using System.Text.Json.Nodes;

using Aijade.Core.Js;

using Aijade.Client.Api;
using Aijade.Client.Companion;
using Aijade.Memory.Contracts;
using Aijade.Memory.Kernel;

namespace Aijade.Client.Chat;

/// <summary>
/// Reports what the stage actually rendered to the server's v9 event bus, so the persona → intent → render identity chain is
/// verifiable: a persona.render_requested (snapshot and intent refs) and an lpm.render_ready (render ref, the hash of the
/// parameters the renderer applied, the asset version) on one trace. The applied-params hash is computed here, by the only
/// witness of what was applied, never by the server.
/// </summary>
public sealed class RenderReporter(AijadeApi api, string sessionId, string deviceId, TimeProvider? time = null)
{
    private readonly TimeProvider clock = time ?? TimeProvider.System;

    private JsonObject Envelope(string eventId, string traceId) => new()
    {
        ["event_id"] = eventId, ["trace_id"] = traceId, ["correlation_id"] = traceId, ["timestamp"] = clock.GetUtcNow().ToUnixTimeMilliseconds(),
        ["producer"] = "aijade-stage", ["origin_device"] = deviceId, ["privacy_level"] = 1, ["evidence_refs"] = new JsonArray(),
        ["causal_context_refs"] = new JsonArray(), ["risk_score"] = 0, ["idempotency_key"] = eventId, ["replay_mode"] = "live", ["risk_level"] = "low",
    };

    public static string AppliedParamsHash(JsonObject appliedParams) => JsFormat.Sha256Hex(JsFormat.CanonicalJson(appliedParams));

    /// <returns>The render ref reported.</returns>
    public async Task<string> ReportAsync(PerformanceIntent intent, JsonObject appliedParams, string? assetVersionHash, CancellationToken ct = default)
    {
        if (appliedParams.Count == 0)
            throw new ArgumentException("nothing was applied; no receipt is sent for an empty parameter map", nameof(appliedParams));
        var traceId = $"render-{intent.Id}";
        var renderRef = $"rr_{intent.Id}";
        var request = Envelope($"evt-req-{intent.Id}", traceId);
        request["topic"] = AijadeEvents.PersonaRenderRequested;
        request["payload"] = new JsonObject { ["session_id"] = sessionId, ["persona_snapshot_ref"] = intent.PersonaSnapshotRef, ["intent_ref"] = intent.Id };
        await api.PostEventAsync(request, ct).ConfigureAwait(false);
        var ready = Envelope($"evt-ready-{intent.Id}", traceId);
        ready["topic"] = AijadeEvents.LpmRenderReady;
        var payload = new JsonObject { ["session_id"] = sessionId, ["render_ref"] = renderRef, ["applied_params_hash"] = AppliedParamsHash(appliedParams) };
        if (!string.IsNullOrEmpty(assetVersionHash))
            payload["asset_version_hash"] = assetVersionHash;
        ready["payload"] = payload;
        await api.PostEventAsync(ready, ct).ConfigureAwait(false);
        return renderRef;
    }
}
