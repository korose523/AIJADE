using Aijade.Learning.Continuous;

namespace Aijade.Research.Telemetry;

// Records
// every persona update as a telemetry turn, but only while the user consents; withdrawing consent purges what was recorded.

public static class PersonaSnapshots
{
    public static PersonaSnapshot From(PersonaState s)
    {
        var v = s.Vector;
        var e = s.Endocrine;
        var i = s.Intimacy;
        var pad = Persona.ToPad(s);
        var b = Persona.ToBigFive(v);
        var mood = Persona.ToMoodProfile(s);
        return new PersonaSnapshot(
            new PersonaVectorSnapshot(v["openness"], v["warmth"], v["curiosity"], v["patience"], v["formality"], v["playfulness"], v["caution"], v["confidence"],
                v["empathy"], v["spontaneity"], v["diligence"], v["assertiveness"], v["stability"]),
            new EndocrineSnapshot(e["dopamine"], e["serotonin"], e["cortisol"], e["oxytocin"], e["adrenaline"]),
            new PadSnapshot(pad.Pleasure, pad.Arousal, pad.Dominance), new BigFiveSnapshot(b.O, b.C, b.E, b.A, b.N),
            new IntimacySnapshot(i["warmth"], i["trust"], i["dependence"], i["security"], i["familiarity"], i["longing"]), mood.Label, mood.Emoji);
    }
}

/// <summary>
/// Consent-gated persona telemetry. Durable storage is required: without one, recording reports an error instead of
/// silently keeping data in memory. Recording failures never interrupt the conversation; they are surfaced in diagnostics.
/// </summary>
public sealed class PersonaTelemetryRecorder(Func<bool> consent, ITelemetryStorage? storage = null, string condition = "baseline", string? participantId = null,
    string? sessionId = null, Func<double>? now = null, Action<Exception>? onError = null) : IDisposable
{
    private Task<ExperimentSessionRunner>? _session;
    private bool _lastConsent = consent();
    private readonly SemaphoreSlim _gate = new(1, 1);

    public void Dispose() => _gate.Dispose();

    public int TurnsRecorded { get; private set; }

    public string? LastError { get; private set; }

    public bool Recording => _lastConsent;

    private Task<ExperimentSessionRunner> OpenSession() => _session ??= ExperimentSessionRunner.StartAsync(new ExperimentSessionRunner(condition, participantId: participantId,
        storage: storage ?? throw new InvalidOperationException("research telemetry consented but no durable storage is available in this environment"), sessionId: sessionId, now: now));

    private void Fail(Exception e)
    {
        LastError = e.Message;
        onError?.Invoke(e);
    }

    private async Task PurgeAsync()
    {
        var session = _session;
        _session = null;
        TurnsRecorded = 0;
        if (session is null)
            return;
        try
        {
            await (await session.ConfigureAwait(false)).Storage.ClearAsync().ConfigureAwait(false);
        }
#pragma warning disable CA1031 // Telemetry must never break the conversation; the failure is surfaced in diagnostics.
        catch (Exception e)
#pragma warning restore CA1031
        {
            Fail(e);
        }
    }

    /// <summary>Record one persona update (if consented). Returns when the write has completed or failed.</summary>
    public async Task RecordAsync(PersonaUpdateEvent evt)
    {
        ArgumentNullException.ThrowIfNull(evt);
        await _gate.WaitAsync().ConfigureAwait(false);
        try
        {
            var granted = consent();
            if (_lastConsent && !granted)
                await PurgeAsync().ConfigureAwait(false);
            _lastConsent = granted;
            if (!granted)
                return;
            try
            {
                var session = await OpenSession().ConfigureAwait(false);
                await session.RecordTurnAsync(new RecordTurnInput(evt.Role == Aijade.Providers.Llm.ChatRole.Assistant ? TurnRole.Assistant : TurnRole.User)
                {
                    Persona = PersonaSnapshots.From(evt.State),
                }).ConfigureAwait(false);
                TurnsRecorded++;
                LastError = null;
            }
#pragma warning disable CA1031 // Telemetry must never break the conversation; the failure is surfaced in diagnostics.
            catch (Exception e)
#pragma warning restore CA1031
            {
                _session = null;
                Fail(e);
            }
        }
        finally
        {
            _gate.Release();
        }
    }
}
