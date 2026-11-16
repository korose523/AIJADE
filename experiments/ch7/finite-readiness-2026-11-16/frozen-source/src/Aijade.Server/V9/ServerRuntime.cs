using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Memory.V9;
using Aijade.Server.Infrastructure;
using Aijade.Server.Memory;

namespace Aijade.Server.V9;

// The kernel runtime, the job queue and the background worker that drains the perception, video-observation, memory and
// promotion queues. A failed job is logged and parked in its dead-letter list, never silently dropped.

public sealed class ServerRuntime(V9CausalRuntime runtime, IJobBroker queue, V9EventService events, ILogger<ServerRuntime> logger, bool queueIsDurable, bool dispatchObservations = true)
{
    public V9CausalRuntime Runtime { get; } = runtime;

    public IJobBroker Queue { get; } = queue;

    /// <summary>True with Redis: work is handed to a worker process; otherwise it is processed inline.</summary>
    public bool QueueIsDurable { get; } = queueIsDurable;

    /// <summary>Whether stored video observations are dispatched to the learning runtime (Aijade:DispatchObservations, default true).</summary>
    public bool DispatchObservations { get; } = dispatchObservations;

    /// <summary>
    /// Observation → learning proposal. The proposal's render identity must be a real receipt from the projection; with none,
    /// dispatch is skipped (better absent than forged) — dispatching would only be refused by the kernel guard anyway. The
    /// proposal id derives from the event id (sp_prop_{eventId}), so replaying an event yields the same proposal.
    /// </summary>
    public async Task DispatchVideoObservationAsync(V9EventInput e, CancellationToken ct)
    {
        if (!DispatchObservations)
            return;
        var identity = await events.FindLatestRenderIdentityAsync(ct).ConfigureAwait(false);
        var sessionId = e.Payload["session_id"]!.GetValue<string>();
        if (identity is null)
        {
            logger.LogWarning("video observation {EventId}: no real render identity available (session {Session}); learning proposal dispatch skipped", e.EventId, sessionId);
            return;
        }
        var evt = new JsonObject
        {
            ["event_id"] = e.EventId, ["trace_id"] = e.TraceId, ["correlation_id"] = e.CorrelationId, ["timestamp"] = e.Timestamp, ["producer"] = e.Producer,
            ["origin_device"] = e.OriginDevice, ["privacy_level"] = e.PrivacyLevel,
            ["evidence_refs"] = new JsonArray([.. e.EvidenceRefs.Select(x => (JsonNode)x)]),
            ["causal_context_refs"] = new JsonArray([.. e.CausalContextRefs.Select(x => (JsonNode)x)]),
            ["risk_score"] = e.RiskScore, ["idempotency_key"] = e.IdempotencyKey, ["replay_mode"] = e.ReplayMode, ["risk_level"] = e.RiskLevel,
            ["tick"] = e.Tick, ["causality"] = new JsonObject { ["inputHash"] = e.InputHash }, ["topic"] = e.Topic, ["payload"] = e.Payload.DeepClone(),
        };
        var input = new V9VideoObservationInput(e.EventId, sessionId, e.TraceId, e.CorrelationId, e.Timestamp, e.OriginDevice, e.PrivacyLevel, e.RiskScore,
            e.Tick!.Value, e.InputHash!, $"sp_prop_{e.EventId}", evt, identity.RenderRef, identity.AppliedParamsHash, identity.AssetVersionHash);
        try
        {
            if (QueueIsDurable)
                await Queue.EnqueueAsync(Queues.VideoObservation, new JsonObject { ["jobId"] = Ids.New(), ["input"] = JsonSerializer.SerializeToNode(input, JsonSerializerOptions.Web) }, ct).ConfigureAwait(false);
            else
                await Runtime.ProcessVideoObservationAsync(input, ct).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            logger.LogError(ex, "video observation dispatch failed for {EventId} (event accepted, not rolled back)", e.EventId);
            if (QueueIsDurable)
                await Queue.ParkDeadLetterAsync(Queues.VideoObservationDeadLetter, new JsonObject { ["eventId"] = e.EventId, ["topic"] = e.Topic }, ex.ToString(), ct).ConfigureAwait(false);
        }
    }
}

/// <summary>Drains the four queues; enabled in the worker role (or alongside the API).</summary>
public sealed class V9Worker(ServerRuntime server, LongTermMemoryService memory, PromotionService promotion, ILogger<V9Worker> logger) : BackgroundService
{
    /// <summary>Process at most one job per queue; true when any job was taken.</summary>
    public async Task<bool> DrainOnceAsync(CancellationToken ct)
    {
        var any = false;
        var q = server.Queue;
        if (await q.TryDequeueAsync(Queues.Perception, ct).ConfigureAwait(false) is { } p)
        {
            any = true;
            await RunAsync(p, Queues.PerceptionDeadLetter, async job =>
                await server.Runtime.ProcessPerceptionAsync(job["input"].Deserialize<V9PerceptionInput>(JsonSerializerOptions.Web)!, ct).ConfigureAwait(false), ct).ConfigureAwait(false);
        }
        if (await q.TryDequeueAsync(Queues.VideoObservation, ct).ConfigureAwait(false) is { } v)
        {
            any = true;
            await RunAsync(v, Queues.VideoObservationDeadLetter, async job =>
                await server.Runtime.ProcessVideoObservationAsync(job["input"].Deserialize<V9VideoObservationInput>(JsonSerializerOptions.Web)!, ct).ConfigureAwait(false), ct).ConfigureAwait(false);
        }
        if (await q.TryDequeueAsync(Queues.Memory, ct).ConfigureAwait(false) is { } m)
        {
            any = true;
            await RunAsync(m, Queues.MemoryDeadLetter, async job =>
            {
                if (job["kind"]?.GetValue<string>() == "sync")
                    await memory.ProcessSyncAsync(job["outboxId"]!.GetValue<string>(), ct).ConfigureAwait(false);
                else
                    await memory.ProcessShareAsync(job["notificationId"]!.GetValue<string>(), ct).ConfigureAwait(false);
            }, ct).ConfigureAwait(false);
        }
        if (await q.TryDequeueAsync(Queues.Promotion, ct).ConfigureAwait(false) is { } pr)
        {
            any = true;
            await RunAsync(pr, Queues.PromotionDeadLetter, async job =>
            {
                var result = await promotion.ProcessAsync(PromotionService.ParseJob(job), ct).ConfigureAwait(false);
                if (!result.Ok)
                    logger.LogWarning("promotion job {JobId} refused at {Stage}: {Reason}", job["jobId"], result.Stage, result.Reason);
            }, ct).ConfigureAwait(false);
        }
        return any;
    }

    private async Task RunAsync(JsonNode job, string deadLetter, Func<JsonNode, Task> work, CancellationToken ct)
    {
        try
        {
            await work(job).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            logger.LogError(ex, "job failed; parked in {DeadLetter}", deadLetter);
            await server.Queue.ParkDeadLetterAsync(deadLetter, job, ex.ToString(), ct).ConfigureAwait(false);
        }
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                if (!await DrainOnceAsync(stoppingToken).ConfigureAwait(false))
                    await Task.Delay(100, stoppingToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "worker loop error");
                await Task.Delay(1000, stoppingToken).ConfigureAwait(false);
            }
        }
    }
}
