using Aijade.Core.Js;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;

namespace Aijade.Growth.Services;

// §48 AEL: bounded LearningQuests (interest ref, question, operational definition, expected gain, source plan, budget,
// privacy class, mandatory stop conditions, success criteria, deliverables, experiment manifest), advanced through the
// AEL state machine.

public sealed record CreateQuestInput(
    string InterestThreadRef, string ResearchQuestion, string OperationalDefinition, double ExpectedInformationGain, QuestionType QuestionType,
    string ExperimentManifestRef, IReadOnlyList<string>? PriorBeliefs = null, Budget? ResourceBudget = null, string? PrivacyClass = null,
    IReadOnlyList<string>? StopConditions = null, IReadOnlyList<string>? SuccessCriteria = null, IReadOnlyList<string>? Deliverables = null);

public sealed class QuestPlanner(GrowthPorts ports, string agentId, string userScope)
{
    public const string Kind = "learning_quest";

    /// <summary>A fine-grained AEL stage onto the coarse quest status; any pipeline stage means "active".</summary>
    public static string ToQuestStatus(QuestStage stage) => stage switch
    {
        QuestStage.Paused => "paused",
        QuestStage.NeedsUserConsent => "needs_consent",
        QuestStage.Contradicted => "contradicted",
        QuestStage.Failed => "failed",
        QuestStage.Abandoned => "abandoned",
        _ => "active",
    };

    /// <summary>The coarse status back onto the AEL stage; satisfied is terminal (null). An unknown status is also null.</summary>
    public static QuestStage? QuestStatusToStage(string status) => status switch
    {
        "active" => QuestStage.Observe,
        "paused" => QuestStage.Paused,
        "needs_consent" => QuestStage.NeedsUserConsent,
        "contradicted" => QuestStage.Contradicted,
        "failed" => QuestStage.Failed,
        "abandoned" => QuestStage.Abandoned,
        _ => null,
    };

    private static LearningQuest Checked(LearningQuest q)
    {
        var check = ContractValidationV8.Validate(q);
        return check.Ok ? q : throw new InvalidOperationException($"LearningQuest rejected: {check.Reason}");
    }

    public async Task<LearningQuest> CreateQuestAsync(CreateQuestInput input, CancellationToken cancellationToken = default)
    {
        var now = ports.Scheduler.Now();
        var plan = Ael.PlanSources(input.QuestionType);
        var quest = Checked(new LearningQuest(
            ports.IdGen.NewId("q"), agentId, userScope, input.InterestThreadRef, input.ResearchQuestion, input.OperationalDefinition,
            input.PriorBeliefs ?? [], input.ExpectedInformationGain, new SourcePlan(WireName.Of(plan.QuestionType), plan.SourceTypes, 8),
            input.ResourceBudget ?? new Budget(50, 0, "queries"), input.PrivacyClass ?? "public",
            input.StopConditions ?? ["marginal information gain below 0.02", "resource budget reached"],
            input.SuccessCriteria ?? ["every motivating question answered", "≥1 claim with support"],
            input.Deliverables ?? ["claim_map", "knowledge_artifact"], input.ExperimentManifestRef, "active", now));
        await ports.Storage.PutAsync(Kind, quest.Id, quest, cancellationToken).ConfigureAwait(false);
        return quest;
    }

    /// <summary>Advance a quest; null when absent, satisfied, or the event is illegal.</summary>
    public async Task<LearningQuest?> TransitionAsync(string id, QuestEvent e, CancellationToken cancellationToken = default)
    {
        var quest = await ports.Storage.GetAsync<LearningQuest>(Kind, id, cancellationToken).ConfigureAwait(false);
        if (quest is null || QuestStatusToStage(quest.Status) is not { } stage)
            return null;
        if (Ael.Transition(new QuestState(stage), e) is not { } result)
            return null;
        var updated = Checked(quest with { Status = ToQuestStatus(result.Stage) });
        await ports.Storage.PutAsync(Kind, updated.Id, updated, cancellationToken).ConfigureAwait(false);
        return updated;
    }

    /// <summary>Mark a quest satisfied (completion after Reflect).</summary>
    public async Task<LearningQuest?> SatisfyAsync(string id, CancellationToken cancellationToken = default)
    {
        var quest = await ports.Storage.GetAsync<LearningQuest>(Kind, id, cancellationToken).ConfigureAwait(false);
        if (quest is null)
            return null;
        var updated = quest with { Status = "satisfied" };
        await ports.Storage.PutAsync(Kind, updated.Id, updated, cancellationToken).ConfigureAwait(false);
        return updated;
    }

    public Task<LearningQuest?> GetAsync(string id, CancellationToken cancellationToken = default) =>
        ports.Storage.GetAsync<LearningQuest>(Kind, id, cancellationToken);
}
