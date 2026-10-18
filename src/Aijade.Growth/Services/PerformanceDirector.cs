using Aijade.Memory.Contracts;
using Aijade.Memory.Development;

namespace Aijade.Growth.Services;

// §52 PEF: a persona snapshot becomes a time-marked stream of incremental PerformanceIntents, full-duplex events are
// scheduled, and renderer observations are checked for identity consistency; a failure degrades the whole stream to a
// controllable avatar or pure voice (voice wins when both kinds fail).

/// <param name="PersonaSnapshotRef">The persona / identity snapshot expressed.</param>
/// <param name="Persona">Persona-stack input.</param>
/// <param name="Observations">Renderer consistency observations.</param>
/// <param name="StepCount">Intent steps to emit (at least 1; default 1).</param>
/// <param name="Duration">Per-intent duration in ms (default 200).</param>
/// <param name="DuplexEvents">Full-duplex events to schedule.</param>
public sealed record DirectInput(
    string PersonaSnapshotRef, PersonaInput Persona, IReadOnlyList<ConsistencyObservation>? Observations = null, int? StepCount = null,
    double? Duration = null, IReadOnlyList<DuplexEvent>? DuplexEvents = null);

public sealed record IntentStep(PerformanceIntent Intent, DegradeMode DegradeMode);

public sealed record DirectResult(IReadOnlyList<IntentStep> Steps, IReadOnlyList<ConsistencyVerdict> Verdicts, IReadOnlyList<DuplexDecision> DuplexDecisions);

public sealed class PerformanceDirector(GrowthPorts ports, string agentId, string userScope)
{
    public const string Kind = "performance_intent";

    public async Task<DirectResult> DirectAsync(DirectInput input, CancellationToken cancellationToken = default)
    {
        var now = ports.Scheduler.Now();
        var observations = input.Observations ?? [];
        var stepCount = Math.Max(1, input.StepCount ?? 1);
        var duration = input.Duration ?? 200;
        var steps = new List<IntentStep>();
        for (var i = 0; i < stepCount; i++)
        {
            var intent = Pef.BuildPerformanceIntent(input.Persona, new PerformanceIds(ports.IdGen.NewId("pi"), agentId, userScope, input.PersonaSnapshotRef),
                now + (i * duration), duration);
            var check = ContractValidationV8.Validate(intent);
            if (!check.Ok)
                throw new InvalidOperationException($"PerformanceIntent rejected: {check.Reason}");
            var degrade = observations.Any(o => !Pef.IdentityConsistencyCheck(o).Ok) ? WorstDegrade(observations) : DegradeMode.None;
            steps.Add(new IntentStep(intent, degrade));
            await ports.Storage.PutAsync(Kind, intent.Id, intent, cancellationToken).ConfigureAwait(false);
        }
        var verdicts = observations.Select(o => Pef.IdentityConsistencyCheck(o)).ToList();
        var duplex = (input.DuplexEvents ?? []).Select(Pef.ScheduleDuplex).ToList();
        return new DirectResult(steps, verdicts, duplex);
    }

    private static DegradeMode WorstDegrade(IReadOnlyList<ConsistencyObservation> observations)
    {
        bool voice = false, avatar = false;
        foreach (var v in observations.Select(o => Pef.IdentityConsistencyCheck(o)).Where(v => !v.Ok))
        {
            if (v.Degrade == DegradeMode.Voice)
                voice = true;
            else
                avatar = true;
        }
        return voice ? DegradeMode.Voice : avatar ? DegradeMode.Avatar : DegradeMode.None;
    }
}
