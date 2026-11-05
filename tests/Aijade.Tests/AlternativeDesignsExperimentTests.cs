using System.Diagnostics;
using System.Text.Json.Nodes;

using Aijade.Memory.Contracts;
using Aijade.Memory.Pgc;
using Aijade.Memory.V9;
using Aijade.Server.V9;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

/// <summary>
/// experiments/plans/2026-11-05-p1-a-alternative-designs.md on input and data faults: every fault and every valid input against
/// every configuration, each on a freshly migrated database. Writes {AIJADE_EXPERIMENT_DIR}/alternative-designs.json; skipped
/// without that variable, because the matrix takes many minutes. Faults defined on code are not part of this test.
/// </summary>
public class AlternativeDesignsExperimentTests
{
    private const string Learning = "aijade.learning.proposed.evidence";
    private const string Request = "aijade.persona.render_requested";
    private const string Receipt = "aijade.lpm.render_ready";

    private static JsonObject Env(string id, string trace, string topic, JsonObject payload, bool v10 = false)
    {
        var e = new JsonObject
        {
            ["event_id"] = $"evt-{id}", ["trace_id"] = trace, ["correlation_id"] = $"corr-{id}", ["timestamp"] = 1_760_000_000_000L, ["producer"] = "p1a",
            ["origin_device"] = "host", ["privacy_level"] = 1, ["evidence_refs"] = new JsonArray(), ["causal_context_refs"] = new JsonArray(), ["risk_score"] = 0.1,
            ["idempotency_key"] = $"key-{id}", ["replay_mode"] = "live", ["risk_level"] = "low", ["topic"] = topic, ["payload"] = payload,
        };
        if (v10 || topic.StartsWith("aijade.learning.", StringComparison.Ordinal) || topic.StartsWith("aijade.video.", StringComparison.Ordinal))
        {
            e["tick"] = 1;
            e["causality"] = new JsonObject { ["inputHash"] = $"hash-{id}" };
        }
        return e;
    }

    private static JsonObject Req(string id, string trace, string intent = "intent-1") =>
        Env(id, trace, Request, new JsonObject { ["session_id"] = "s", ["persona_snapshot_ref"] = "snap", ["intent_ref"] = intent });

    private static JsonObject Rec(string id, string trace, string render = "render-1", string applied = "applied-1", string asset = "asset-1") =>
        Env(id, trace, Receipt, new JsonObject { ["session_id"] = "s", ["render_ref"] = render, ["applied_params_hash"] = applied, ["asset_version_hash"] = asset });

    private static JsonObject Prop(string id, string render = "render-1", string applied = "applied-1", string asset = "asset-1", string claim = "the viewer slowed down", double confidence = .7) =>
        Env(id, $"trace-{id}", Learning, new JsonObject
        {
            ["session_id"] = "s", ["proposal_id"] = $"p-{id}", ["render_ref"] = render, ["applied_params_hash"] = applied, ["asset_version_hash"] = asset,
            ["evidence_hash"] = $"e-{id}", ["claim_text"] = claim, ["confidence"] = confidence,
        });

    private static JsonObject Without(JsonObject o, string field)
    {
        (o["payload"]!.AsObject()).Remove(field);
        return o;
    }

    private static JsonObject Opinion(string id, string? evidence = null)
    {
        var e = Env(id, $"trace-{id}", "aijade.learning.constraint.opinion_evaluation", new JsonObject
        {
            ["evaluation_target"] = "t", ["claims"] = new JsonArray(new JsonObject { ["claim_text"] = "c", ["confidence"] = .5 }), ["uncertainty_notes"] = "n",
        });
        if (evidence is not null)
            e["evidence_refs"] = new JsonArray(evidence);
        return e;
    }

    private static JsonObject Weave(string id, params string[] writes) => Env(id, $"trace-{id}", "aijade.evidence.weave_candidate_ready", new JsonObject
    {
        ["tx_id"] = $"tx-{id}", ["weave_id"] = $"w-{id}", ["graph_hash"] = "g", ["candidate_memory_write_ids"] = new JsonArray([.. writes.Select(w => (JsonNode)w)]),
    });

    /// <summary>The inputs a fault needs first: one paired trace.</summary>
    private static readonly JsonObject[] Base = [Req("base-req", "trace-base"), Rec("base-rec", "trace-base")];

    private sealed record Case(string Set, string Id, string Klass, string Form, string Kind, JsonObject[] Inputs, bool Malformed = false, bool Anonymous = false, string? Promotion = null);

    private static Case F(string klass, string id, string form, params JsonObject[] inputs) => new("1", id, klass, form, "fault", inputs);

    private static IEnumerable<Case> Cases()
    {
        // Set 1: input and data faults, three per class.
        yield return F("missing source", "s1", "a proposal with no render_ref", Without(Prop("s1"), "render_ref"));
        yield return F("missing source", "s2", "a proposal citing a render absent from the projection", Prop("s2", render: "render-nowhere"));
        yield return F("missing source", "s3", "a proposal with an empty render_ref", Prop("s3", render: ""));
        yield return F("wrong memory reference", "m1", "an opinion whose evidence_refs names no record", Opinion("m1", "evt-nowhere"));
        yield return F("wrong memory reference", "m2", "a weave candidate whose write ids name no record", Weave("m2", "write-nowhere"));
        yield return F("wrong memory reference", "m3", "an event whose causal_context_refs names no record", WithCausal(Opinion("m3"), "evt-nowhere"));
        yield return F("stale skill (nearest form)", "t1", "a proposal citing a paired render a later receipt superseded", Req("t1a", "trace-t1"), Rec("t1b", "trace-t1", render: "render-2", applied: "applied-2", asset: "asset-2"), Prop("t1"));
        yield return F("stale skill (nearest form)", "t2", "a proposal citing a render two receipts old", Req("t2a", "trace-t2a"), Rec("t2b", "trace-t2a", render: "render-2", applied: "a2"), Req("t2c", "trace-t2c"), Rec("t2d", "trace-t2c", render: "render-3", applied: "a3"), Prop("t2"));
        yield return F("stale skill (nearest form)", "t3", "a proposal citing a render whose asset version was replaced later", Req("t3a", "trace-t3"), Rec("t3b", "trace-t3", render: "render-2", asset: "asset-9"), Prop("t3"));
        yield return new Case("1", "f1", "self-assessment false pass", "a promotion job whose pack declares core tests passed while counting 3 failures", "fault", [], Promotion: "core");
        yield return new Case("1", "f2", "self-assessment false pass", "a promotion job whose pack declares core tests passed with no tests counted", "fault", [], Promotion: "none");
        yield return new Case("1", "f3", "self-assessment false pass", "a promotion job whose pack declares core tests passed while counting more failures than passes", "fault", [], Promotion: "more");
        yield return F("success reported for a failed execution", "x1", "a receipt for an intent the renderer did not apply", Req("x1a", "trace-x1"), Rec("x1b", "trace-x1", render: "render-x1", applied: "never-applied"));
        yield return F("success reported for a failed execution", "x2", "a receipt naming an asset the renderer does not hold", Req("x2a", "trace-x2"), Rec("x2b", "trace-x2", render: "render-x2", asset: "asset-absent"));
        yield return F("success reported for a failed execution", "x3", "a receipt with a second session's identifier", Req("x3a", "trace-x3"), Env("x3b", "trace-x3", Receipt, new JsonObject { ["session_id"] = "other-session", ["render_ref"] = "render-x3", ["applied_params_hash"] = "a", ["asset_version_hash"] = "b" }));
        yield return F("missing or out-of-order receipt", "o1", "a request left without a receipt", Req("o1", "trace-o1"));
        yield return F("missing or out-of-order receipt", "o2", "a receipt before its request", Rec("o2a", "trace-o2", render: "render-o2"), Req("o2b", "trace-o2"));
        yield return F("missing or out-of-order receipt", "o3", "a proposal citing a trace without a request", Rec("o3a", "trace-o3", render: "render-o3"), Prop("o3", render: "render-o3"));
        yield return F("parameter or asset mismatch", "p1", "a proposal whose fingerprint differs from its receipt's", Prop("p1", applied: "forged"));
        yield return F("parameter or asset mismatch", "p2", "a proposal whose asset version differs from its receipt's", Prop("p2", asset: "forged"));
        yield return F("parameter or asset mismatch", "p3", "a proposal differing in both", Prop("p3", applied: "forged", asset: "forged"));
        yield return F("duplicate", "d1", "a replay under the same idempotency key", Opinion("d1"), Opinion("d1"));
        yield return F("duplicate", "d2", "the same event under a new key", Opinion("d2"), WithKey(Opinion("d2"), "key-d2-again"));
        yield return F("duplicate", "d3", "the same proposal under a new key", Prop("d3"), WithKey(Prop("d3"), "key-d3-again"));

        // Set 2, second kind: identifiers correct, content semantically wrong. The first kind (a changed unit or meaning) is a code fault.
        yield return new Case("2", "w1", "semantically wrong record", "a proposal with real identifiers and an empty-of-meaning claim", "fault", [Prop("w1", claim: "lorem ipsum")]);
        yield return new Case("2", "w2", "semantically wrong record", "a proposal with real identifiers and a claim contradicting its evidence", "fault", [Prop("w2", claim: "the viewer did not watch the video they watched")]);
        yield return new Case("2", "w3", "semantically wrong record", "a proposal with real identifiers and full confidence in a guess", "fault", [Prop("w3", claim: "probably a guess", confidence: 1)]);
        yield return new Case("2", "w4", "semantically wrong record", "an observation whose text does not match its hash", "fault", [Env("w4", "trace-w4", "aijade.video.observation.webpage_text", new JsonObject { ["session_id"] = "s", ["source_url"] = "https://example.test/a", ["content_hash"] = "hash-of-other-text", ["spans"] = new JsonArray(new JsonObject { ["start_offset"] = 0, ["end_offset"] = 4 }), ["observation_text"] = "text" })]);
        yield return new Case("2", "w5", "semantically wrong record", "an observation whose span lies outside its text", "fault", [Env("w5", "trace-w5", "aijade.video.observation.webpage_text", new JsonObject { ["session_id"] = "s", ["source_url"] = "https://example.test/b", ["content_hash"] = "h", ["spans"] = new JsonArray(new JsonObject { ["start_offset"] = 900, ["end_offset"] = 4 }), ["observation_text"] = "text" })]);

        // Set 3: the nine boundary negatives of the end-to-end cases; the 33 mutants are faults on code, not part of this test.
        var n2 = Opinion("n2"); n2.Remove("tick");
        var n3 = Opinion("n3"); n3["causality"] = new JsonObject { ["inputHash"] = "" };
        var n4 = Opinion("n4"); n4["surplus"] = 1;
        var n5 = Opinion("n5"); n5["topic"] = "aijade.not.a.topic";
        var n6 = Without(Req("n6", "trace-n6"), "intent_ref");
        yield return new Case("3", "n1", "N1", "unauthenticated request", "fault", [Opinion("n1")], Anonymous: true);
        yield return new Case("3", "n2", "N2", "missing tick", "fault", [n2]);
        yield return new Case("3", "n3", "N3", "empty input fingerprint", "fault", [n3]);
        yield return new Case("3", "n4", "N4", "unknown envelope field", "fault", [n4]);
        yield return new Case("3", "n5", "N5", "unknown topic", "fault", [n5]);
        yield return new Case("3", "n6", "N6", "missing intent_ref", "fault", [n6]);
        yield return new Case("3", "n7", "N7", "render_ref equal to the envelope's own identifier", "fault", [Req("n7a", "trace-n7"), Rec("n7b", "trace-n7", render: "trace-n7")]);
        yield return new Case("3", "n8", "N8", "a second receipt on one trace with another value", "fault", [Rec("n8", "trace-base", render: "render-other")]);
        yield return new Case("3", "n9", "N9", "malformed JSON", "fault", [], Malformed: true);

        // Valid inputs: refusing one of these is a false refusal.
        for (var i = 0; i < 8; i++)
            yield return new Case("valid", $"v{i}", "valid", "an honest proposal", "valid", [Prop($"v{i}", claim: $"claim {i}")]);
        for (var i = 8; i < 14; i++)
            yield return new Case("valid", $"v{i}", "valid", "a paired render", "valid", [Req($"v{i}a", $"trace-v{i}", $"intent-{i}"), Rec($"v{i}b", $"trace-v{i}", render: $"render-v{i}")]);
        for (var i = 14; i < 20; i++)
            yield return new Case("valid", $"v{i}", "valid", "an opinion", "valid", [Opinion($"v{i}")]);
        for (var i = 20; i < 22; i++)
            yield return new Case("valid", $"v{i}", "valid", "a weave candidate without writes", "valid", [Weave($"v{i}")]);
        for (var i = 22; i < 24; i++)
        {
            yield return new Case("valid", $"v{i}", "valid", "an honest observation", "valid", [Env($"v{i}", $"trace-v{i}", "aijade.video.observation.webpage_text", new JsonObject
            {
                ["session_id"] = "s", ["source_url"] = $"https://example.test/v{i}", ["content_hash"] = $"hash-{i}", ["spans"] = new JsonArray(new JsonObject { ["start_offset"] = 0, ["end_offset"] = 4 }), ["observation_text"] = "text",
            })]);
        }
    }

    private static JsonObject WithCausal(JsonObject e, string r)
    {
        e["causal_context_refs"] = new JsonArray(r);
        return e;
    }

    private static JsonObject WithKey(JsonObject e, string key)
    {
        e["idempotency_key"] = key;
        return e;
    }

    private static PromotionJob Job(string id, string kind)
    {
        var session = $"session-{id}";
        var honest = new JsonObject { ["lr"] = 0.01 };
        var hash = ShadowParams.ComputeLearningInputHash(session, id, honest);
        var proposal = new ShadowParamsProposal(id, session, hash, ShadowParamsAnchorKind.ShadowParams, true, honest, 0.9);
        var gate = kind switch { "core" => new CoreTestGate(true, 10, 3), "none" => new CoreTestGate(true, 0, 0), _ => new CoreTestGate(true, 2, 9) };
        return new PromotionJob($"job-{id}", id, session, $"trace-{id}", 7, hash, new EvaluationEvidencePack($"pack-{id}", id, gate, 0, TraceId: $"trace-{id}"), proposal, PgcV6State: new PgcState4(0, 0, 0, 0));
    }

    [Fact]
    public async Task Every_input_fault_and_valid_input_against_every_configuration()
    {
        if (Environment.GetEnvironmentVariable("AIJADE_EXPERIMENT_DIR") is not { Length: > 0 } dir)
        {
            Assert.Skip("set AIJADE_EXPERIMENT_DIR to run the P1-A matrix");
            return;
        }
        var ct = TestContext.Current.CancellationToken;
        var rows = new JsonArray();
        foreach (var (key, setting) in new[] { ("1 paper", (string?)null), ("2 liberal", "liberal"), ("3 contracts", "contracts"), ("4 lineage", "lineage") })
        {
            foreach (var c in Cases())
            {
                var settings = new Dictionary<string, string?>();
                if (setting is not null)
                    settings[V9Alternative.ConfigKey] = setting;
                await using var host = await ServerTestHost.StartAsync(settings, worker: false);
                foreach (var b in Base)
                    await host.PostAsync("/api/v1/v9/events", b);
                var audit0 = setting == "lineage" ? await V9Alternative.AuditAsync(host.Db, ct) : [];
                long Events0 = await host.CountAsync("SELECT count(*) FROM events"), Traces0 = await host.CountAsync("SELECT count(*) FROM render_traces");
                var clock = Stopwatch.StartNew();
                var refused = false;
                var point = "none";
                var statuses = new JsonArray();
                if (c.Promotion is not null)
                {
                    var result = await host.App.Services.GetRequiredService<PromotionService>().ProcessAsync(Job(c.Id, c.Promotion), ct);
                    statuses.Add(result.Ok ? "promoted" : $"refused at {result.Stage}");
                    if (!result.Ok)
                    {
                        refused = true;
                        point = "gate";
                    }
                }
                else if (c.Malformed)
                {
                    var (status, _) = await host.PostRawAsync("/api/v1/v9/events", "{not json");
                    statuses.Add(status);
                    refused = status >= 400;
                    point = refused ? "boundary" : "none";
                }
                else
                {
                    foreach (var input in c.Inputs)
                    {
                        var (status, body) = await host.PostAsync("/api/v1/v9/events", input.DeepClone(), auth: !c.Anonymous);
                        statuses.Add(status);
                        if (status >= 400)
                        {
                            refused = true;
                            var text = body?.ToJsonString() ?? "";
                            point = status == 401 ? "authentication" : text.Contains("CONSUMER_UNREADABLE", StringComparison.Ordinal) ? "consumer" : text.Contains("INVALID_RENDER_TRACE_REFERENCE", StringComparison.Ordinal) ? "write" : status >= 500 ? "write (server error)" : "boundary";
                            break;
                        }
                    }
                }
                var flagged = false;
                if (setting == "lineage")
                {
                    var audit = await V9Alternative.AuditAsync(host.Db, ct);
                    flagged = audit.Count > audit0.Count;
                    if (flagged && !refused)
                        point = "after-the-fact audit";
                }
                clock.Stop();
                rows.Add(new JsonObject
                {
                    ["configuration"] = key, ["set"] = c.Set, ["id"] = c.Id, ["class"] = c.Klass, ["form"] = c.Form, ["kind"] = c.Kind,
                    ["detected"] = refused || flagged, ["point"] = point, ["statuses"] = statuses, ["ms"] = clock.Elapsed.TotalMilliseconds,
                    ["eventsWritten"] = await host.CountAsync("SELECT count(*) FROM events") - Events0,
                    ["tracesWritten"] = await host.CountAsync("SELECT count(*) FROM render_traces") - Traces0,
                });
            }
        }
        var report = new JsonObject
        {
            ["experiment"] = "P1-A: input and data faults against four configurations, each cell on a freshly migrated database",
            ["plan"] = "experiments/plans/2026-11-05-p1-a-alternative-designs.md",
            ["codeCommit"] = Environment.GetEnvironmentVariable("AIJADE_GIT_COMMIT"),
            ["deviations"] = new JsonArray(
                "Run on the Mac before the supervisor's review of the plan: the first author's decision of 5 November 2026.",
                "Not run in this file: the faults defined on code (the changed units or meanings of set 2 and the 33 mutants of set 3), their pre-deployment checks and the consumer expectation tests of configuration 3, which the plan commits with the switches. Without them this file cannot give configuration 3's or any configuration's pre-deployment detection.",
                "Corrected after a first run of this matrix: the audit job treated references to evidence packets, chunks and traces as dangling, which listed an honest observation as a fault (a probe on 5 November 2026 found 12 such entries), so two semantically wrong observations were counted as detected. It now resolves those references, and two of the 24 valid inputs became honest observations, so that a false alarm of the audit would show.",
                "The worker is not started: nothing here measures rows read by a downstream consumer other than the projection."),
            ["rows"] = rows,
            ["generatedAt"] = DateTimeOffset.UtcNow.ToString("o"),
        };
        await File.WriteAllTextAsync(Path.Combine(dir, "alternative-designs.json"), report.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping }) + "\n", ct);
    }
}
