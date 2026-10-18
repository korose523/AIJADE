using Aijade.Memory.Contracts;

namespace Aijade.Growth.Services;

// §50.3: a day's interests, quests, claims, beliefs, skills, open questions and identity reflections aggregated into a
// privacy-filtered LifeJournalEntry with an ISO date, a share policy and evidence references.

public sealed record ComposeInput(
    string? Date = null, IReadOnlyList<string>? ExperiencedEvents = null, IReadOnlyList<string>? ActiveInterests = null,
    IReadOnlyList<string>? LearnedClaims = null, IReadOnlyList<string>? ChangedBeliefs = null, IReadOnlyList<string>? PracticedSkills = null,
    IReadOnlyList<string>? UnresolvedQuestions = null, IReadOnlyList<string>? IdentityReflections = null, string? SharePolicy = null,
    IReadOnlyList<string>? EvidenceRefs = null);

public sealed class LifeJournal(GrowthPorts ports, string agentId, string userScope)
{
    public const string Kind = "life_journal_entry";

    public async Task<LifeJournalEntry> ComposeAsync(ComposeInput input, CancellationToken cancellationToken = default)
    {
        var entry = new LifeJournalEntry(ports.IdGen.NewId("lj"), agentId, userScope, input.Date ?? GrowthUtil.TodayIso(ports.Scheduler.Now(), ports.Zone),
            input.ExperiencedEvents ?? [], input.ActiveInterests ?? [], input.LearnedClaims ?? [], input.ChangedBeliefs ?? [], input.PracticedSkills ?? [],
            input.UnresolvedQuestions ?? [], input.IdentityReflections ?? [], input.SharePolicy ?? "private", input.EvidenceRefs ?? [],
            ports.Scheduler.Now());
        var check = ContractValidationV8.Validate(entry);
        if (!check.Ok)
            throw new InvalidOperationException($"LifeJournalEntry rejected: {check.Reason}");
        await ports.Storage.PutAsync(Kind, entry.Id, entry, cancellationToken).ConfigureAwait(false);
        return entry;
    }

    public Task<LifeJournalEntry?> GetAsync(string id, CancellationToken cancellationToken = default) =>
        ports.Storage.GetAsync<LifeJournalEntry>(Kind, id, cancellationToken);
}
