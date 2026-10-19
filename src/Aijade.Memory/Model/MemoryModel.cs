namespace Aijade.Memory.Model;


/// <summary>Affective snapshot (PAD), each in [0, 1]; 0.5 is neutral for valence and dominance.</summary>
public readonly record struct Affect(double Valence, double Arousal, double Dominance)
{
    public static Affect Neutral => new(0.5, 0.5, 0.5);
}

public sealed record EpisodeContext(string? SessionId, string? Interlocutor, string? Task, IReadOnlyList<string> Tags);

/// <summary>Content-derived salience driving the memory gate, all in [0, 1].</summary>
public readonly record struct ContentSalience(double Salience, double SocialSalience, double Novelty);

public sealed record Encoding(double Salience, double SocialSalience, double Novelty, Affect Affect);

/// <summary>Temporal validity window; a memory is retrievable only while "now" lies inside it.</summary>
public readonly record struct ValidTime(double? ValidFrom = null, double? ValidUntil = null)
{
    public bool Contains(double now) => !(ValidFrom is { } from && now < from) && !(ValidUntil is { } until && now > until);
}

public enum MemoryType
{
    Episodic,
    Semantic,
    Procedural,
    Working,
    Emotional,
    Relational,
    Reflective,
}

public enum MemoryStatus
{
    Active,
    Expired,
    Superseded,
    Candidate,
    Quarantine,
    Episodic,
    Reviewed,
    Semantic,
    Procedural,
    Consolidated,
    Decayed,
    Archived,
    Retracted,
}

public static class MemoryStatusExtensions
{
    /// <summary>Terminal statuses make a memory non-retrievable.</summary>
    public static bool IsRetrievable(this MemoryStatus s) =>
        s is not (MemoryStatus.Expired or MemoryStatus.Archived or MemoryStatus.Retracted or MemoryStatus.Decayed);
}

public sealed class Episode
{
    public required string Id { get; init; }
    public required string Content { get; init; }
    public required double CreatedAt { get; init; }
    public double LastAccessedAt { get; set; }
    public int AccessCount { get; set; }
    public double BaseStrength { get; init; } = 1;

    /// <summary>Durability multiplier set at encode time from content salience; exactly 1 under NO_GATING.</summary>
    public double Durability { get; init; } = 1;

    public required Encoding Encoding { get; init; }
    public required EpisodeContext Context { get; init; }
    public bool Consolidated { get; set; }

    /// <summary>Set when gating judged the episode not worth keeping and pruned it.</summary>
    public bool Forgotten { get; set; }

    public MemoryType MemoryType { get; init; } = MemoryType.Episodic;
    public MemoryStatus Status { get; set; } = MemoryStatus.Active;
    public ValidTime ValidTime { get; set; }
}

public sealed class SemanticFact
{
    public required string Id { get; init; }
    public required string Content { get; init; }
    public required IReadOnlyList<string> DerivedFrom { get; init; }
    public required double CreatedAt { get; init; }
    public double LastAccessedAt { get; set; }
    public int AccessCount { get; set; }
    public double Confidence { get; init; } = 1;
    public double BaseStrength { get; init; } = 1;
    public double Durability { get; init; } = 1;
    public required IReadOnlyList<string> ContextTags { get; init; }
    public double Salience { get; init; }
    public Affect Affect { get; init; } = Affect.Neutral;
    public MemoryType MemoryType { get; init; } = MemoryType.Semantic;
    public MemoryStatus Status { get; set; } = MemoryStatus.Active;
    public ValidTime ValidTime { get; set; }
}

/// <summary>A how-to / skill memory.</summary>
public sealed class ProceduralMemory
{
    public required string Id { get; init; }
    public required string Content { get; init; }

    /// <summary>The episode or fact the skill was derived from, if any.</summary>
    public string? DerivedFrom { get; init; }

    public required double CreatedAt { get; init; }
    public double LastAccessedAt { get; set; }
    public int AccessCount { get; set; }
    public double BaseStrength { get; init; } = 1;
    public double Durability { get; init; } = 1;
    public IReadOnlyList<string> ContextTags { get; init; } = [];
    public ValidTime ValidTime { get; set; }
    public MemoryStatus Status { get; set; } = MemoryStatus.Active;
    public MemoryType MemoryType { get; init; } = MemoryType.Procedural;

    /// <summary>How well established the skill is, in [0, 1].</summary>
    public double Confidence { get; init; } = 1;
}

/// <summary>A short-term active buffer entry, scoped to the immediate context.</summary>
public sealed class WorkingMemory
{
    public required string Id { get; init; }
    public required string Content { get; init; }
    public required double CreatedAt { get; init; }
    public double LastAccessedAt { get; set; }
    public int AccessCount { get; set; }
    public double BaseStrength { get; init; } = 1;
    public double Durability { get; init; } = 1;
    public IReadOnlyList<string> ContextTags { get; init; } = [];
    public ValidTime ValidTime { get; set; }
    public MemoryStatus Status { get; set; } = MemoryStatus.Active;
    public MemoryType MemoryType { get; init; } = MemoryType.Working;
}

/// <summary>Coefficients mapping content salience onto memory dynamics. All zero = the ungated control.</summary>
public sealed record GatingCoefficients(double KSalience, double KSocial, double KNovelty)
{
    public static GatingCoefficients None { get; } = new(0, 0, 0);
    public static GatingCoefficients Default { get; } = new(0.8, 0.5, 0.3);
    public bool IsNone => KSalience == 0 && KSocial == 0 && KNovelty == 0;
}

public sealed record ForgettingConfig(double BaseDecay = 0.35, double SpacingBeta = 0.5, double AgeScaleMs = 86_400_000);

public sealed record RetrievalWeights(double Similarity = 1, double Strength = 0.6, double Recency = 0.3, double Context = 0.4, double Affect = 0.25)
{
    public static RetrievalWeights Default { get; } = new();

    /// <summary>Recency zeroed — the "dimensional mismatch" correction studied in P3.</summary>
    public static RetrievalWeights Corrected { get; } = new(Recency: 0);
}

public enum RetrievalScoreMode
{
    /// <summary>
    /// Legacy raw weighted sum, kept so pre-fix numbers (P3) stay reproducible. Its conflict penalty scans only the top K, so the
    /// order can change with K; the other modes scan a constant head. Do not use it for new work.
    /// </summary>
    Additive,

    /// <summary>Default: each component z-scored within the candidate pool, then weighted.</summary>
    Standardized,

    /// <summary>Opt-in Reciprocal Rank Fusion (k = 60).</summary>
    Rrf,
}

public sealed record MemoryConfig
{
    public GatingCoefficients Gating { get; init; } = GatingCoefficients.Default;
    public ForgettingConfig Forgetting { get; init; } = new();
    public RetrievalWeights Weights { get; init; } = RetrievalWeights.Default;
    public int ConsolidateThreshold { get; init; } = 8;
    /// <summary>
    /// The score a candidate must exceed to count as delivered in the memory evaluations. It is an absolute value set for the
    /// additive and standardized score domains; Reciprocal Rank Fusion scores lie below about 0.04, so the floor is not
    /// meaningful there (P3 §5.4) and RRF results should be read by rank. <see cref="BioticMemory.Retrieve"/> does not apply it.
    /// </summary>
    public double RetrievalFloor { get; init; } = 0.02;
    public RetrievalScoreMode RetrievalScoreMode { get; init; } = RetrievalScoreMode.Standardized;
    public bool DedupeByContent { get; init; } = true;

    /// <summary>
    /// Multiplier for the older side of a conflicting pair among the leading candidates (same entity token, different
    /// negation). It is applied once per pair, so it compounds, and the older item always loses: it acts as a second recency
    /// bias. P3 measures its cost (switching it off raises standardised delivered recall@8 from 0.199 to 0.548 on LoCoMo);
    /// the precision of the conflict test on genuine contradictions has not been evaluated. Research kernel only.
    /// </summary>
    public double ConflictPenalty { get; init; } = 0.5;

    /// <summary>Opt-in §38 fault injection on retrieval results; null or disabled = no effect.</summary>
    public Interventions.FaultInjectionConfig? FaultInjection { get; init; }

    /// <summary>Hormones modulate presentation only (never memory); off = neutral presentation.</summary>
    public bool PhysiologyEnabled { get; init; } = true;

    public Beliefs.BeliefConfig Belief { get; init; } = Beliefs.BeliefConfig.Default;

    /// <summary>The HAC + CDI closed loop; constructed only when <c>Hac.Enabled</c> (opt-in, H2c guard).</summary>
    public Hac.HacConfig? Hac { get; init; }

    public Identity.CdiConfig? Cdi { get; init; }

    /// <summary>The §38 intervention API; resolved only when enabled.</summary>
    public Interventions.InterventionConfig? Intervention { get; init; }

    /// <summary>The §12 replay log; constructed only when enabled.</summary>
    public Replay.CbrConfig? Cbr { get; init; }

    /// <summary>Opt-in persistence (§26); not part of a snapshot — the restoring instance supplies its own.</summary>
    [System.Text.Json.Serialization.JsonIgnore]
    public Storage.IStorageAdapter? Storage { get; init; }

    public static MemoryConfig Default { get; } = new();
}

public enum CandidateKind
{
    Episode,
    Fact,
    Procedural,
    Working,
}

public sealed record ScoreZ(double Similarity, double Strength, double Recency, double Context);

/// <summary>Component scores, exposed so a surprising retrieval can be explained.</summary>
public sealed record ScoreParts
{
    public double Similarity { get; init; }
    public double Strength { get; init; }
    public double Recency { get; init; }
    public double Context { get; init; }
    public double Affect { get; init; }
    public double? Noise { get; init; }
    public bool Conflict { get; set; }
    public ScoreZ? Z { get; init; }
    public IReadOnlyList<string>? DeduplicatedIds { get; init; }
}

public sealed record ScoredCandidate(CandidateKind Kind, string Id, string Content, double Score, ScoreParts Parts);
