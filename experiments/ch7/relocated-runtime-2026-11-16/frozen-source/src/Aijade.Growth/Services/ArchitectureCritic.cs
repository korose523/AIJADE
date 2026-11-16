using Aijade.Core.Js;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;

namespace Aijade.Growth.Services;

// §51 / §48 / §49: scans quests, evolution proposals and transfers for systemic capability gaps — quests failed, abandoned,
// awaiting consent or stuck; transfers with a negative-transfer signal; proposals touching E4 / E5 objects.

public sealed record CapabilityGap(string Severity, string Area, string Description);

public sealed record CriticReport(string Id, string AgentId, string UserScope, IReadOnlyList<CapabilityGap> Gaps, double GeneratedAt);

public sealed class ArchitectureCritic(GrowthPorts ports, string agentId, string userScope)
{
    public const string Kind = "architecture_gap_report";

    public async Task<CriticReport> ScanAsync(
        IReadOnlyList<LearningQuest> quests, IReadOnlyList<EvolutionProposal> proposals, IReadOnlyList<TransferRecord> transfers,
        CancellationToken cancellationToken = default)
    {
        var gaps = new List<CapabilityGap>();
        foreach (var q in quests)
        {
            var stage = QuestPlanner.QuestStatusToStage(q.Status);
            var terminal = stage is not { } s || Ael.Transition(new QuestState(s), QuestEvent.Advance) is null;
            var area = $"quest:{q.ResearchQuestion}";
            if (q.Status == "failed")
                gaps.Add(new("high", area, $"LearningQuest \"{q.ResearchQuestion}\" failed and is terminal (no further AEL transition)."));
            else if (q.Status == "abandoned")
                gaps.Add(new("medium", area, $"LearningQuest \"{q.ResearchQuestion}\" was abandoned."));
            else if (q.Status == "needs_consent")
                gaps.Add(new("medium", area, $"LearningQuest \"{q.ResearchQuestion}\" is blocked awaiting user consent."));
            else if (terminal && q.Status != "satisfied")
                gaps.Add(new("high", area, $"LearningQuest \"{q.ResearchQuestion}\" is in an un-advancable state \"{q.Status}\"."));
        }
        foreach (var t in transfers)
        {
            var area = $"transfer:{t.SourceDomain}->{t.TargetDomain}";
            var signal = JsFormat.Number(t.NegativeTransferSignal);
            if (t.NegativeTransferSignal > 0.5)
                gaps.Add(new("high", area, $"Strong negative transfer ({signal}) from \"{t.SourceDomain}\" to \"{t.TargetDomain}\"."));
            else if (t.NegativeTransferSignal > 0.2)
                gaps.Add(new("medium", area, $"Mild negative transfer ({signal}) from \"{t.SourceDomain}\" to \"{t.TargetDomain}\"."));
        }
        foreach (var p in proposals)
        {
            var evolvable = Enum.TryParse<EvolutionGrade>(p.Grade, out var grade) ? Vse.AssertEvolvable(grade) : Validation.Pass;
            if (!evolvable.Ok)
                gaps.Add(new("high", $"evolution:{p.Grade}", $"Proposal {p.Id} touches {p.Grade}: {evolvable.Reason}"));
        }
        var report = new CriticReport(ports.IdGen.NewId("gap"), agentId, userScope, gaps, ports.Scheduler.Now());
        await ports.Storage.PutAsync(Kind, report.Id, report, cancellationToken).ConfigureAwait(false);
        return report;
    }
}
