using Aijade.Memory.Contracts;
using Aijade.Memory.Development;

namespace Aijade.Growth.Services;

// §47 DIVE: interest components become a persisted InterestThread, advanced through its lifecycle, and a daily
// attention-budget portfolio is selected from the live threads.

public sealed record CreateThreadInput(
    string Subject, IReadOnlyList<string> OriginEventIds, InterestComponents Components, double IdentityRelevance, double UserRelevance,
    double NoveltyFrontier, IReadOnlyList<string>? MotivatingQuestions = null, IReadOnlyList<string>? KnowledgeGaps = null,
    IReadOnlyList<string>? CurrentHypotheses = null, double? Progress = null, Budget? AttentionBudget = null);

public sealed class InterestService(GrowthPorts ports, string agentId, string userScope)
{
    public const string Kind = "interest_thread";

    private static InterestThread Checked(InterestThread t)
    {
        var check = ContractValidationV8.Validate(t);
        return check.Ok ? t : throw new InvalidOperationException($"InterestThread rejected: {check.Reason}");
    }

    /// <summary>Create and persist a new latent thread from its components.</summary>
    public async Task<InterestThread> CreateThreadAsync(CreateThreadInput input, CancellationToken cancellationToken = default)
    {
        var now = ports.Scheduler.Now();
        var thread = Checked(new InterestThread(
            ports.IdGen.NewId("it"), agentId, userScope, input.Subject, input.OriginEventIds, input.MotivatingQuestions ?? [],
            Dive.IntrinsicValue(input.Components, InterestWeights.Default), input.IdentityRelevance, input.UserRelevance, input.NoveltyFrontier,
            input.KnowledgeGaps ?? [], input.CurrentHypotheses ?? [], input.Progress ?? 0, input.AttentionBudget ?? new Budget(60, 0, "minutes"),
            "latent", now));
        await ports.Storage.PutAsync(Kind, thread.Id, thread, cancellationToken).ConfigureAwait(false);
        return thread;
    }

    /// <summary>Advance a thread's lifecycle; null when absent or the transition is illegal.</summary>
    public async Task<InterestThread?> AdvanceAsync(string id, InterestSignal signal, CancellationToken cancellationToken = default)
    {
        var thread = await ports.Storage.GetAsync<InterestThread>(Kind, id, cancellationToken).ConfigureAwait(false);
        if (thread is null)
            return null;
        var next = Dive.NextStatus(thread.Status, signal);
        if (next is null)
            return null;
        var updated = Checked(thread with
        {
            Status = next,
            LastReflectedAt = ports.Scheduler.Now(),
            AbandonedReason = next == "abandoned" ? thread.AbandonedReason ?? "advanced to abandoned" : thread.AbandonedReason,
        });
        await ports.Storage.PutAsync(Kind, updated.Id, updated, cancellationToken).ConfigureAwait(false);
        return updated;
    }

    /// <summary>Select the active portfolio for this scope under a daily attention budget.</summary>
    public async Task<PortfolioSelection> SelectActiveAsync(int budget, PortfolioOptions? options = null, CancellationToken cancellationToken = default)
    {
        var threads = await ports.Storage.QueryAsync<InterestThread>(Kind, t => t.UserScope == userScope && t.Status != "abandoned", cancellationToken)
            .ConfigureAwait(false);
        var candidates = threads.Select(t => new PortfolioCandidate(t.Id, t.Subject, t.IntrinsicValue, t.IdentityRelevance, t.UserRelevance)).ToList();
        return Dive.SelectPortfolio(candidates, (options ?? new PortfolioOptions(budget)) with { Budget = budget });
    }

    public Task<InterestThread?> GetAsync(string id, CancellationToken cancellationToken = default) =>
        ports.Storage.GetAsync<InterestThread>(Kind, id, cancellationToken);

    public Task<IReadOnlyList<InterestThread>> ListAsync(CancellationToken cancellationToken = default) =>
        ports.Storage.QueryAsync<InterestThread>(Kind, t => t.UserScope == userScope, cancellationToken);
}
