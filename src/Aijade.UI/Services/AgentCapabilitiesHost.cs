using Aijade.Client.Agent;
using Aijade.Client.Api;
using Aijade.Client.Settings;
using Aijade.Research.Telemetry;

namespace Aijade.UI.Services;

/// <summary>
/// Learning state lives for the app session but belongs to one account: signing in as someone else starts afresh, so one
/// user's discourse, persona and skills never reach another user's prompts on a shared device.
/// </summary>
public sealed class AgentCapabilitiesHost(AijadeApi api, SettingsService settings, BrowserTelemetryStorage telemetry) : IDisposable
{
    private readonly object gate = new();
    private (string AccountId, AgentCapabilities Bridge)? current;
    private PersonaTelemetryRecorder? recorder;

    /// <summary>The current account's recorder (turns recorded, last error), if a chat has started.</summary>
    public PersonaTelemetryRecorder? Recorder
    {
        get
        {
            lock (gate)
                return recorder;
        }
    }

    public AgentCapabilities For(string accountId)
    {
        lock (gate)
        {
            if (current is { } c && c.AccountId == accountId)
                return c.Bridge;
            // Persona updates go to research telemetry only with the user's consent; withdrawing it purges what was kept.
            recorder?.Dispose();
            recorder = new PersonaTelemetryRecorder(() => settings.Current.ResearchConsent, telemetry);
            var record = recorder;
            var bridge = new AgentCapabilities(new GatewayChatClient(api, () => settings.Current.Model),
                new AgentCapabilitiesOptions { Enabled = () => settings.Current.Modules.Learning, OnPersonaUpdate = e => _ = record.RecordAsync(e) });
            current = (accountId, bridge);
            return bridge;
        }
    }

    public void Dispose()
    {
        lock (gate)
            recorder?.Dispose();
    }
}
