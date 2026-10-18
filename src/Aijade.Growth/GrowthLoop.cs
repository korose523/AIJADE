using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Growth.Services;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;
using Aijade.Memory.V9;

namespace Aijade.Growth;

// §46: one autonomous developmental cycle — interest → quest → acquire → verify → synthesise → journal → share — guarded
// by a budget draw, so a scope that has exhausted its quota returns a skipped summary instead of running.

public sealed record RunOnceInput(
    string Subject, IReadOnlyList<string> OriginEventIds, InterestComponents Components, double IdentityRelevance, double UserRelevance,
    double NoveltyFrontier, string ResearchQuestion, string OperationalDefinition, double ExpectedInformationGain, QuestionType QuestionType,
    string Query, IReadOnlyList<string>? SourceTypes = null, ShareUtility? ShareUtility = null);

public sealed record GrowthLoopSummary(
    bool Skipped, int SourceCount, string? Reason = null, string? InterestThreadId = null, string? QuestId = null, string? ClaimMapId = null,
    string? ArtifactId = null, string? JournalId = null, string? ShareCandidateId = null, double? ShareScore = null, string? ShareChannel = null);

public sealed class GrowthLoop
{
    /// <summary>The share utility used when the input gives none: a moderate profile.</summary>
    public static ShareUtility DefaultShareUtility { get; } = new(0.6, 0.5, 0.5, 0.5, 0.3, 0.1, 0.1, 0.1);

    private readonly GrowthPorts ports;
    private readonly InterestService interest;
    private readonly QuestPlanner planner;
    private readonly KnowledgeAcquirer acquirer;
    private readonly EpistemicVerifier verifier;
    private readonly SynthesisWorkbench synthesis;
    private readonly LifeJournal journal;
    private readonly SharingPolicy sharing;

    public GrowthLoop(GrowthPorts ports, string agentId, string userScope)
    {
        this.ports = ports;
        interest = new InterestService(ports, agentId, userScope);
        planner = new QuestPlanner(ports, agentId, userScope);
        acquirer = new KnowledgeAcquirer(ports);
        verifier = new EpistemicVerifier(ports, agentId, userScope);
        synthesis = new SynthesisWorkbench(ports, agentId, userScope);
        journal = new LifeJournal(ports, agentId, userScope);
        sharing = new SharingPolicy(ports, agentId, userScope);
    }

    public async Task<GrowthLoopSummary> RunOnceAsync(RunOnceInput input, CancellationToken cancellationToken = default)
    {
        if (!ports.Scheduler.ConsumeBudget("growth_loop", 1))
            return new GrowthLoopSummary(true, 0, "growth_loop budget exhausted");

        var thread = await interest.CreateThreadAsync(new CreateThreadInput(input.Subject, input.OriginEventIds, input.Components, input.IdentityRelevance,
            input.UserRelevance, input.NoveltyFrontier), cancellationToken).ConfigureAwait(false);
        var quest = await planner.CreateQuestAsync(new CreateQuestInput(thread.Id, input.ResearchQuestion, input.OperationalDefinition,
            input.ExpectedInformationGain, input.QuestionType, ports.IdGen.NewId("exp")), cancellationToken).ConfigureAwait(false);
        var sources = await acquirer.AcquireAsync(new AcquireInput(input.Query, input.SourceTypes, UseLlmBrief: ports.Llm is not null), cancellationToken)
            .ConfigureAwait(false);

        string? claimMapId = null, artifactId = null, beliefId = null;
        if (sources.Count > 0)
        {
            var verified = await verifier.VerifyAsync(new VerifyInput(sources, quest.Id, input.ResearchQuestion), cancellationToken).ConfigureAwait(false);
            claimMapId = verified.ClaimMap.Id;
            beliefId = verified.Belief.Id;
            var artifact = await synthesis.SynthesizeAsync(new SynthesizeInput(quest.Id, "learning_note",
                new JsonObject { ["summary"] = input.ResearchQuestion, ["confidence"] = verified.Confidence }, sources), cancellationToken).ConfigureAwait(false);
            artifactId = artifact.Id;
        }

        string[] claims = claimMapId is null ? [] : [claimMapId];
        string[] artifacts = artifactId is null ? [] : [artifactId];
        var entry = await journal.ComposeAsync(new ComposeInput(
            ActiveInterests: [thread.Id], LearnedClaims: claims, ChangedBeliefs: beliefId is null ? [] : [beliefId], SharePolicy: "shareable",
            EvidenceRefs: [.. claims, .. artifacts]), cancellationToken).ConfigureAwait(false);
        var share = await sharing.ScoreShareAsync(artifactId ?? thread.Id, input.ShareUtility ?? DefaultShareUtility, cancellationToken).ConfigureAwait(false);
        return new GrowthLoopSummary(false, sources.Count, null, thread.Id, quest.Id, claimMapId, artifactId, entry.Id, share.Candidate.Id,
            share.Candidate.Score, share.Candidate.Channel);
    }
}

/// <summary>Perception-envelope fields for admitting a completed loop through the v9 runtime.</summary>
public sealed record GrowthV9Envelope(
    string EventId, string SessionId, string TraceId, string OriginDevice, int PrivacyLevel, double RiskScore, string? CorrelationId = null);

public static class GrowthV9Bridge
{
    /// <summary>
    /// A completed loop is admitted through the same evidence / PGC / MemoryTx gate as perception data, instead of writing a
    /// parallel growth-only memory record. A skipped loop is not admitted.
    /// </summary>
    public static async Task<(GrowthLoopSummary Summary, V9RuntimeResult? Runtime)> RunGrowthThroughV9Async(
        GrowthLoop loop, V9CausalRuntime runtime, RunOnceInput input, GrowthV9Envelope envelope, TimeProvider? time = null,
        CancellationToken cancellationToken = default)
    {
        var summary = await loop.RunOnceAsync(input, cancellationToken).ConfigureAwait(false);
        if (summary.Skipped)
            return (summary, null);
        var content = new JsonObject
        {
            ["subject"] = input.Subject,
            ["researchQuestion"] = input.ResearchQuestion,
            ["sourceCount"] = summary.SourceCount,
        };
        // JSON.stringify drops undefined members, so absent ids are omitted rather than written as null.
        if (summary.ClaimMapId is { } cm)
            content["claimMapId"] = cm;
        if (summary.ArtifactId is { } ka)
            content["artifactId"] = ka;
        if (summary.JournalId is { } lj)
            content["journalId"] = lj;
        var risk = envelope.RiskScore >= 0.7 ? "high" : envelope.RiskScore >= 0.35 ? "medium" : "low";
        var result = await runtime.ProcessPerceptionAsync(new V9PerceptionInput(
            envelope.EventId, envelope.SessionId, envelope.TraceId, envelope.CorrelationId ?? envelope.TraceId,
            (time ?? TimeProvider.System).GetUtcNow().ToUnixTimeMilliseconds(), envelope.OriginDevice, envelope.PrivacyLevel, envelope.RiskScore,
            "growth-loop", JsFormat.Stringify(content), RiskLevel: risk), cancellationToken).ConfigureAwait(false);
        return (summary, result);
    }
}
