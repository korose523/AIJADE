using System.Text.RegularExpressions;

using Aijade.Core.Js;

namespace Aijade.Memory.Lexical;

// A hashed bag-of-words TF-IDF cosine: deliberately simple and held constant across experimental conditions, so a
// measured difference comes from the memory dynamics rather than from embedding quality.
// Summation follows first-insertion order exactly, so scores are reproduced bit for bit.

/// <summary>Sparse vector whose entries keep insertion order (summation order matters for exact reproduction).</summary>
public sealed class SparseVector
{
    private readonly List<(int Index, double Weight)> _entries = [];
    private readonly Dictionary<int, double> _lookup = [];

    public IReadOnlyList<(int Index, double Weight)> Entries => _entries;

    public double Norm { get; internal set; }

    internal void Set(int index, double weight)
    {
        if (_lookup.ContainsKey(index))
        {
            var at = _entries.FindIndex(e => e.Index == index);
            _entries[at] = (index, weight);
        }
        else
        {
            _entries.Add((index, weight));
        }
        _lookup[index] = weight;
    }

    public bool TryGet(int index, out double weight) => _lookup.TryGetValue(index, out weight);
}

public static class Tokenizer
{
    private static readonly HashSet<string> Stop =
    [
        "the", "a", "an", "and", "or", "but", "if", "then", "else", "when", "at", "by", "for", "with", "about", "against",
        "between", "into", "through", "during", "before", "after", "above", "below", "to", "from", "up", "down", "in", "out",
        "on", "off", "over", "under", "again", "further", "is", "are", "was", "were", "be", "been", "being", "have", "has",
        "had", "do", "does", "did", "of", "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they", "me",
        "him", "her", "us", "them", "my", "your", "his", "its", "our", "their", "what", "which", "who", "whom", "where", "why",
        "how", "all", "any", "both", "each", "few", "more", "most", "some", "such", "no", "nor", "not", "only", "own", "same",
        "so", "than", "too", "very", "can", "will", "just", "dont", "should", "now", "im", "yeah", "yes", "got", "get",
        "really", "like", "love", "great",
    ];

    private static readonly Regex NonAlphanumeric = new("[^a-z0-9" + JsText.SpaceChars + "]", JsText.Options(ignoreCase: false));

    /// <summary>Lower-case, replace everything but [a-z0-9] and whitespace by spaces, split, drop 1-char tokens and stop words.</summary>
    public static IReadOnlyList<string> Tokenize(string text) =>
        JsText.SplitOnSpace(NonAlphanumeric.Replace(JsText.Lower(text), " "))
            .Where(t => t.Length > 1 && !Stop.Contains(t))
            .ToList();

    /// <summary>Dense cosine (kept for tests).</summary>
    public static double Cosine(ReadOnlySpan<double> a, ReadOnlySpan<double> b)
    {
        double dot = 0, na = 0, nb = 0;
        for (var i = 0; i < a.Length; i++)
        {
            dot += a[i] * b[i];
            na += a[i] * a[i];
            nb += b[i] * b[i];
        }
        var denom = Math.Sqrt(na) * Math.Sqrt(nb);
        return denom == 0 ? 0 : dot / denom;
    }

    /// <summary>Token-level F1, the standard LoCoMo factual metric.</summary>
    public static double TokenF1(string prediction, string gold)
    {
        var p = Tokenize(prediction).ToHashSet();
        var g = Tokenize(gold).ToHashSet();
        if (p.Count == 0 && g.Count == 0)
            return 1;
        if (p.Count == 0 || g.Count == 0)
            return 0;
        var common = p.Count(g.Contains);
        var precision = (double)common / p.Count;
        var recall = (double)common / g.Count;
        return precision + recall == 0 ? 0 : 2 * precision * recall / (precision + recall);
    }
}

/// <summary>TF-IDF index over a fixed document set, with precomputed sparse vectors and L2 norms.</summary>
public sealed class LexicalIndex
{
    private readonly Dictionary<string, int> _vocabIndex = [];
    private readonly List<double> _idf = [];
    private readonly Dictionary<string, SparseVector> _docs = [];

    public LexicalIndex(IEnumerable<(string Id, string Text)> docs)
    {
        var list = docs.ToList();
        var df = new Dictionary<string, int>();
        var vocabOrder = new List<string>();
        var tokenized = new List<IReadOnlyList<string>>(list.Count);
        foreach (var (_, text) in list)
        {
            var tokens = Tokenizer.Tokenize(text);
            foreach (var t in tokens)
            {
                if (df.TryGetValue(t, out var c))
                {
                    df[t] = c + 1;
                }
                else
                {
                    df[t] = 1;
                    vocabOrder.Add(t);
                }
            }
            tokenized.Add(tokens);
        }
        var n = list.Count;
        foreach (var term in vocabOrder)
        {
            _vocabIndex[term] = _idf.Count;
            _idf.Add(Math.Log((n + 1.0) / (df[term] + 1)) + 1);
        }
        for (var i = 0; i < list.Count; i++)
            _docs[list[i].Id] = ToSparse(tokenized[i]);
    }

    public int Dimension => _idf.Count;

    private SparseVector ToSparse(IReadOnlyList<string> tokens)
    {
        // Term frequencies in first-occurrence order.
        var tf = new Dictionary<string, int>();
        var order = new List<string>();
        foreach (var t in tokens)
        {
            if (tf.TryGetValue(t, out var c))
            {
                tf[t] = c + 1;
            }
            else
            {
                tf[t] = 1;
                order.Add(t);
            }
        }
        var vector = new SparseVector();
        var norm = 0.0;
        foreach (var term in order)
        {
            if (!_vocabIndex.TryGetValue(term, out var idx))
                continue;
            var w = (1 + Math.Log(tf[term])) * _idf[idx];
            vector.Set(idx, w);
            norm += w * w;
        }
        vector.Norm = Math.Sqrt(norm);
        return vector;
    }

    /// <summary>Dense vector (vocabulary length) for arbitrary text.</summary>
    public double[] Embed(string text)
    {
        var v = new double[Dimension];
        foreach (var (idx, w) in ToSparse(Tokenizer.Tokenize(text)).Entries)
            v[idx] = w;
        return v;
    }

    public double[] DenseVector(string id)
    {
        var v = new double[Dimension];
        if (_docs.TryGetValue(id, out var sp))
        {
            foreach (var (idx, w) in sp.Entries)
                v[idx] = w;
        }
        return v;
    }

    public SparseVector QuerySparse(string text) => ToSparse(Tokenizer.Tokenize(text));

    /// <summary>Cosine of a query against a stored document (intersection dot product).</summary>
    public double Cosine(SparseVector query, string id)
    {
        if (!_docs.TryGetValue(id, out var sp) || sp.Norm == 0 || query.Norm == 0)
            return 0;
        var dot = 0.0;
        foreach (var (idx, w) in query.Entries)
        {
            if (sp.TryGet(idx, out var dw) && dw != 0)
                dot += w * dw;
        }
        var denom = query.Norm * sp.Norm;
        return denom == 0 ? 0 : dot / denom;
    }
}
