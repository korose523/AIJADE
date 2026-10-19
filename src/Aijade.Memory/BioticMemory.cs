using System.Text.RegularExpressions;

using Aijade.Memory.Dynamics;
using Aijade.Memory.Interventions;
using Aijade.Memory.Lexical;
using Aijade.Memory.Model;
using Aijade.Memory.Retrieval;
using Aijade.Memory.Salience;
using Aijade.Core.Js;

namespace Aijade.Memory;

// This file holds the encode / consolidate / retrieve core; the belief graph, the HAC + CDI loop, the research hooks (interventions, CBR) and
// storage live in the other BioticMemory.*.cs parts. Every opt-in subsystem is absent unless enabled, so the baseline
// memory dynamics are never perturbed (H2c guard).

public sealed record EncodeInput(
    string Id, string Content, double CreatedAt, EpisodeContext Context, double BaseStrength = 1, Affect? Affect = null,
    double? SalienceOverride = null);

/// <summary>Turns episodes into semantic facts.</summary>
public interface IDistiller
{
    IReadOnlyList<SemanticFact> Distill(IReadOnlyList<Episode> episodes);
}

/// <summary>Deterministic per-episode consolidation: one fact per episode, content and provenance carried over.</summary>
public sealed class LexicalDistiller : IDistiller
{
    public IReadOnlyList<SemanticFact> Distill(IReadOnlyList<Episode> episodes) => episodes.Select(e => new SemanticFact
    {
        Id = $"fact_{e.Id}",
        Content = e.Content,
        DerivedFrom = [e.Id],
        CreatedAt = e.CreatedAt,
        LastAccessedAt = e.CreatedAt,
        BaseStrength = e.BaseStrength,
        Durability = e.Durability,
        ContextTags = e.Context.Tags,
        Salience = e.Encoding.Salience,
        Affect = e.Encoding.Affect,
    }).ToList();
}

public sealed record ConsolidationResult(IReadOnlyList<SemanticFact> Facts, IReadOnlyList<string> Consumed, IReadOnlyList<(string EpisodeId, string Reason)> Skipped);

/// <summary>
/// The biomimetic long-term memory store. Two instances differ only in their gating configuration; everything
/// else (corpus, weights, forgetting curve, distiller) is held fixed — that is the whole ablation.
/// </summary>
public sealed partial class BioticMemory
{
    /// <summary>Content salience above this marks a memory worth keeping under selective consolidation.</summary>
    private const double SalienceThreshold = 0.5;

    /// <summary>Top candidates scanned for conflicts in the modern score modes — a constant, so retrieve(q, K) prefixes agree.</summary>
    private const int ConflictRerankPool = 150;

    private static readonly int NoveltyFeature = SaliencePredictor.FeatureIndex("noveltyIdf");
    private static readonly Regex NonLetters = new("[^A-Za-z]", JsText.Options(false));
    private static readonly Regex Capitalised = new("^[A-Z][a-z]+$", JsText.Options(false));

    private LexicalIndex? _index;

    public MemoryConfig Config { get; set; }
    public List<Episode> Episodes { get; } = [];
    public List<SemanticFact> Facts { get; } = [];
    public List<ProceduralMemory> Procedural { get; } = [];
    public List<WorkingMemory> Working { get; } = [];
    public double Now { get; private set; }

    /// <summary>The layered L3 state (presentation only — never gates memory).</summary>
    public PhysiologicalStateV3 Mood { get; set; } = NeutralPhysiology;

    /// <summary>The last computed presentation modulation (for inspection; not used in scoring).</summary>
    public PresentationModulation LastPresentation { get; private set; } = PresentationModulation.Neutral;

    private static readonly HormoneLevels Mid = new(0.5, 0.5, 0.5, 0.5, 0.5);

    public static PhysiologicalStateV3 NeutralPhysiology { get; } = new(Mid, Mid, Mid, Affect.Neutral, 0.5);

    public void SetNow(double ms)
    {
        Now = ms;
        _index = null;
    }

    private static double Clamp01(double x) => Math.Min(1, Math.Max(0, x));

    private static double Sigmoid(double z) => 1 / (1 + Math.Exp(-z));

    /// <summary>Social-salience proxy: second-person and person-name density over length.</summary>
    private static double DeriveSocialSalience(string content)
    {
        var tokens = Tokenizer.Tokenize(content);
        var you = tokens.Count(t => t is "you" or "your" or "yours" or "yourself");
        var names = JsText.SplitOnSpace(content).Count(w => Capitalised.IsMatch(NonLetters.Replace(w, "")));
        var len = Math.Max(8, tokens.Count);
        return Math.Min(1, (double)(you + names) / len);
    }

    /// <summary>Encode one episode; durability comes from content salience under the gating config.</summary>
    public Episode Encode(EncodeInput input)
    {
        var ctx = SalienceContext.Empty;
        var salience = input.SalienceOverride is { } o ? Clamp01(o) : Clamp01(Sigmoid(SaliencePredictor.PredictV2(input.Content, ctx).Score));
        var social = DeriveSocialSalience(input.Content);
        var novelty = Clamp01(NoveltyFeature >= 0 ? SaliencePredictor.FeatureVector(input.Content, ctx)[NoveltyFeature] : 0.5);
        var episode = new Episode
        {
            Id = input.Id,
            Content = input.Content,
            CreatedAt = input.CreatedAt,
            LastAccessedAt = input.CreatedAt,
            BaseStrength = input.BaseStrength,
            Durability = Gating.Durability(new ContentSalience(salience, social, novelty), Config.Gating),
            Encoding = new Encoding(salience, social, novelty, input.Affect ?? Affect.Neutral),
            Context = input.Context,
        };
        Episodes.Add(episode);
        _index = null;
        Flush();
        return episode;
    }

    /// <summary>Encode a procedural (how-to / skill) memory; the id defaults to proc_{count}_{now}.</summary>
    public ProceduralMemory EncodeProcedural(string content, string? id = null, double? createdAt = null, string? derivedFrom = null,
        double baseStrength = 1, double durability = 1, IReadOnlyList<string>? contextTags = null, ValidTime validTime = default,
        MemoryStatus status = MemoryStatus.Active, double confidence = 1)
    {
        var at = createdAt ?? Now;
        var m = new ProceduralMemory
        {
            Id = id ?? $"proc_{Procedural.Count}_{Core.Js.JsFormat.Number(Now)}",
            Content = content,
            DerivedFrom = derivedFrom,
            CreatedAt = at,
            LastAccessedAt = at,
            BaseStrength = baseStrength,
            Durability = durability,
            ContextTags = contextTags ?? [],
            ValidTime = validTime,
            Status = status,
            Confidence = confidence,
        };
        Procedural.Add(m);
        _index = null;
        Flush();
        return m;
    }

    /// <summary>Encode a working-memory (short-term buffer) entry; the id defaults to work_{count}_{now}.</summary>
    public WorkingMemory EncodeWorking(string content, string? id = null, double? createdAt = null, double baseStrength = 1, double durability = 1,
        IReadOnlyList<string>? contextTags = null, ValidTime validTime = default, MemoryStatus status = MemoryStatus.Active)
    {
        var at = createdAt ?? Now;
        var m = new WorkingMemory
        {
            Id = id ?? $"work_{Working.Count}_{Core.Js.JsFormat.Number(Now)}",
            Content = content,
            CreatedAt = at,
            LastAccessedAt = at,
            BaseStrength = baseStrength,
            Durability = durability,
            ContextTags = contextTags ?? [],
            ValidTime = validTime,
            Status = status,
        };
        Working.Add(m);
        _index = null;
        Flush();
        return m;
    }

    /// <summary>
    /// Distil pending episodes into facts. Selective when content gating is active (salience above 0.5, or the top
    /// <paramref name="keepFraction"/> by salience); the rest are marked forgotten. Under NO_GATING nothing is pruned.
    /// </summary>
    public ConsolidationResult Consolidate(IDistiller? distiller = null, bool? selective = null, double? keepFraction = null)
    {
        distiller ??= new LexicalDistiller();
        return ConsolidateCoreAsync(eps => Task.FromResult(distiller.Distill(eps)), selective, keepFraction).GetAwaiter().GetResult();
    }

    /// <summary>The same consolidation with a distiller that may call a model (e.g. <see cref="LlmDistiller"/>).</summary>
    public Task<ConsolidationResult> ConsolidateAsync(IAsyncDistiller distiller, bool? selective = null, double? keepFraction = null, CancellationToken cancellationToken = default) =>
        ConsolidateCoreAsync(eps => distiller.DistillAsync(eps, cancellationToken), selective, keepFraction);

    private async Task<ConsolidationResult> ConsolidateCoreAsync(Func<IReadOnlyList<Episode>, Task<IReadOnlyList<SemanticFact>>> distil, bool? selective, double? keepFraction)
    {

        var pending = Episodes.Where(e => !e.Consolidated && !e.Forgotten).ToList();
        if (pending.Count < Config.ConsolidateThreshold)
            return new ConsolidationResult([], [], []);
        var g = Config.Gating;
        var isSelective = selective ?? (g.KSalience != 0 || g.KSocial != 0);

        HashSet<string>? keep = null;
        if (isSelective)
        {
            if (keepFraction is { } frac)
            {
                var k = Math.Max(1, Math.Min(pending.Count, (int)Math.Round(pending.Count * Clamp01(frac), MidpointRounding.AwayFromZero)));
                keep = pending.OrderByDescending(e => e.Encoding.Salience).Take(k).Select(e => e.Id).ToHashSet();
            }
            else
            {
                keep = pending.Where(e => e.Encoding.Salience > SalienceThreshold).Select(e => e.Id).ToHashSet();
            }
        }

        var selected = keep is null ? pending : pending.Where(e => keep.Contains(e.Id)).ToList();
        var facts = await distil(selected).ConfigureAwait(false);
        Facts.AddRange(facts);
        foreach (var e in selected)
            e.Consolidated = true;
        var pruned = keep is null ? [] : pending.Where(e => !keep.Contains(e.Id)).ToList();
        foreach (var e in pruned)
            e.Forgotten = true;
        _index = null;
        Flush();
        var reason = keepFraction is { } kf
            ? $"outranked under quantile retention (keepFraction={Core.Js.JsFormat.Number(kf)})"
            : "not selected by content-salience gating (pruned)";
        return new ConsolidationResult(facts, selected.Select(e => e.Id).ToList(), pruned.Select(e => (e.Id, reason)).ToList());
    }

    private LexicalIndex EnsureIndex() => _index ??= new LexicalIndex(
        Episodes.Where(e => !e.Forgotten).Select(e => (e.Id, e.Content))
            .Concat(Facts.Select(f => (f.Id, f.Content)))
            .Concat(Procedural.Select(p => (p.Id, p.Content)))
            .Concat(Working.Select(w => (w.Id, w.Content))));

    private sealed record Item(
        CandidateKind Kind, string Id, string Content, double CreatedAt, int AccessCount, double BaseStrength, double Durability,
        double Salience, double SocialSalience, double Novelty, IReadOnlyList<string> ContextTags) : IDedupable;

    private sealed class Scored(Item item, double score, ScoreParts parts)
    {
        public Item Item { get; } = item;
        public double Score { get; set; } = score;
        public ScoreParts Parts { get; set; } = parts;
    }

    /// <summary>Top-K candidates for a query, with content-salience noise and the R-conflict penalty.</summary>
    public IReadOnlyList<ScoredCandidate> Retrieve(string query, int topK = 10, bool bump = true, RetrievalWeights? weights = null)
    {
        var idx = EnsureIndex();
        var qVec = idx.QuerySparse(query);
        var queryTags = Tokenizer.Tokenize(query);
        var f = Config.Forgetting;
        var g = Config.Gating;
        var w = weights ?? Config.Weights;
        var now = Now;

        // Hormones affect presentation only: the modulation is computed for audit and never enters a score.
        if (Config.PhysiologyEnabled)
            LastPresentation = Plasticity.DerivePresentation(Mood, true);

        var items = Episodes
            .Where(e => !e.Forgotten && e.Status.IsRetrievable() && e.ValidTime.Contains(now))
            .Select(e => new Item(CandidateKind.Episode, e.Id, e.Content, e.CreatedAt, e.AccessCount, e.BaseStrength, e.Durability,
                e.Encoding.Salience, e.Encoding.SocialSalience, e.Encoding.Novelty, e.Context.Tags))
            .Concat(Facts
                .Where(fc => fc.Status.IsRetrievable() && fc.ValidTime.Contains(now))
                .Select(fc => new Item(CandidateKind.Fact, fc.Id, fc.Content, fc.CreatedAt, fc.AccessCount, fc.BaseStrength, fc.Durability,
                    fc.Salience, 0.5, 0.5, fc.ContextTags)))
            .Concat(Procedural
                .Where(p => p.Status.IsRetrievable() && p.ValidTime.Contains(now))
                .Select(p => new Item(CandidateKind.Procedural, p.Id, p.Content, p.CreatedAt, p.AccessCount, p.BaseStrength, p.Durability, 0.5, 0.5, 0.5, p.ContextTags)))
            .Concat(Working
                .Where(wm => wm.Status.IsRetrievable() && wm.ValidTime.Contains(now))
                .Select(wm => new Item(CandidateKind.Working, wm.Id, wm.Content, wm.CreatedAt, wm.AccessCount, wm.BaseStrength, wm.Durability, 0.5, 0.5, 0.5, wm.ContextTags)))
            .ToList();

        var (ranked, absorbed) = Config.DedupeByContent
            ? Scoring.CollapseDuplicateContent(items)
            : (items, new Dictionary<string, List<string>>());

        var rows = ranked.Select(it => new RawScoreRow(
            idx.Cosine(qVec, it.Id),
            Forgetting.RetrievalStrength(it.CreatedAt, it.AccessCount, it.BaseStrength, it.Durability, now, f, g, it.Salience),
            1 / (1 + (Math.Max(0, now - it.CreatedAt) / f.AgeScaleMs)),
            Scoring.Jaccard(queryTags, it.ContextTags),
            0)).ToList();

        var fused = Config.RetrievalScoreMode switch
        {
            RetrievalScoreMode.Additive => null,
            RetrievalScoreMode.Rrf => Scoring.ScoreRrf(rows, w),
            _ => Scoring.ScoreStandardized(rows, w),
        };

        var scored = new List<Scored>(ranked.Count);
        for (var i = 0; i < ranked.Count; i++)
        {
            var it = ranked[i];
            var gate = Plasticity.GateFromContent(new ContentSalience(it.Salience, it.SocialSalience, it.Novelty));
            double baseScore;
            ScoreParts parts;
            if (fused is not null)
            {
                baseScore = fused[i].Score;
                parts = fused[i].RawParts with { Z = fused[i].Z };
            }
            else
            {
                (baseScore, parts) = Scoring.ScoreAdditive(rows[i], w);
            }
            if (absorbed.TryGetValue(it.Id, out var absorbedIds))
                parts = parts with { DeduplicatedIds = absorbedIds };
            var noisy = Plasticity.ApplyRetrievalNoise(baseScore, it.Id, gate.RetrievalNoise);
            if (_hac is not null)
            {
                // v7 §9.5 cognitive-load retrieval degradation: a cost growing with load c_t, which keeps HAC falsifiable.
                noisy += _hac.Degradation(HacRng());
            }
            scored.Add(new Scored(it, noisy, parts with { Noise = gate.RetrievalNoise }));
        }

        // R-conflict penalty: among the scanned head, the older (then lower-durability) side of a conflicting pair loses.
        var head = fused is not null ? ConflictRerankPool : topK;
        scored = StableSortDescending(scored);
        var top = scored.Take(head).ToList();
        // Entities and polarity depend only on the text, so compute them once per candidate instead of once per pair.
        var entities = top.Select(s => Scoring.EntityTokens(s.Item.Content)).ToArray();
        var negated = top.Select(s => Scoring.HasNegation(s.Item.Content)).ToArray();
        for (var i = 0; i < top.Count; i++)
        {
            for (var j = i + 1; j < top.Count; j++)
            {
                if (negated[i] == negated[j] || !entities[i].Overlaps(entities[j]))
                    continue;
                var loser = Loser(top[i], top[j]);
                loser.Score *= Config.ConflictPenalty;
                loser.Parts.Conflict = true;
            }
        }
        scored = StableSortDescending(scored);
        IReadOnlyList<ScoredCandidate> final = scored.Take(topK).Select(s => new ScoredCandidate(s.Item.Kind, s.Item.Id, s.Item.Content, s.Score, s.Parts)).ToList();

        // §38 opt-in fault injection. Default off, so the default path is unchanged (H2c). A component crash is
        // caught and degrades to the remaining healthy stores: the fail-closed path.
        LastFaultReport = null;
        if (Config.FaultInjection is { Enabled: true } fault)
        {
            try
            {
                (final, LastFaultReport) = new FaultInjector(fault).Apply(final);
            }
            catch (FaultInjectedException crash)
            {
                final = final.Where(c => c.Kind != crash.Component).ToList();
                LastFaultReport = crash.Report;
            }
        }

        if (bump)
        {
            foreach (var c in final)
            {
                if (Episodes.Find(e => e.Id == c.Id) is { } ep)
                {
                    ep.AccessCount++;
                    ep.LastAccessedAt = now;
                }
                else if (Facts.Find(x => x.Id == c.Id) is { } fact)
                {
                    fact.AccessCount++;
                    fact.LastAccessedAt = now;
                }
                else if (Procedural.Find(x => x.Id == c.Id) is { } proc)
                {
                    proc.AccessCount++;
                    proc.LastAccessedAt = now;
                }
                else if (Working.Find(x => x.Id == c.Id) is { } work)
                {
                    work.AccessCount++;
                    work.LastAccessedAt = now;
                }
            }
        }
        return final;
    }

    /// <summary>Score one stored memory under a query, reusing the retrieval scoring.</summary>
    public ScoredCandidate? ScoreCandidateById(string query, string id) => Retrieve(query, 9999, false).FirstOrDefault(c => c.Id == id);

    /// <summary>The report of the last retrieval's injected fault; null when fault injection is off.</summary>
    public FaultReport? LastFaultReport { get; private set; }

    /// <summary>JavaScript's Array.prototype.sort is stable; ties keep their relative order.</summary>
    private static List<Scored> StableSortDescending(List<Scored> xs) => xs.OrderByDescending(s => s.Score).ToList();

    /// <summary>Newer wins, then higher durability; otherwise the second argument loses.</summary>
    private static Scored Loser(Scored a, Scored b)
    {
        if (a.Item.CreatedAt != b.Item.CreatedAt)
            return a.Item.CreatedAt > b.Item.CreatedAt ? b : a;
        if (a.Item.Durability != b.Item.Durability)
            return a.Item.Durability > b.Item.Durability ? b : a;
        return b;
    }
}
