using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Chat;
using Aijade.Memory.Kernel;

namespace Aijade.Integrations.Renderer;

// P1-C (experiments/plans/2026-11-06-p1-c-external-renderer.md): receipts from the renderer's evidence file reach the event bus
// in stages. An intent is registered before it is sent; the session ends and the renderer closes its file; a sealed manifest
// is checked against the file and the registry; only then are receipts imported. Identity comes from the registry, never from
// the latest receipt, and the renderer's hash and this system's hash are each recomputed by their own rule, never compared.

/// <summary>Why a file or a row produced no receipt. The names are the study's reason codes.</summary>
public static class RenderSealReason
{
    public const string ManifestNotComplete = "manifest_not_complete", ManifestCountMismatch = "manifest_count_mismatch", FileDigestMismatch = "file_digest_mismatch",
        NotSchemaV2 = "not_schema_v2", SessionMismatch = "session_mismatch", RendererContextMismatch = "renderer_context_mismatch",
        EndRecordMissing = "end_record_missing", EndCountMismatch = "end_count_mismatch", EndDigestMismatch = "end_digest_mismatch", EndStateUnfinished = "end_state_unfinished",
        TraceNotRegistered = "trace_not_registered", RendererHashMismatch = "renderer_hash_mismatch", NoRow = "no_row", TwoIntentsInRow = "two_intents_in_row",
        NoAppliedValues = "no_applied_values", FileRefused = "file_refused";
}

/// <summary>An intent as registered before it was sent.</summary>
public sealed record RegisteredIntent(string IntentId, string PersonaSnapshotRef, long SentMs);

/// <summary>The registry of one session: its id, the renderer instance it names, and its intents in the order sent.</summary>
public sealed record IntentRegistry(string SessionId, string? RendererContextId, IReadOnlyList<RegisteredIntent> Intents)
{
    /// <summary>Starts a registry file; it must not exist yet.</summary>
    public static void Create(string path, string sessionId, string? rendererContextId) =>
        File.WriteAllText(path, new JsonObject { ["record"] = "session", ["session_id"] = sessionId, ["renderer_context_id"] = rendererContextId }.ToJsonString() + "\n");

    /// <summary>Writes one intent to disk. The caller sends the intent only after this returns.</summary>
    public static void Append(string path, RegisteredIntent intent)
    {
        using var file = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.Read);
        file.Write(Encoding.UTF8.GetBytes(new JsonObject
        {
            ["record"] = "intent", ["intent_id"] = intent.IntentId, ["persona_snapshot_ref"] = intent.PersonaSnapshotRef, ["sent_ms"] = intent.SentMs,
        }.ToJsonString() + "\n"));
        file.Flush(true);
    }

    public static IntentRegistry Read(string path)
    {
        var rows = File.ReadAllLines(path).Where(l => l.Length > 0).Select(l => JsonNode.Parse(l)!.AsObject()).ToList();
        var head = rows.Single(r => r["record"]!.GetValue<string>() == "session");
        return new IntentRegistry(head["session_id"]!.GetValue<string>(), head["renderer_context_id"]?.GetValue<string>(),
            [.. rows.Where(r => r["record"]!.GetValue<string>() == "intent").Select(r =>
                new RegisteredIntent(r["intent_id"]!.GetValue<string>(), r["persona_snapshot_ref"]!.GetValue<string>(), r["sent_ms"]!.GetValue<long>()))]);
    }
}

/// <summary>The renderer's evidence file as read: its lines, its header and end record if any, and its pre-solve rows.</summary>
public sealed class RenderStateFile
{
    public const string SchemaV2 = "mosaic-render-state-log-v2";

    private RenderStateFile(string fileSha256, JsonObject? header, JsonObject? end, string digestBeforeLast, long linesBeforeLast, IReadOnlyList<JsonObject> preSolve, int postSolve)
    {
        FileSha256 = fileSha256;
        Header = header;
        End = end;
        DigestBeforeLast = digestBeforeLast;
        LinesBeforeLast = linesBeforeLast;
        PreSolveRows = preSolve;
        PostSolveRows = postSolve;
    }

    public string FileSha256 { get; }
    public JsonObject? Header { get; }
    public JsonObject? End { get; }
    public string DigestBeforeLast { get; }
    public long LinesBeforeLast { get; }
    public IReadOnlyList<JsonObject> PreSolveRows { get; }
    public int PostSolveRows { get; }

    public static RenderStateFile Read(string path)
    {
        var bytes = File.ReadAllBytes(path);
        var lines = Encoding.UTF8.GetString(bytes).Split('\n').Where(l => l.Length > 0).ToList();
        var rows = lines.Select(l => JsonNode.Parse(l)!.AsObject()).ToList();
        var header = rows.Count > 0 && rows[0]["record"]?.GetValue<string>() == "header" ? rows[0] : null;
        var end = rows.Count > 0 && rows[^1]["record"]?.GetValue<string>() == "end" ? rows[^1] : null;
        using var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        foreach (var line in lines.Take(Math.Max(0, lines.Count - 1)))
            digest.AppendData(Encoding.UTF8.GetBytes(line + "\n"));
        return new RenderStateFile(Convert.ToHexStringLower(SHA256.HashData(bytes)), header, end, Convert.ToHexStringLower(digest.GetHashAndReset()), Math.Max(0, lines.Count - 1),
            [.. rows.Where(r => r["packet_type"]?.GetValue<string>() == AijadeRendererPackets.RenderState)],
            rows.Count(r => r["record"]?.GetValue<string>() == "post_solve_observation"));
    }

    /// <summary>The parameters a row applied, as morph.* and bone.*, the keys the renderer's own hash covers.</summary>
    public static JsonObject AppliedOf(JsonObject row)
    {
        var applied = new JsonObject();
        if (row["expressions_applied"] is JsonObject morphs)
        {
            foreach (var (k, v) in morphs)
                applied[$"morph.{k}"] = v?.DeepClone();
        }
        if (row["avatar_state"]?["bones"] is JsonObject bones)
        {
            foreach (var (k, v) in bones)
                applied[$"bone.{k}"] = v?.DeepClone();
        }
        return applied;
    }
}

/// <summary>What was known about a session when it was sealed. <see cref="Complete"/> is the completion marker.</summary>
public sealed record RenderSessionManifest(string SessionId, string? RendererContextId, string EndState, int ExpectedIntents, int ActualPreSolveRows, string FileSha256, bool Complete)
{
    public const string Closed = "closed", Unfinished = "unfinished";

    /// <summary>Seals a session after its renderer has stopped: the end state is what the file shows, identity is the registry's.</summary>
    public static RenderSessionManifest Seal(IntentRegistry registry, string filePath)
    {
        var file = RenderStateFile.Read(filePath);
        return new RenderSessionManifest(registry.SessionId, registry.RendererContextId, file.End is null ? Unfinished : Closed, registry.Intents.Count, file.PreSolveRows.Count, file.FileSha256, true);
    }

    public string ToJson() => new JsonObject
    {
        ["schema"] = "aijade-render-session-manifest-v1", ["session_id"] = SessionId, ["renderer_context_id"] = RendererContextId, ["end_state"] = EndState,
        ["expected_intents"] = ExpectedIntents, ["actual_pre_solve_rows"] = ActualPreSolveRows, ["file_sha256"] = FileSha256, ["complete"] = Complete,
    }.ToJsonString();

    public static RenderSessionManifest Parse(string json)
    {
        var m = JsonNode.Parse(json)!.AsObject();
        return new RenderSessionManifest(m["session_id"]!.GetValue<string>(), m["renderer_context_id"]?.GetValue<string>(), m["end_state"]!.GetValue<string>(),
            m["expected_intents"]!.GetValue<int>(), m["actual_pre_solve_rows"]!.GetValue<int>(), m["file_sha256"]!.GetValue<string>(), m["complete"]?.GetValue<bool>() == true);
    }
}

/// <summary>The sealing check: every file-level reason found. An empty list means the file may be imported.</summary>
public static class RenderSeal
{
    public static IReadOnlyList<string> Check(RenderSessionManifest manifest, IntentRegistry registry, RenderStateFile file)
    {
        var reasons = new List<string>();
        if (!manifest.Complete)
            reasons.Add(RenderSealReason.ManifestNotComplete);
        if (!string.Equals(manifest.FileSha256, file.FileSha256, StringComparison.Ordinal))
            reasons.Add(RenderSealReason.FileDigestMismatch);
        if (file.Header?["schema"]?.GetValue<string>() != RenderStateFile.SchemaV2)
        {
            reasons.Add(RenderSealReason.NotSchemaV2);
            return reasons;
        }
        var headerSession = file.Header["session_id"]?.GetValue<string>();
        if (headerSession != manifest.SessionId || manifest.SessionId != registry.SessionId)
            reasons.Add(RenderSealReason.SessionMismatch);
        var headerContext = file.Header["renderer_context_id"]?.GetValue<string>();
        if (headerContext is null || headerContext != manifest.RendererContextId || manifest.RendererContextId != registry.RendererContextId)
            reasons.Add(RenderSealReason.RendererContextMismatch);
        if (file.End is not { } end || end["complete"]?.GetValue<bool>() != true)
        {
            reasons.Add(RenderSealReason.EndRecordMissing);
        }
        else
        {
            if (end["lines"]?.GetValue<long>() != file.LinesBeforeLast)
                reasons.Add(RenderSealReason.EndCountMismatch);
            if (end["sha256"]?.GetValue<string>() != file.DigestBeforeLast)
                reasons.Add(RenderSealReason.EndDigestMismatch);
        }
        if (manifest.EndState != RenderSessionManifest.Closed)
            reasons.Add(RenderSealReason.EndStateUnfinished);
        if (manifest.ExpectedIntents != registry.Intents.Count || manifest.ActualPreSolveRows != file.PreSolveRows.Count)
            reasons.Add(RenderSealReason.ManifestCountMismatch);
        return reasons;
    }
}

/// <summary>One intent's two events, in the order they are posted.</summary>
public sealed record ReceiptEvents(string IntentId, string RenderRef, string AppliedParamsHash, string AssetVersionHash, JsonObject Request, JsonObject Receipt);

/// <summary>What a sealed file gives: the events to post, the rows refused and the intents left unknown, each with its reason.</summary>
public sealed record ReceiptImportPlan(
    IReadOnlyList<string> FileReasons, IReadOnlyList<ReceiptEvents> Receipts, IReadOnlyList<(long Seq, string Reason)> RefusedRows, IReadOnlyList<(string IntentId, string Reason)> Unknown);

/// <summary>Maps the rows of a sealed file to receipt events and posts them through the same HTTP boundary as every other event.</summary>
public static class RenderReceiptImporter
{
    public static ReceiptImportPlan Plan(RenderSessionManifest manifest, IntentRegistry registry, RenderStateFile file)
    {
        var fileReasons = RenderSeal.Check(manifest, registry, file);
        if (fileReasons.Count > 0)
            return new ReceiptImportPlan(fileReasons, [], [], [.. registry.Intents.Select(i => (i.IntentId, RenderSealReason.FileRefused))]);

        var registered = registry.Intents.ToDictionary(i => i.IntentId, StringComparer.Ordinal);
        var context = file.Header!["renderer_context_id"]!.GetValue<string>();
        var asset = file.Header["pmx_sha256"]?.GetValue<string>() ?? "";
        var refused = new List<(long, string)>();
        var failed = new Dictionary<string, string>(StringComparer.Ordinal);
        var receipts = new Dictionary<string, ReceiptEvents>(StringComparer.Ordinal);
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var row in file.PreSolveRows)
        {
            var seq = row["seq"]?.GetValue<long>() ?? -1;
            var traces = (row["consumed"]?.AsArray() ?? []).Select(c => c?["trace_id"]?.GetValue<string>()).Where(t => !string.IsNullOrEmpty(t)).Select(t => t!).Distinct(StringComparer.Ordinal).ToList();
            var known = traces.Where(registered.ContainsKey).ToList();
            if (traces.Count > known.Count)
                refused.Add((seq, RenderSealReason.TraceNotRegistered));
            if (known.Count > 1)
            {
                refused.Add((seq, RenderSealReason.TwoIntentsInRow));
                foreach (var id in known)
                {
                    failed[id] = RenderSealReason.TwoIntentsInRow;
                    seen.Add(id);
                    receipts.Remove(id);
                }
                continue;
            }
            if (known.Count == 0 || !seen.Add(known[0]))
                continue;
            var intent = registered[known[0]];
            var applied = RenderStateFile.AppliedOf(row);
            if (applied.Count == 0)
            {
                failed[intent.IntentId] = RenderSealReason.NoAppliedValues;
                continue;
            }
            if (RenderStateReceipts.RendererHash(applied) != row["applied_params_hash"]?.GetValue<string>())
            {
                refused.Add((seq, RenderSealReason.RendererHashMismatch));
                failed[intent.IntentId] = RenderSealReason.RendererHashMismatch;
                continue;
            }
            receipts[intent.IntentId] = Events(registry.SessionId, intent, $"{context}:{seq}", RenderReporter.AppliedParamsHash(applied), asset);
        }
        var unknown = registry.Intents.Where(i => !receipts.ContainsKey(i.IntentId))
            .Select(i => (i.IntentId, failed.TryGetValue(i.IntentId, out var reason) ? reason : RenderSealReason.NoRow)).ToList();
        return new ReceiptImportPlan([], [.. registry.Intents.Where(i => receipts.ContainsKey(i.IntentId)).Select(i => receipts[i.IntentId])], refused, unknown);
    }

    /// <summary>Posts request then receipt for each intent through <paramref name="post"/>, which returns the HTTP status; anything but a 2xx stops the import with an exception. Idempotency keys come from the render reference, so running it again writes nothing new.</summary>
    public static async Task ImportAsync(ReceiptImportPlan plan, Func<JsonObject, Task<int>> post)
    {
        ArgumentNullException.ThrowIfNull(plan);
        ArgumentNullException.ThrowIfNull(post);
        foreach (var r in plan.Receipts)
        {
            foreach (var e in new[] { r.Request, r.Receipt })
            {
                var status = await post((JsonObject)e.DeepClone()).ConfigureAwait(false);
                if (status is < 200 or >= 300)
                    throw new InvalidOperationException($"{e["event_id"]}: status {status}");
            }
        }
    }

    private static ReceiptEvents Events(string sessionId, RegisteredIntent intent, string renderRef, string appliedHash, string asset)
    {
        var trace = $"render-{intent.IntentId}";
        JsonObject Envelope(string kind, string topic, JsonObject payload) => new()
        {
            ["event_id"] = $"evt-{kind}-{renderRef}", ["trace_id"] = trace, ["correlation_id"] = trace, ["timestamp"] = intent.SentMs,
            ["producer"] = "renderer-importer", ["origin_device"] = "renderer-client", ["privacy_level"] = 1, ["evidence_refs"] = new JsonArray(),
            ["causal_context_refs"] = new JsonArray(), ["risk_score"] = 0, ["idempotency_key"] = $"idem-{kind}-{renderRef}", ["replay_mode"] = "live", ["risk_level"] = "low",
            ["topic"] = topic, ["payload"] = payload,
        };
        var receipt = new JsonObject { ["session_id"] = sessionId, ["render_ref"] = renderRef, ["applied_params_hash"] = appliedHash };
        if (asset.Length > 0)
            receipt["asset_version_hash"] = asset;
        return new ReceiptEvents(intent.IntentId, renderRef, appliedHash, asset,
            Envelope("req", AijadeEvents.PersonaRenderRequested, new JsonObject { ["session_id"] = sessionId, ["persona_snapshot_ref"] = intent.PersonaSnapshotRef, ["intent_ref"] = intent.IntentId }),
            Envelope("ready", AijadeEvents.LpmRenderReady, receipt));
    }
}
