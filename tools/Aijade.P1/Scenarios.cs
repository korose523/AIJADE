using System.Diagnostics;
using System.Globalization;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Core.Js;

using Npgsql;

namespace Aijade.P1;

// The P1 end-to-end checks and the ingest-latency bench, against a running server (HTTP) and its
// database. Row counts are read straight from PostgreSQL.

public sealed record CheckResult(string Name, bool Pass, string Detail);

/// <summary>The server under test: an HTTP client already pointed at the server (base address) and its database.</summary>
public sealed class Target(HttpClient http, NpgsqlDataSource db, string token, string eventsPath = "/api/v1/v9/events")
{
    public NpgsqlDataSource Db => db;

    public async Task<(int Status, JsonNode? Json)> PostAsync(object body, bool withAuth = true, CancellationToken ct = default)
    {
        using var req = new HttpRequestMessage(HttpMethod.Post, eventsPath)
        {
            Content = new StringContent(body is string s ? s : ((JsonNode)body).ToJsonString(), Encoding.UTF8, "application/json"),
        };
        req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", withAuth ? token : "invalid-token");
        using var res = await http.SendAsync(req, ct).ConfigureAwait(false);
        var text = await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        JsonNode? json = null;
        try
        {
            json = JsonNode.Parse(text);
        }
        catch (System.Text.Json.JsonException)
        {
        }
        return ((int)res.StatusCode, json);
    }

    public async Task<string> ScalarAsync(string sql, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await using var cmd = new NpgsqlCommand(sql, conn);
        var v = await cmd.ExecuteScalarAsync(ct).ConfigureAwait(false);
        return v is null or DBNull ? "" : Convert.ToString(v, CultureInfo.InvariantCulture)!;
    }

    public async Task<string> RowAsync(string sql, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await using var cmd = new NpgsqlCommand(sql, conn);
        await using var r = await cmd.ExecuteReaderAsync(ct).ConfigureAwait(false);
        if (!await r.ReadAsync(ct).ConfigureAwait(false))
            return "";
        return string.Join("|", Enumerable.Range(0, r.FieldCount).Select(i => r.IsDBNull(i) ? "" : Convert.ToString(r.GetValue(i), CultureInfo.InvariantCulture)));
    }

    public async Task<long> CountAsync(string sql, CancellationToken ct = default) => long.Parse(await ScalarAsync(sql, ct).ConfigureAwait(false), CultureInfo.InvariantCulture);
}

public static class Scenarios
{
    private static string Rand() => Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(4));

    public static JsonObject Envelope(string topic, JsonObject payload, string? traceId = null, string? eventId = null, JsonObject? extra = null)
    {
        var id = eventId ?? $"evt-{topic}-{Rand()}";
        var e = new JsonObject
        {
            ["event_id"] = id, ["trace_id"] = traceId ?? $"trace-{Rand()}", ["correlation_id"] = $"corr-{Rand()}",
            ["timestamp"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), ["producer"] = "e2e-driver", ["origin_device"] = "e2e-host", ["privacy_level"] = 1,
            ["evidence_refs"] = new JsonArray(), ["causal_context_refs"] = new JsonArray(), ["risk_score"] = 0.1, ["idempotency_key"] = $"idem-{id}",
            ["replay_mode"] = "live", ["risk_level"] = "low", ["topic"] = topic, ["payload"] = payload,
        };
        foreach (var (k, v) in extra ?? [])
            e[k] = v?.DeepClone();
        return e;
    }

    private static async Task<string?> PollAsync(Func<Task<string?>> probe, TimeSpan timeout, TimeSpan step, CancellationToken ct)
    {
        var end = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < end)
        {
            if (await probe().ConfigureAwait(false) is { } v)
                return v;
            await Task.Delay(step, ct).ConfigureAwait(false);
        }
        return null;
    }

    /// <summary>
    /// Main flow: render_requested → render_ready (identity pairing) → idempotent replay → video observation (R1 learning loop)
    /// → opinion_evaluation; then the boundary negatives, each a 4xx with no write to events or render_traces.
    /// </summary>
    public static async Task<IReadOnlyList<CheckResult>> MainFlowAsync(Target t, TimeSpan? pollTimeout = null, CancellationToken ct = default)
    {
        var results = new List<CheckResult>();
        void Record(string name, bool pass, string detail = "") => results.Add(new(name, pass, detail));
        const string session = "e2e-install-001";
        async Task<(long Events, long Traces)> Counts() =>
            (await t.CountAsync("SELECT count(*) FROM events", ct).ConfigureAwait(false), await t.CountAsync("SELECT count(*) FROM render_traces", ct).ConfigureAwait(false));
        var trace = $"trace-e2e-{DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()}-{Rand()}";
        JsonObject Persona(string snap, string intent) => new() { ["session_id"] = session, ["persona_snapshot_ref"] = snap, ["intent_ref"] = intent };

        var r = await t.PostAsync(Envelope("aijade.persona.render_requested", Persona("ps-1", "int-e2e-1")), withAuth: false, ct: ct).ConfigureAwait(false);
        Record("N1 未认证请求被 401 拒绝", r.Status == 401, $"status={r.Status}");

        var p1Body = Envelope("aijade.persona.render_requested", Persona("ps-e2e-1", "intent-e2e-1"), trace);
        r = await t.PostAsync(p1Body, ct: ct).ConfigureAwait(false);
        Record("P1 persona.render_requested → 201 落库", r.Status == 201 && r.Json?["ok"]?.GetValue<bool>() == true, r.Json?.ToJsonString() ?? "");
        var rows = await t.ScalarAsync($"SELECT count(*) FROM render_traces WHERE trace_id='{trace}'", ct).ConfigureAwait(false);
        var status = await t.ScalarAsync($"SELECT projection_status FROM render_traces WHERE trace_id='{trace}'", ct).ConfigureAwait(false);
        Record("P1b 投影行建立且为 partial（intent 端先到）", rows == "1" && status == "partial", $"rows={rows} status={status}");

        r = await t.PostAsync(Envelope("aijade.lpm.render_ready", new JsonObject
        {
            ["session_id"] = session, ["render_ref"] = "render-e2e-1", ["applied_params_hash"] = "hash-e2e-1", ["asset_version_hash"] = "avh-e2e-1",
        }, trace), ct: ct).ConfigureAwait(false);
        Record("P2 lpm.render_ready → 201", r.Status == 201, $"status={r.Status}");
        status = await t.ScalarAsync($"SELECT projection_status FROM render_traces WHERE trace_id='{trace}'", ct).ConfigureAwait(false);
        var refs = await t.RowAsync($"SELECT intent_ref, render_ref, applied_params_hash FROM render_traces WHERE trace_id='{trace}'", ct).ConfigureAwait(false);
        Record("P2b 身份链配对为 paired 且三元组齐备", status == "paired" && refs.Contains("intent-e2e-1", StringComparison.Ordinal) && refs.Contains("render-e2e-1", StringComparison.Ordinal), refs);

        var beforeReplay = (await Counts().ConfigureAwait(false)).Events;
        r = await t.PostAsync(p1Body, ct: ct).ConfigureAwait(false);
        var afterReplay = (await Counts().ConfigureAwait(false)).Events;
        Record("P3 同幂等键重放 → 200 deduped 且事件数不变", r.Status == 200 && r.Json?["deduped"]?.GetValue<bool>() == true && afterReplay == beforeReplay,
            $"status={r.Status} deduped={r.Json?["deduped"]} {beforeReplay}→{afterReplay}");

        // Count before posting and wait for an increase (checking only "> 0" would let a leftover proposal on a reused
        // database satisfy it before the worker has written anything).
        var proposalsBefore = await t.CountAsync("SELECT count(*) FROM events WHERE topic='aijade.learning.proposed.evidence'", ct).ConfigureAwait(false);
        r = await t.PostAsync(Envelope("aijade.video.observation.webpage_text", new JsonObject
        {
            ["session_id"] = session, ["source_url"] = "https://example.com/e2e-article", ["content_hash"] = $"ch-e2e-{Rand()}",
            ["spans"] = new JsonArray(new JsonObject { ["start_offset"] = 0, ["end_offset"] = 42, ["label"] = "paragraph" }),
            ["observation_text"] = "The page claims that spaced repetition improves retention by 40 percent.",
        }, extra: new JsonObject { ["tick"] = 42, ["causality"] = new JsonObject { ["inputHash"] = $"ih-e2e-{Rand()}" } }), ct: ct).ConfigureAwait(false);
        Record("P4 video.observation → 201（tick+causality 合规）", r.Status == 201, $"status={r.Status} eventId={r.Json?["eventId"]}");
        var proposal = await PollAsync(async () =>
        {
            var n = await t.CountAsync("SELECT count(*) FROM events WHERE topic='aijade.learning.proposed.evidence'", ct).ConfigureAwait(false);
            return n > proposalsBefore ? n.ToString(CultureInfo.InvariantCulture) : null;
        }, pollTimeout ?? TimeSpan.FromSeconds(20), TimeSpan.FromMilliseconds(250), ct).ConfigureAwait(false);
        Record("P4b R1 闭环：worker 产出 learning.proposed.evidence（端到端首次真实贯通）", proposal is not null, $"rows={proposal ?? "0"}");
        if (proposal is not null)
        {
            var payload = await t.ScalarAsync($"SELECT payload::text FROM events WHERE topic='aijade.learning.proposed.evidence' AND payload->>'session_id' = '{session}' ORDER BY \"timestamp\" DESC LIMIT 1", ct).ConfigureAwait(false);
            Record("P4c 提案引用真实渲染身份（render_ref=render-e2e-1，非合成）", payload.Contains("render-e2e-1", StringComparison.Ordinal), payload.Length > 160 ? payload[..160] : payload);
        }

        r = await t.PostAsync(Envelope("aijade.learning.constraint.opinion_evaluation", new JsonObject
        {
            ["evaluation_target"] = "https://example.com/e2e-article",
            ["claims"] = new JsonArray(new JsonObject { ["claim_text"] = "Spaced repetition improves retention.", ["confidence"] = 0.72 }),
            ["uncertainty_notes"] = "Sample size of the cited study unknown from the excerpt.",
        }, extra: new JsonObject { ["tick"] = 43, ["causality"] = new JsonObject { ["inputHash"] = $"ih-e2e-{Rand()}" } }), ct: ct).ConfigureAwait(false);
        var opinions = await t.CountAsync("SELECT count(*) FROM events WHERE topic='aijade.learning.constraint.opinion_evaluation'", ct).ConfigureAwait(false);
        Record("P5 opinion_evaluation → 201 且落库（C 路真实投递）", r.Status == 201 && opinions >= 1, $"status={r.Status} rows={opinions}");

        async Task Negative(string name, Func<object> make)
        {
            var before = await Counts().ConfigureAwait(false);
            var res = await t.PostAsync(make(), ct: ct).ConfigureAwait(false);
            var after = await Counts().ConfigureAwait(false);
            var clean = after == before;
            Record(name, res.Status is >= 400 and < 500 && clean, $"status={res.Status} writes={(clean ? "clean" : "DIRTY")}");
        }
        JsonObject Page() => new()
        {
            ["session_id"] = session, ["source_url"] = "https://x.test/a", ["content_hash"] = "c",
            ["spans"] = new JsonArray(new JsonObject { ["start_offset"] = 0, ["end_offset"] = 5 }), ["observation_text"] = "x",
        };
        await Negative("N2 video topic 缺 tick → 400 不落库", () => Envelope("aijade.video.observation.webpage_text", Page())).ConfigureAwait(false);
        await Negative("N3 causality.inputHash 空串 → 400 不落库", () => Envelope("aijade.video.observation.webpage_text", Page(),
            extra: new JsonObject { ["tick"] = 1, ["causality"] = new JsonObject { ["inputHash"] = "" } })).ConfigureAwait(false);
        await Negative("N4 信封未知多余字段（strict）→ 400 不落库", () =>
        {
            var e = Envelope("aijade.persona.render_requested", Persona("p", "i"));
            e["rogue_field"] = "must-be-rejected";
            return e;
        }).ConfigureAwait(false);
        await Negative("N5 未知 topic → 400 不落库", () => Envelope("aijade.unknown.topic.thing", new JsonObject { ["foo"] = "bar" })).ConfigureAwait(false);
        await Negative("N6 render_requested 缺 intent_ref → 400 不落库", () =>
            Envelope("aijade.persona.render_requested", new JsonObject { ["session_id"] = session, ["persona_snapshot_ref"] = "p-only" })).ConfigureAwait(false);
        await Negative("N7 render_ref 自引用信封标识（§11.2）→ 400 不落库", () =>
        {
            var e = Envelope("aijade.lpm.render_ready", new JsonObject { ["session_id"] = session, ["render_ref"] = "SELF", ["applied_params_hash"] = "h" }, $"trace-selfref-{Rand()}");
            e["payload"]!["render_ref"] = e["trace_id"]!.GetValue<string>();
            return e;
        }).ConfigureAwait(false);
        await Negative("N8 同 trace 二次 render_ready 不同 render_ref（append-only）→ 400 不落库", () =>
            Envelope("aijade.lpm.render_ready", new JsonObject { ["session_id"] = session, ["render_ref"] = "render-e2e-CONFLICT", ["applied_params_hash"] = "hash-2" }, trace)).ConfigureAwait(false);
        {
            var before = await Counts().ConfigureAwait(false);
            var res = await t.PostAsync("{ not-json", ct: ct).ConfigureAwait(false);
            var after = await Counts().ConfigureAwait(false);
            Record("N9 畸形 JSON → 400 不落库", res.Status == 400 && after == before, $"status={res.Status}");
        }
        return results;
    }

    /// <summary>
    /// Negative fork ("better absent than forged"), on a database with no render traces: an observation without any real
    /// render identity is accepted but yields no proposal and no forged trace; after a real receipt it yields a proposal
    /// whose render_ref is the projection's, with no dangling reference anywhere.
    /// </summary>
    public static async Task<IReadOnlyList<CheckResult>> NegativeForkAsync(Target t, TimeSpan? settle = null, CancellationToken ct = default)
    {
        var wait = settle ?? TimeSpan.FromSeconds(6);
        var results = new List<CheckResult>();
        void Record(string name, bool pass, string detail = "") => results.Add(new(name, pass, detail));
        const string proposed = "aijade.learning.proposed.evidence";
        var tick = 9000 + RandomNumberGenerator.GetInt32(0, 100_000);
        Task<long> Proposals() => t.CountAsync($"SELECT count(*) FROM events WHERE topic='{proposed}'", ct);
        Task<long> Events() => t.CountAsync("SELECT count(*) FROM events", ct);
        Task<long> Traces() => t.CountAsync("SELECT count(*) FROM render_traces", ct);
        JsonObject Observation(string sessionId) => Envelope("aijade.video.observation.webpage_text", new JsonObject
        {
            ["session_id"] = sessionId, ["source_url"] = "https://example.com/e2e-negfork2", ["content_hash"] = $"ch-{Rand()}",
            ["spans"] = new JsonArray(new JsonObject { ["start_offset"] = 0, ["end_offset"] = 120, ["label"] = "paragraph" }),
            ["observation_text"] = "Spaced repetition improves retention by 40 percent in this sample.",
        }, extra: new JsonObject { ["tick"] = ++tick, ["causality"] = new JsonObject { ["inputHash"] = $"ih-{Rand()}" } });

        var traces0 = await Traces().ConfigureAwait(false);
        Record("P0 前提：起点库内渲染轨迹为 0（真正的\"无渲染身份\"场景）", traces0 == 0, $"render_traces={traces0}");
        if (traces0 != 0)
            return results;

        var beforeP1 = await Proposals().ConfigureAwait(false);
        var eventsBefore = await Events().ConfigureAwait(false);
        var obsB = await t.PostAsync(Observation($"e2e-nf2-b-{Rand()}"), ct: ct).ConfigureAwait(false);
        Record("P1.1 零渲染身份：观察被正常受理（201，不因缺身份而拒绝）", obsB.Status == 201, $"status={obsB.Status}");
        await Task.Delay(wait, ct).ConfigureAwait(false);
        var afterP1 = await Proposals().ConfigureAwait(false);
        var eventsAfter = await Events().ConfigureAwait(false);
        Record("P1.2 零渲染身份：不产出提案（宁缺勿伪造 · 负向分支）", afterP1 == beforeP1, $"proposals {beforeP1} → {afterP1}（期望不变）");
        Record("P1.3 零渲染身份：观察照常落库（跳过派发 ≠ 拒绝受理）", eventsAfter > eventsBefore, $"events {eventsBefore} → {eventsAfter}");
        var tracesAfterP1 = await Traces().ConfigureAwait(false);
        Record("P1.4 零渲染身份：未产生任何伪造渲染轨迹", tracesAfterP1 == 0, $"render_traces={tracesAfterP1}");

        var traceA = $"trace-nf2-a-{Rand()}";
        var sessionA = $"e2e-nf2-a-{Rand()}";
        var r1 = await t.PostAsync(Envelope("aijade.persona.render_requested", new JsonObject
        {
            ["session_id"] = sessionA, ["persona_snapshot_ref"] = "ps-nf2-1", ["intent_ref"] = $"intent-nf2-{Rand()}",
        }, traceA), ct: ct).ConfigureAwait(false);
        var r2 = await t.PostAsync(Envelope("aijade.lpm.render_ready", new JsonObject
        {
            ["session_id"] = sessionA, ["render_ref"] = $"render-nf2-{Rand()}", ["applied_params_hash"] = $"hash-nf2-{Rand()}", ["asset_version_hash"] = "avh-nf2-1",
        }, traceA), ct: ct).ConfigureAwait(false);
        Record("P2.1 补齐：渲染请求/回执 201 配对", r1.Status == 201 && r2.Status == 201, $"req={r1.Status} ready={r2.Status}");
        var beforeP2 = await Proposals().ConfigureAwait(false);
        var obsA = await t.PostAsync(Observation(sessionA), ct: ct).ConfigureAwait(false);
        await Task.Delay(wait, ct).ConfigureAwait(false);
        var afterP2 = await Proposals().ConfigureAwait(false);
        Record("P2.2 有真实回执 ⇒ 产出提案（增量 > 0）", obsA.Status == 201 && afterP2 > beforeP2, $"obs={obsA.Status} proposals {beforeP2} → {afterP2}");

        var projRef = await t.ScalarAsync($"SELECT render_ref FROM render_traces WHERE trace_id='{traceA}' LIMIT 1", ct).ConfigureAwait(false);
        var proposalPayload = await t.ScalarAsync($"SELECT payload::text FROM events WHERE topic='{proposed}' ORDER BY \"timestamp\" DESC LIMIT 1", ct).ConfigureAwait(false);
        Record("P3.1 提案引用与投影真源逐字一致", projRef.Length > 0 && proposalPayload.Contains(projRef, StringComparison.Ordinal),
            $"projection={projRef} | contained={proposalPayload.Contains(projRef, StringComparison.Ordinal)}");
        var dangling = await t.CountAsync(
            $"SELECT count(*) FROM events e WHERE e.topic='{proposed}' AND (e.payload->>'render_ref') IS NOT NULL " +
            "AND NOT EXISTS (SELECT 1 FROM render_traces rt WHERE rt.render_ref = e.payload->>'render_ref')", ct).ConfigureAwait(false);
        Record("P3.2 无悬空引用（所有提案 render_ref 均可在投影表定位）", dangling == 0, $"dangling={dangling}");
        return results;
    }

    /// <summary>Nearest-rank percentile (no interpolation): rank = ⌈p/100 · n⌉; with small n, p99 is the maximum.</summary>
    public static double? Percentile(IReadOnlyList<double> sorted, double p)
    {
        if (sorted.Count == 0)
            return null;
        var rank = (int)Math.Ceiling(p / 100 * sorted.Count);
        return sorted[Math.Min(Math.Max(rank, 1), sorted.Count) - 1];
    }

    public static JsonObject Summarize(IReadOnlyList<(double Ms, int Status)> samples)
    {
        var ok = samples.Where(s => s.Status == 201).Select(s => s.Ms).Order().ToList();
        var errors = samples.Where(s => s.Status != 201).ToList();
        var o = new JsonObject
        {
            ["n"] = ok.Count,
            ["errors"] = errors.Count,
            ["errorDetail"] = new JsonArray([.. errors.GroupBy(e => e.Status == 0 ? "network" : $"http:{e.Status}").Select(g => (JsonNode)$"{g.Key}×{g.Count()}")]),
            ["min"] = ok.Count > 0 ? ok[0] : null,
            ["max"] = ok.Count > 0 ? ok[^1] : null,
            ["mean"] = ok.Count > 0 ? ok.Average() : null,
            ["p50"] = Percentile(ok, 50),
            ["p95"] = Percentile(ok, 95),
            ["p99"] = Percentile(ok, 99),
            ["p99EqualsMax"] = ok.Count > 0 && Percentile(ok, 99) == ok[^1],
            ["raw"] = new JsonArray([.. ok.Select(x => (JsonNode)x)]),
        };
        return o;
    }

    private static int tickCounter = 1_000_000;

    /// <summary>One opinion_evaluation event with unique keys (a reused key would be deduplicated and measure nothing).</summary>
    public static JsonObject BenchEnvelope()
    {
        var tick = Interlocked.Increment(ref tickCounter);
        var id = $"bench-{GrowthBase36(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds())}-{Rand()}";
        var payload = new JsonObject
        {
            ["evaluation_target"] = "bench-target",
            ["claims"] = new JsonArray(new JsonObject { ["claim_text"] = "bench claim", ["confidence"] = 0.5 }),
            ["uncertainty_notes"] = "bench run; not a scientific claim",
        };
        var inputHash = JsFormat.Sha256Hex(payload.ToJsonString() + id);
        return new JsonObject
        {
            ["event_id"] = id, ["trace_id"] = $"trace-{id}", ["correlation_id"] = $"corr-{id}", ["timestamp"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            ["producer"] = "bench-ingest-latency", ["origin_device"] = "bench-host", ["privacy_level"] = 1, ["evidence_refs"] = new JsonArray(),
            ["causal_context_refs"] = new JsonArray(), ["risk_score"] = 0.1, ["idempotency_key"] = $"idem-{id}", ["replay_mode"] = "live", ["risk_level"] = "low",
            ["tick"] = tick % int.MaxValue, ["causality"] = new JsonObject { ["inputHash"] = inputHash },
            ["topic"] = "aijade.learning.constraint.opinion_evaluation", ["payload"] = payload,
        };
    }

    private static string GrowthBase36(long v)
    {
        const string digits = "0123456789abcdefghijklmnopqrstuvwxyz";
        var sb = new StringBuilder();
        do
        {
            sb.Insert(0, digits[(int)(v % 36)]);
            v /= 36;
        }
        while (v > 0);
        return sb.ToString();
    }

    private static async Task<(double Ms, int Status)> TimedAsync(Target t, CancellationToken ct)
    {
        var sw = Stopwatch.StartNew();
        try
        {
            var (status, _) = await t.PostAsync(BenchEnvelope(), ct: ct).ConfigureAwait(false);
            return (sw.Elapsed.TotalMilliseconds, status);
        }
        catch (HttpRequestException)
        {
            return (sw.Elapsed.TotalMilliseconds, 0);
        }
    }

    /// <summary>
    /// Observation → proposal loop latency: after one paired render trace, each observation is posted and the time until the
    /// worker has written a new learning proposal (polled every 20 ms) is recorded. Needs the worker process and the queue.
    /// </summary>
    public static async Task<JsonObject> BenchLoopAsync(Target t, int n, CancellationToken ct = default)
    {
        const string session = "bench-loop";
        var trace = $"trace-loop-{Rand()}";
        var r = await t.PostAsync(Envelope("aijade.persona.render_requested", new JsonObject
        {
            ["session_id"] = session, ["persona_snapshot_ref"] = "ps-loop", ["intent_ref"] = $"intent-loop-{Rand()}",
        }, trace), ct: ct).ConfigureAwait(false);
        if (r.Status != 201)
            throw new InvalidOperationException($"render_requested: {r.Status}");
        r = await t.PostAsync(Envelope("aijade.lpm.render_ready", new JsonObject
        {
            ["session_id"] = session, ["render_ref"] = $"render-loop-{Rand()}", ["applied_params_hash"] = "hash-loop", ["asset_version_hash"] = "avh-loop",
        }, trace), ct: ct).ConfigureAwait(false);
        if (r.Status != 201)
            throw new InvalidOperationException($"render_ready: {r.Status}");
        const string countSql = "SELECT count(*) FROM events WHERE topic='aijade.learning.proposed.evidence'";
        var samples = new List<(double, int)>();
        for (var i = 0; i < n; i++)
        {
            var before = await t.CountAsync(countSql, ct).ConfigureAwait(false);
            var sw = Stopwatch.StartNew();
            r = await t.PostAsync(Envelope("aijade.video.observation.webpage_text", new JsonObject
            {
                ["session_id"] = session, ["source_url"] = $"https://example.com/loop-{i}", ["content_hash"] = $"ch-loop-{Rand()}",
                ["spans"] = new JsonArray(new JsonObject { ["start_offset"] = 0, ["end_offset"] = 40, ["label"] = "paragraph" }),
                ["observation_text"] = "The page claims that regular sleep improves recall by a large margin.",
            }, extra: new JsonObject { ["tick"] = 1000 + i, ["causality"] = new JsonObject { ["inputHash"] = $"ih-loop-{Rand()}" } }), ct: ct).ConfigureAwait(false);
            var seen = await PollAsync(async () => await t.CountAsync(countSql, ct).ConfigureAwait(false) > before ? "yes" : null,
                TimeSpan.FromSeconds(30), TimeSpan.FromMilliseconds(20), ct).ConfigureAwait(false);
            samples.Add((sw.Elapsed.TotalMilliseconds, seen is null ? 0 : r.Status));
        }
        var s = Summarize(samples);
        s["requested"] = n;
        s["note"] = "observation POST to the proposal row appearing (20 ms polling); status 0 = no proposal within 30 s";
        return new JsonObject
        {
            ["runs"] = new JsonObject { ["loop"] = s },
            ["provenance"] = new JsonObject
            {
                ["percentileMethod"] = "nearest-rank (no interpolation)",
                ["runtime"] = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
                ["platform"] = System.Runtime.InteropServices.RuntimeInformation.RuntimeIdentifier,
            },
        };
    }

    /// <summary>Ingest latency, sequential (one at a time) and concurrent (all n at once), each after discarded warm-up requests.</summary>
    public static async Task<JsonObject> BenchIngestAsync(Target t, string mode, int n, int warmup, CancellationToken ct = default)
    {
        var runs = new JsonObject();
        if (mode is "sequential" or "both")
        {
            for (var i = 0; i < warmup; i++)
                await TimedAsync(t, ct).ConfigureAwait(false);
            var samples = new List<(double, int)>();
            for (var i = 0; i < n; i++)
                samples.Add(await TimedAsync(t, ct).ConfigureAwait(false));
            var s = Summarize(samples);
            s["requested"] = n;
            s["warmupDiscarded"] = warmup;
            s["detailed"] = new JsonArray([.. samples.Select(x => (JsonNode)new JsonObject { ["ms"] = Math.Round(x.Item1, 3), ["status"] = x.Item2 })]);
            runs["sequential"] = s;
        }
        if (mode is "concurrent" or "both")
        {
            for (var i = 0; i < warmup; i++)
                await TimedAsync(t, ct).ConfigureAwait(false);
            var wall = Stopwatch.StartNew();
            var samples = await Task.WhenAll(Enumerable.Range(0, n).Select(_ => TimedAsync(t, ct))).ConfigureAwait(false);
            var wallMs = wall.Elapsed.TotalMilliseconds;
            var s = Summarize(samples);
            s["requested"] = n;
            s["concurrency"] = n;
            s["warmupDiscarded"] = warmup;
            s["wallClockMs"] = Math.Round(wallMs, 3);
            s["detailed"] = new JsonArray([.. samples.Select(x => (JsonNode)new JsonObject { ["ms"] = Math.Round(x.Ms, 3), ["status"] = x.Status })]);
            runs["concurrent"] = s;
        }
        return new JsonObject
        {
            ["mode"] = mode, ["n"] = n, ["warmup"] = warmup, ["startedAt"] = DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture),
            ["provenance"] = new JsonObject
            {
                ["percentileMethod"] = "nearest-rank (no interpolation)",
                ["authPath"] = "Bearer static token; real session resolution NOT exercised",
                ["warmupDiscarded"] = warmup,
                ["runtime"] = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
                ["platform"] = System.Runtime.InteropServices.RuntimeInformation.RuntimeIdentifier,
            },
            ["runs"] = runs,
        };
    }
}
