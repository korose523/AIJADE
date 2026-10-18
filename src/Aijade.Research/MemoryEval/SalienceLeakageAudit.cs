using Aijade.Memory.Locomo;
using Aijade.Memory.Salience;

namespace Aijade.Research.MemoryEval;

// P4 / J5 §5.5, a negative audit: does the leave-one-conversation-out AUC of the learned salience model owe anything to
// leakage? Ported from the author's own p2-salience-nested audit. Three estimates with the same features and the same fit
// (L2-regularised logistic regression, plain gradient descent):
//   1. LOCV-original — standardisation statistics over the whole corpus, all features, leave one conversation out;
//   2. LOCV-trainStd — the same, standardisation computed on the training folds only (removes one leak);
//   3. Nested-Train — outer leave-one-out; inner greedy forward feature selection on the nine training conversations only
//      (criterion: their mean resubstitution AUC), IDF and standardisation also from the training folds.
// (1) − (2) is the standardisation leak, (2) − (3) the feature-selection leak. Labels: the episode is cited as evidence.

public sealed record LeakageAuditResult(int Rows, int Positives, int Features, double LocvOriginal, double LocvTrainStd, double Nested,
    IReadOnlyList<(int Fold, double Auc, IReadOnlyList<string> Selected)> Folds);

public static class SalienceLeakageAudit
{
    private const int Iterations = 600;
    private const double LearningRate = 0.2, Lambda = 1;

    private sealed record Row(int Conv, int Y, double[] X);

    private static (Dictionary<string, double> Idf, int NDocs) Idf(IEnumerable<LocomoConversation> convs) =>
        SaliencePredictor.BuildCorpusIdf(convs.SelectMany(c => c.Episodes.Select(e => e.Content)));

    private static List<Row> Rows(IReadOnlyList<(int Index, LocomoConversation Conv)> convs, Dictionary<string, double> idf, int nDocs)
    {
        var rows = new List<Row>();
        foreach (var (ci, c) in convs)
        {
            var priors = new List<string>();
            foreach (var e in c.Episodes)
            {
                rows.Add(new Row(ci, c.EvidenceIds.Contains(e.Id) ? 1 : 0, SaliencePredictor.FeatureVector(e.Content, new SalienceContext([.. priors], idf, nDocs))));
                priors.Add(e.Content);
            }
        }
        return rows;
    }

    private static (double[] Mean, double[] Sd) Stats(IReadOnlyList<Row> rows)
    {
        var dim = rows[0].X.Length;
        var mean = new double[dim];
        var sd = new double[dim];
        foreach (var r in rows)
        {
            for (var j = 0; j < dim; j++)
                mean[j] += r.X[j];
        }
        for (var j = 0; j < dim; j++)
            mean[j] /= rows.Count;
        foreach (var r in rows)
        {
            for (var j = 0; j < dim; j++)
                sd[j] += Math.Pow(r.X[j] - mean[j], 2);
        }
        for (var j = 0; j < dim; j++)
        {
            sd[j] = Math.Sqrt(sd[j] / rows.Count);
            if (sd[j] == 0)
                sd[j] = 1;
        }
        return (mean, sd);
    }

    private static List<Row> Standardize(IReadOnlyList<Row> rows, (double[] Mean, double[] Sd) s) =>
        [.. rows.Select(r => r with { X = [.. r.X.Select((v, j) => (v - s.Mean[j]) / s.Sd[j])] })];

    private static double Sigmoid(double z) => z > 0 ? 1 / (1 + Math.Exp(-z)) : Math.Exp(z) / (1 + Math.Exp(z));

    private static double[] Fit(List<double[]> x, List<int> y)
    {
        var n = x.Count;
        var dim = x[0].Length;
        var w = new double[dim];
        var gw = new double[dim];
        double b = 0;
        for (var it = 0; it < Iterations; it++)
        {
            Array.Clear(gw);
            double gb = 0;
            for (var i = 0; i < n; i++)
            {
                var xi = x[i];
                var z = b;
                for (var j = 0; j < dim; j++)
                    z += xi[j] * w[j];
                var err = Sigmoid(z) - y[i];
                for (var j = 0; j < dim; j++)
                    gw[j] += err * xi[j];
                gb += err;
            }
            for (var j = 0; j < dim; j++)
                w[j] -= LearningRate * ((gw[j] + (Lambda * w[j])) / n);
            b -= LearningRate * (gb / n);
        }
        return [b, .. w];
    }

    private static double[] Predict(double[] w, IReadOnlyList<double[]> x) =>
        [.. x.Select(xi => w[0] + xi.Select((v, j) => v * w[j + 1]).Sum())];

    private static List<double[]> Sub(IReadOnlyList<Row> rows, IReadOnlyList<int> idx) => [.. rows.Select(r => idx.Select(j => r.X[j]).ToArray())];

    private static double Locv(IReadOnlyList<LocomoConversation> convs, bool trainStd)
    {
        var (idf, nDocs) = Idf(convs); // unsupervised, over the whole corpus
        var rows = Rows([.. convs.Select((c, i) => (i, c))], idf, nDocs);
        if (!trainStd)
            rows = Standardize(rows, Stats(rows));
        var scores = new double[rows.Count];
        var folds = ParallelMap.Map(convs, (_, ci) =>
        {
            var train = rows.Where(r => r.Conv != ci).ToList();
            var testIdx = Enumerable.Range(0, rows.Count).Where(i => rows[i].Conv == ci).ToList();
            var test = testIdx.Select(i => rows[i]).ToList();
            if (trainStd)
            {
                var s = Stats(train);
                train = Standardize(train, s);
                test = Standardize(test, s);
            }
            var w = Fit([.. train.Select(r => r.X)], [.. train.Select(r => r.Y)]);
            return (TestIdx: testIdx, Scores: Predict(w, [.. test.Select(r => r.X)]));
        });
        foreach (var (testIdx, sc) in folds)
        {
            for (var k = 0; k < testIdx.Count; k++)
                scores[testIdx[k]] = sc[k];
        }
        return SaliencePredictor.Auc(scores, [.. rows.Select(r => r.Y)]);
    }

    private static double TrainAverageAuc(IReadOnlyList<Row> rows, IReadOnlyList<int> idx)
    {
        var x = Sub(rows, idx);
        var y = rows.Select(r => r.Y).ToList();
        var sc = Predict(Fit(x, y), x);
        return rows.Select((r, i) => (r.Conv, i)).GroupBy(p => p.Conv).Average(g => SaliencePredictor.Auc([.. g.Select(p => sc[p.i])], [.. g.Select(p => y[p.i])]));
    }

    private static List<int> GreedyForward(IReadOnlyList<Row> rows)
    {
        var n = rows[0].X.Length;
        var selected = new List<int>();
        var best = 0.5;
        while (selected.Count < n)
        {
            int add = -1;
            var addAuc = best;
            for (var f = 0; f < n; f++)
            {
                if (selected.Contains(f))
                    continue;
                var a = TrainAverageAuc(rows, [.. selected, f]);
                if (a > addAuc)
                    (add, addAuc) = (f, a);
            }
            if (add < 0)
                break;
            selected.Add(add);
            best = addAuc;
        }
        return selected;
    }

    public static LeakageAuditResult Run(IReadOnlyList<LocomoConversation> convs)
    {
        var allRows = convs.Sum(c => c.Episodes.Count);
        var positives = convs.Sum(c => c.Episodes.Count(e => c.EvidenceIds.Contains(e.Id)));
        var locvOriginal = Locv(convs, trainStd: false);
        var locvTrainStd = Locv(convs, trainStd: true);
        var outer = ParallelMap.Map(convs, (_, ci) =>
        {
            var trainConvs = convs.Select((c, i) => (i, c)).Where(p => p.i != ci).ToList();
            var (idf, nDocs) = Idf(trainConvs.Select(p => p.c));
            var s = Stats(Rows(trainConvs, idf, nDocs));
            var train = Standardize(Rows(trainConvs, idf, nDocs), s);
            var test = Standardize(Rows([(ci, convs[ci])], idf, nDocs), s);
            var selected = GreedyForward(train);
            var w = Fit(Sub(train, selected), [.. train.Select(r => r.Y)]);
            var sc = Predict(w, Sub(test, selected));
            return (Scores: sc, Labels: test.Select(r => r.Y).ToList(), Selected: selected);
        });
        var pooledScores = outer.SelectMany(o => o.Scores).ToList();
        var pooledLabels = outer.SelectMany(o => o.Labels).ToList();
        var folds = outer.Select((o, ci) => (ci, SaliencePredictor.Auc(o.Scores, o.Labels), (IReadOnlyList<string>)[.. o.Selected.Select(j => SaliencePredictor.Features[j].Name)])).ToList();
        return new LeakageAuditResult(allRows, positives, SaliencePredictor.Features.Count, locvOriginal, locvTrainStd,
            SaliencePredictor.Auc(pooledScores, pooledLabels), folds);
    }
}
