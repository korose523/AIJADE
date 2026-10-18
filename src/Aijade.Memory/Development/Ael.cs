using System.Text.Json.Nodes;

using Aijade.Memory.Contracts;
using Aijade.Memory.Kernel;

namespace Aijade.Memory.Development;

// v8 §48 AEL, Autonomous Epistemic Learning: "search → summarise" becomes a bounded, evidence-graded loop. Every quest
// declares stop conditions up front, external content is quarantined before it can influence beliefs, source lineage
// is kept so reposts of one origin cannot pass as multi-source validation, and conclusions are graded by evidence
// quality, not by vote. Pure and deterministic; budgets and consent are wired by the store / config layer.

/// <summary>The 14 pipeline stages (§48.1) followed by the exceptional states any stage may enter.</summary>
public enum QuestStage
{
    Observe,
    FormQuestion,
    ScopeAndBudget,
    PlanSources,
    Search,
    Acquire,
    ExtractClaims,
    CrossValidate,
    Synthesize,
    TestOrPractice,
    Consolidate,
    TransferProbe,
    ShareOrIncubate,
    Reflect,
    Paused,
    NeedsUserConsent,
    Contradicted,
    Failed,
    Abandoned,
}

public enum QuestEvent
{
    /// <summary>Move to the next pipeline stage.</summary>
    Advance,
    /// <summary>Park the quest (resumable).</summary>
    Pause,
    /// <summary>Return from paused / needs-consent / contradicted.</summary>
    Resume,
    /// <summary>Pause pending user consent.</summary>
    NeedConsent,
    /// <summary>Consent granted → resume.</summary>
    GrantConsent,
    /// <summary>A contradiction was found (resumable after resolution).</summary>
    Contradict,
    /// <summary>Unrecoverable failure (terminal).</summary>
    Fail,
    /// <summary>Deliberately dropped (terminal).</summary>
    Abandon,
}

/// <summary>The current stage plus the pipeline stage to return to after an exceptional state.</summary>
public sealed record QuestState(QuestStage Stage, QuestStage? ResumePoint = null);

public sealed record EvidenceQualities(double Reliability, double Independence, double Directness, double Recency, double Reproducibility, double CounterEvidence);

public sealed record ConfidenceWeights(
    double Reliability = 0.3, double Independence = 0.2, double Directness = 0.15, double Recency = 0.1, double Reproducibility = 0.15, double CounterEvidence = 0.2)
{
    public static ConfidenceWeights Default { get; } = new();
}

public enum QuestionType
{
    TimelyFact,
    Academic,
    Technical,
    Everyday,
    SubjectiveCulture,
}

/// <summary>§48.3 source plan: which source types to consult, whether to cross-validate, whether to keep multiple perspectives.</summary>
public sealed record QuestSourcePlan(QuestionType QuestionType, IReadOnlyList<string> SourceTypes, bool CrossValidate, bool PreservePerspectives);

public enum ContentOrigin
{
    System,
    User,
    Web,
    Model,
    Tool,
}

public static class Ael
{
    public const int PipelineLength = 14;

    public static bool IsPipeline(QuestStage s) => (int)s < PipelineLength;

    private static bool IsTerminal(QuestStage s) => s is QuestStage.Failed or QuestStage.Abandoned;

    private static bool IsResumable(QuestStage s) => s is QuestStage.Paused or QuestStage.NeedsUserConsent or QuestStage.Contradicted;

    /// <summary>
    /// §48.1 quest state machine. Returns null for an illegal event (so it is recorded, not applied). Advancing from
    /// Reflect, the last stage, also returns null: there is no further state, the quest is complete.
    /// </summary>
    public static QuestState? Transition(QuestState state, QuestEvent e)
    {
        if (IsTerminal(state.Stage))
            return null;
        var pipeline = IsPipeline(state.Stage);
        switch (e)
        {
            case QuestEvent.Advance:
                if (!pipeline || state.Stage == QuestStage.Reflect)
                    return null;
                return new QuestState(state.Stage + 1);
            case QuestEvent.Pause:
                return pipeline ? new QuestState(QuestStage.Paused, state.Stage) : null;
            case QuestEvent.NeedConsent:
                return pipeline ? new QuestState(QuestStage.NeedsUserConsent, state.Stage) : null;
            case QuestEvent.Contradict:
                return pipeline ? new QuestState(QuestStage.Contradicted, state.Stage) : null;
            case QuestEvent.Resume:
            case QuestEvent.GrantConsent:
                if (!IsResumable(state.Stage))
                    return null;
                if (e == QuestEvent.GrantConsent && state.Stage != QuestStage.NeedsUserConsent)
                    return null;
                return state.ResumePoint is { } r ? new QuestState(r) : null;
            case QuestEvent.Fail:
                return new QuestState(QuestStage.Failed);
            case QuestEvent.Abandon:
                return new QuestState(QuestStage.Abandoned);
            default:
                return null;
        }
    }

    /// <summary>
    /// The single edge that emits active_learning.requested: leaving ScopeAndBudget for PlanSources. Earlier the quest has
    /// no budget or stop conditions yet (they would have to be invented); one edge means one emission per pipeline pass.
    /// </summary>
    public static (QuestStage From, QuestStage To) ActiveLearningRequestEdge { get; } = (QuestStage.ScopeAndBudget, QuestStage.PlanSources);

    public static bool ShouldRequestActiveLearning(QuestStage from, QuestStage? to) =>
        to is { } t && from == ActiveLearningRequestEdge.From && t == ActiveLearningRequestEdge.To;

    /// <summary>Completion = advancing from Reflect (Transition returns null). Fail and abandon are not completion.</summary>
    public static bool ShouldCompleteActiveLearning(QuestStage from, QuestStage? to) => to is null && from == QuestStage.Reflect;

    /// <summary>
    /// Wrap a scoped quest as aijade.active_learning.requested. A quest violating §48.2 (no stop conditions, spent &gt; allocated,
    /// no experiment manifest) throws instead of emitting an unauditable request. The session id is explicit: a quest has
    /// an agent and a user scope but no session, and the two have different lifetimes.
    /// </summary>
    public static JsonObject BuildActiveLearningRequestedEvent(LearningQuest quest, string sessionId, JsonObject envelope)
    {
        var verdict = ContractValidationV8.Validate(quest);
        if (!verdict.Ok)
            throw new ArgumentException($"active_learning.requested 被拒：quest 未满足 v8 §48.2 界定要求 — {verdict.Reason}", nameof(quest));
        var payload = new JsonObject
        {
            ["session_id"] = sessionId,
            ["trace_id"] = envelope["trace_id"]?.DeepClone(),
            ["requested_at"] = envelope["timestamp"]?.DeepClone(),
            ["target"] = quest.ResearchQuestion,
            ["quest_ref"] = quest.Id,
            ["resource_budget"] = new JsonObject
            {
                ["allocated"] = quest.ResourceBudget.Allocated,
                ["spent"] = quest.ResourceBudget.Spent,
                ["unit"] = quest.ResourceBudget.Unit,
            },
            ["stop_conditions"] = new JsonArray(quest.StopConditions.Select(s => (JsonNode?)s).ToArray()),
        };
        return AijadeEvents.Build(AijadeEvents.ActiveLearningRequested, envelope, payload);
    }

    /// <summary>Wrap a completed quest as aijade.active_learning.completed; result_ref only when one exists (no placeholder).</summary>
    public static JsonObject BuildActiveLearningCompletedEvent(LearningQuest quest, string sessionId, JsonObject envelope, string? resultRef = null)
    {
        var payload = new JsonObject
        {
            ["session_id"] = sessionId,
            ["trace_id"] = envelope["trace_id"]?.DeepClone(),
            ["completed_at"] = envelope["timestamp"]?.DeepClone(),
            ["quest_ref"] = quest.Id,
        };
        if (resultRef is not null)
            payload["result_ref"] = resultRef;
        return AijadeEvents.Build(AijadeEvents.ActiveLearningCompleted, envelope, payload);
    }

    private static double Clamp01(double x) => Math.Min(1, Math.Max(0, x));

    /// <summary>§48.5 confidence is not a vote: weighted source qualities minus counter-evidence, clamped to [0, 1].</summary>
    public static double EvidenceConfidence(EvidenceQualities q, ConfidenceWeights? weights = null)
    {
        var w = weights ?? ConfidenceWeights.Default;
        var support = (w.Reliability * Clamp01(q.Reliability)) + (w.Independence * Clamp01(q.Independence)) + (w.Directness * Clamp01(q.Directness))
            + (w.Recency * Clamp01(q.Recency)) + (w.Reproducibility * Clamp01(q.Reproducibility));
        return Clamp01(support - (w.CounterEvidence * Clamp01(q.CounterEvidence)));
    }

    /// <summary>§48.3 plan sources by question type.</summary>
    public static QuestSourcePlan PlanSources(QuestionType t) => t switch
    {
        QuestionType.TimelyFact => new(t, ["official_announcement", "primary_data", "recent_reliable_report"], true, false),
        QuestionType.Academic => new(t, ["paper", "dataset", "reproduction_code", "citing_works"], true, false),
        QuestionType.Technical => new(t, ["official_doc", "source_code", "issue_tracker", "test_suite", "version_history"], true, false),
        QuestionType.Everyday => new(t, ["multi_source_crosscheck"], true, false),
        QuestionType.SubjectiveCulture => new(t, ["multi_perspective"], false, true),
        _ => throw new ArgumentOutOfRangeException(nameof(t)),
    };

    /// <summary>§48.4 / §14.4 only system-authored content may act as an instruction; web, model and tool text never can.</summary>
    public static bool CanBeSystemInstruction(ContentOrigin origin) => origin == ContentOrigin.System;

    /// <summary>§48.4 a model's own restatement of a claim is never independent evidence for it.</summary>
    public static bool CanBeIndependentEvidence(ContentOrigin origin, bool isModelSummary) =>
        !isModelSummary && origin is ContentOrigin.Web or ContentOrigin.Tool or ContentOrigin.User;

    /// <summary>§48.4 cluster sources sharing an upstream ref or an identical content hash, so reposts count once.</summary>
    public static IReadOnlyList<IReadOnlyList<string>> SharedOriginClusters(IReadOnlyList<SourceRecord> sources)
    {
        var n = sources.Count;
        var parent = Enumerable.Range(0, n).ToArray();
        int Find(int x) => parent[x] == x ? x : parent[x] = Find(parent[x]);
        for (var i = 0; i < n; i++)
        {
            for (var j = i + 1; j < n; j++)
            {
                var a = sources[i];
                var b = sources[j];
                var shared = a.ContentHash == b.ContentHash
                    || a.UpstreamRefs.Any(b.UpstreamRefs.Contains)
                    || a.UpstreamRefs.Contains(b.Id)
                    || b.UpstreamRefs.Contains(a.Id);
                if (shared)
                    parent[Find(i)] = Find(j);
            }
        }
        var clusters = new OrderedDictionary<int, List<string>>();
        for (var i = 0; i < n; i++)
        {
            var root = Find(i);
            if (!clusters.TryGetValue(root, out var list))
                clusters[root] = list = [];
            list.Add(sources[i].Id);
        }
        return [.. clusters.Values];
    }

    /// <summary>§48.4 the number of independent origins (clusters), not of raw sources.</summary>
    public static int IndependentOriginCount(IReadOnlyList<SourceRecord> sources) => SharedOriginClusters(sources).Count;
}
