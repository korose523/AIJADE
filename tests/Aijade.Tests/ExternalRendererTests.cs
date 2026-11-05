using System.Globalization;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

using Aijade.Core.Js;
using Aijade.Integrations.Renderer;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;
using Aijade.Memory.Kernel;
using Aijade.Server.V9;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

/// <summary>Builds the study's constructed variants of a render-state file, line by line.</summary>
internal static class RenderFileVariants
{
    private static string Sha(IEnumerable<string> lines) =>
        JsFormat.Sha256Hex(string.Concat(lines.Select(l => l + "\n")));

    private static List<int> PreSolve(List<string> lines) =>
        [.. Enumerable.Range(0, lines.Count).Where(i => JsonNode.Parse(lines[i])!["packet_type"]?.GetValue<string>() == AijadeRendererPackets.RenderState)];

    /// <summary>The same lines with their end record recomputed.</summary>
    public static List<string> Reend(List<string> lines)
    {
        var body = lines.Take(lines.Count - 1).ToList();
        body.Add(new JsonObject { ["record"] = "end", ["lines"] = body.Count, ["sha256"] = Sha(body), ["complete"] = true }.ToJsonString());
        return body;
    }

    /// <summary>The last three rows before the end record removed; the end record kept as it was.</summary>
    public static List<string> Truncated(List<string> lines) => [.. lines.Take(lines.Count - 4), lines[^1]];

    private static List<string> WithRow(List<string> lines, int preSolveIndex, Action<JsonObject> change)
    {
        var copy = new List<string>(lines);
        var at = PreSolve(lines)[preSolveIndex];
        var row = JsonNode.Parse(copy[at])!.AsObject();
        change(row);
        copy[at] = row.ToJsonString();
        return copy;
    }

    /// <summary>One applied value of one row changed; the row's renderer hash kept.</summary>
    public static List<string> Altered(List<string> lines, int k) => WithRow(lines, k, row =>
    {
        var morphs = row["expressions_applied"]!.AsObject();
        var key = morphs.First().Key;
        morphs[key] = morphs[key]!.GetValue<double>() + 0.125;
    });

    public static List<string> TraceReplaced(List<string> lines, int k, string trace) => WithRow(lines, k, row =>
    {
        foreach (var c in row["consumed"]!.AsArray())
            c!["trace_id"] = trace;
    });

    public static List<string> TraceAdded(List<string> lines, int k, string trace) => WithRow(lines, k, row =>
        row["consumed"]!.AsArray().Add(new JsonObject { ["packet_type"] = "AffectToAvatarPacket", ["seq"] = 999, ["trace_id"] = trace }));

    /// <summary>One pre-solve row and the post-solve row that follows it removed.</summary>
    public static List<string> RowRemoved(List<string> lines, int k)
    {
        var at = PreSolve(lines)[k];
        var copy = new List<string>(lines);
        copy.RemoveRange(at, 2);
        return copy;
    }
}

/// <summary>P1-C's registry, sealing check and importer on files built here (no client, no database).</summary>
public class RenderEvidenceTests
{
    private static List<string> Lines(string session, string context, params string[] traces)
    {
        var lines = new List<string>
        {
            new JsonObject { ["record"] = "header", ["schema"] = RenderStateFile.SchemaV2, ["renderer_context_id"] = context, ["session_id"] = session, ["pmx_sha256"] = "model-1" }.ToJsonString(),
        };
        for (var i = 0; i < traces.Length; i++)
        {
            var applied = new JsonObject { ["morph.a"] = 0.25 + i, ["bone.b"] = 0.5 };
            lines.Add(new JsonObject
            {
                ["packet_type"] = "RenderStatePacket", ["seq"] = i, ["run_id"] = session, ["t_sim"] = i, ["schema_version"] = "v1.0",
                ["consumed"] = new JsonArray(new JsonObject { ["trace_id"] = traces[i] }, new JsonObject { ["trace_id"] = traces[i] }),
                ["expressions_applied"] = new JsonObject { ["a"] = 0.25 + i }, ["avatar_state"] = new JsonObject { ["bones"] = new JsonObject { ["b"] = 0.5 } },
                ["applied_params_hash"] = RenderStateReceipts.RendererHash(applied),
            }.ToJsonString());
            lines.Add(new JsonObject { ["record"] = "post_solve_observation", ["render_seq"] = i }.ToJsonString());
        }
        lines.Add("{}");
        return RenderFileVariants.Reend(lines);
    }

    private static RenderStateFile FileOf(List<string> lines)
    {
        var path = Path.Combine(Path.GetTempPath(), $"render-evidence-{Guid.NewGuid():N}.jsonl");
        try
        {
            File.WriteAllText(path, string.Concat(lines.Select(l => l + "\n")));
            return RenderStateFile.Read(path);
        }
        finally
        {
            File.Delete(path);
        }
    }

    private static readonly IntentRegistry Registry = new("s1", "ctx-1", [new("a", "snap", 1), new("b", "snap", 2), new("c", "snap", 3)]);

    private static RenderSessionManifest Manifest(RenderStateFile f) =>
        new("s1", "ctx-1", f.End is null ? RenderSessionManifest.Unfinished : RenderSessionManifest.Closed, 3, f.PreSolveRows.Count, f.FileSha256, true);

    [Fact]
    public void A_healthy_file_gives_one_receipt_per_registered_intent_bound_to_the_registry()
    {
        var f = FileOf(Lines("s1", "ctx-1", "a", "b", "c"));
        var plan = RenderReceiptImporter.Plan(Manifest(f), Registry, f);
        Assert.Empty(plan.FileReasons);
        Assert.Empty(plan.Unknown);
        Assert.Equal(["a", "b", "c"], plan.Receipts.Select(r => r.IntentId));
        Assert.Equal("ctx-1:1", plan.Receipts[1].RenderRef);
        Assert.Equal("model-1", plan.Receipts[1].Receipt["payload"]!["asset_version_hash"]!.GetValue<string>());
        Assert.Equal("b", plan.Receipts[1].Request["payload"]!["intent_ref"]!.GetValue<string>());
        Assert.Equal(plan.Receipts[1].Request["trace_id"]!.GetValue<string>(), plan.Receipts[1].Receipt["trace_id"]!.GetValue<string>());
        Assert.NotEqual(plan.Receipts[1].Receipt["payload"]!["applied_params_hash"]!.GetValue<string>(), JsonNode.Parse(Lines("s1", "ctx-1", "a", "b", "c")[3])!["applied_params_hash"]!.GetValue<string>());
        Assert.True(AijadeEvents.IsValid(plan.Receipts[1].Receipt));
        Assert.True(AijadeEvents.IsValid(plan.Receipts[1].Request));
    }

    [Fact]
    public void File_level_faults_stop_the_whole_import_and_leave_every_intent_unknown()
    {
        var healthy = Lines("s1", "ctx-1", "a", "b", "c");
        static void Refused(RenderSessionManifest manifest, IntentRegistry registry, RenderStateFile file, string reason)
        {
            var plan = RenderReceiptImporter.Plan(manifest, registry, file);
            Assert.Contains(reason, plan.FileReasons);
            Assert.Empty(plan.Receipts);
            Assert.Equal(registry.Intents.Count, plan.Unknown.Count);
        }
        var noEnd = FileOf([.. healthy.Take(healthy.Count - 1)]);
        Refused(Manifest(noEnd), Registry, noEnd, RenderSealReason.EndRecordMissing);
        var truncated = FileOf(RenderFileVariants.Truncated(healthy));
        Refused(Manifest(truncated), Registry, truncated, RenderSealReason.EndCountMismatch);
        var altered = FileOf(RenderFileVariants.Altered(healthy, 1));
        Refused(Manifest(altered), Registry, altered, RenderSealReason.EndDigestMismatch);
        var f = FileOf(healthy);
        Refused(Manifest(f), Registry, FileOf(RenderFileVariants.Reend(RenderFileVariants.Altered(healthy, 1))), RenderSealReason.FileDigestMismatch);
        var v1 = FileOf([.. healthy.Skip(1).Take(healthy.Count - 2)]);
        Refused(Manifest(v1), Registry, v1, RenderSealReason.NotSchemaV2);
        Refused(Manifest(f) with { RendererContextId = "ctx-2" }, Registry, f, RenderSealReason.RendererContextMismatch);
        Refused(Manifest(f) with { SessionId = "s2" }, Registry with { SessionId = "s2" }, f, RenderSealReason.SessionMismatch);
        Refused(Manifest(f) with { Complete = false }, Registry, f, RenderSealReason.ManifestNotComplete);
        Refused(Manifest(f) with { ExpectedIntents = 4 }, Registry, f, RenderSealReason.ManifestCountMismatch);
    }

    [Fact]
    public void Row_level_faults_cost_only_the_rows_and_intents_they_touch()
    {
        var healthy = Lines("s1", "ctx-1", "a", "b", "c");
        static ReceiptImportPlan Planned(List<string> lines)
        {
            var f = FileOf(RenderFileVariants.Reend(lines));
            return RenderReceiptImporter.Plan(Manifest(f), Registry, f);
        }
        var unregistered = Planned(RenderFileVariants.TraceReplaced(healthy, 1, "nobody"));
        Assert.Equal(["a", "c"], unregistered.Receipts.Select(r => r.IntentId));
        Assert.Equal(("b", RenderSealReason.NoRow), Assert.Single(unregistered.Unknown));
        Assert.Equal((1L, RenderSealReason.TraceNotRegistered), Assert.Single(unregistered.RefusedRows));

        var noRow = Planned(RenderFileVariants.RowRemoved(healthy, 1));
        Assert.Equal(("b", RenderSealReason.NoRow), Assert.Single(noRow.Unknown));
        Assert.Empty(noRow.RefusedRows);

        var badHash = Planned(RenderFileVariants.Altered(healthy, 1));
        Assert.Equal(("b", RenderSealReason.RendererHashMismatch), Assert.Single(badHash.Unknown));

        var two = Planned(RenderFileVariants.TraceAdded(healthy, 0, "b"));
        Assert.Equal(["c"], two.Receipts.Select(r => r.IntentId));
        Assert.Equal([("a", RenderSealReason.TwoIntentsInRow), ("b", RenderSealReason.TwoIntentsInRow)], two.Unknown);
    }

    [Fact]
    public async Task The_registry_is_on_disk_before_anything_reads_it_and_the_importer_stops_at_the_first_refused_post()
    {
        var path = Path.Combine(Path.GetTempPath(), $"intent-registry-{Guid.NewGuid():N}.jsonl");
        try
        {
            IntentRegistry.Create(path, "s1", "ctx-1");
            IntentRegistry.Append(path, new("a", "snap", 5));
            var read = IntentRegistry.Read(path);
            Assert.Equal(("s1", "ctx-1", "a", 5L), (read.SessionId, read.RendererContextId, read.Intents[0].IntentId, read.Intents[0].SentMs));
        }
        finally
        {
            File.Delete(path);
        }
        var f = FileOf(Lines("s1", "ctx-1", "a", "b", "c"));
        var plan = RenderReceiptImporter.Plan(Manifest(f), Registry, f);
        var posted = new List<string>();
        await Assert.ThrowsAsync<InvalidOperationException>(() => RenderReceiptImporter.ImportAsync(plan, e =>
        {
            posted.Add(e["topic"]!.GetValue<string>());
            return Task.FromResult(posted.Count == 3 ? 400 : 201);
        }));
        Assert.Equal([AijadeEvents.PersonaRenderRequested, AijadeEvents.LpmRenderReady, AijadeEvents.PersonaRenderRequested], posted);
        var round = RenderSessionManifest.Parse(Manifest(f).ToJson());
        Assert.Equal(Manifest(f), round);
    }
}

/// <summary>
/// P1-C's steps as experiments/p1/external_renderer_driver.py calls them against the MOSAIC client. All are skipped unless their variables are set.
/// A difference from a recorded or expected outcome does not fail these tests: it is the study's result and goes to the results file.
/// </summary>
public class ExternalRendererStudyTests
{
    private const string Events = "/api/v1/v9/events";

    private static string? Env(string name) => Environment.GetEnvironmentVariable(name) is { Length: > 0 } v ? v : null;

    /// <summary>Registers then sends intents FROM..TO (one per second). Waits briefly for the file header to name the renderer instance; an old-format file has none.</summary>
    [Fact]
    public async Task Send_intents()
    {
        var ct = TestContext.Current.CancellationToken;
        if (Env("AIJADE_P1C_SEND_DIR") is not { } dir)
        {
            Assert.Skip("AIJADE_P1C_SEND_DIR is not set");
            return;
        }
        var session = Env("AIJADE_P1C_SESSION")!;
        var registryPath = Path.Combine(dir, "registry.jsonl");
        var from = int.Parse(Env("AIJADE_P1C_FROM")!, CultureInfo.InvariantCulture);
        var to = int.Parse(Env("AIJADE_P1C_TO")!, CultureInfo.InvariantCulture);
        if (!File.Exists(registryPath))
        {
            string? context = null;
            var filePath = Env("AIJADE_P1C_FILE")!;
            for (var i = 0; i < 40 && context is null; i++)
            {
                if (File.Exists(filePath) && new FileInfo(filePath).Length > 0)
                {
                    using var reader = new StreamReader(new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite));
                    context = JsonNode.Parse(await reader.ReadLineAsync(ct) ?? "{}")?["renderer_context_id"]?.GetValue<string>();
                }
                if (context is null)
                    await Task.Delay(250, ct);
            }
            IntentRegistry.Create(registryPath, session, context);
        }
        using var link = new MosaicRendererLink(int.Parse(Env("AIJADE_P1C_PORT")!, CultureInfo.InvariantCulture), session);
        var acts = Enum.GetValues<DialogueAct>();
        for (var n = from; n <= to; n++)
        {
            var id = $"pi_{session}_{n:00}";
            var intent = Pef.BuildPerformanceIntent(new PersonaInput(acts[n - 1]), new PerformanceIds(id, "aijade", "user:p1c", "persona:p1c"), 0, 2);
            IntentRegistry.Append(registryPath, new RegisteredIntent(id, intent.PersonaSnapshotRef, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
            await link.SendAsync(intent, ct: ct);
            await Task.Delay(1000, ct);
        }
    }

    /// <summary>Seals a session after its client has stopped.</summary>
    [Fact]
    public void Seal_session()
    {
        if (Env("AIJADE_P1C_SEAL_REGISTRY") is not { } registry)
        {
            Assert.Skip("AIJADE_P1C_SEAL_REGISTRY is not set");
            return;
        }
        var target = Env("AIJADE_P1C_SEAL_MANIFEST")!;
        File.WriteAllText(target + ".tmp", RenderSessionManifest.Seal(IntentRegistry.Read(registry), Env("AIJADE_P1C_SEAL_FILE")!).ToJson() + "\n");
        File.Move(target + ".tmp", target);
    }

    private sealed record Run(string Dir, IntentRegistry Registry, RenderSessionManifest Manifest, string FilePath)
    {
        public RenderStateFile File_ => RenderStateFile.Read(FilePath);
        public List<string> Lines => [.. File.ReadAllLines(FilePath).Where(l => l.Length > 0)];
    }

    private static Run Load(string dir) => new(dir, IntentRegistry.Read(Path.Combine(dir, "registry.jsonl")),
        RenderSessionManifest.Parse(File.ReadAllText(Path.Combine(dir, "manifest.json"))), Path.Combine(dir, "client", "aijade-render-state.jsonl"));

    private static RenderStateFile Temp(List<string> lines, out string path)
    {
        path = Path.Combine(Path.GetTempPath(), $"p1c-variant-{Guid.NewGuid():N}.jsonl");
        File.WriteAllText(path, string.Concat(lines.Select(l => l + "\n")));
        return RenderStateFile.Read(path);
    }

    private static async Task<JsonObject> CaseAsync(string name, string[] expected, int writtenExpected, int unknownExpected, RenderSessionManifest manifest, IntentRegistry registry, RenderStateFile file)
    {
        var plan = RenderReceiptImporter.Plan(manifest, registry, file);
        await using var host = await ServerTestHost.StartAsync(worker: false);
        await RenderReceiptImporter.ImportAsync(plan, async e => (await host.PostAsync(Events, e)).Status);
        var written = await host.CountAsync("SELECT count(*) FROM events WHERE event_id LIKE 'evt-ready-%'");
        var reported = plan.FileReasons.Concat(plan.RefusedRows.Select(r => r.Reason)).Concat(plan.Unknown.Select(u => u.Reason)).Where(r => r != RenderSealReason.FileRefused).Distinct().Order(StringComparer.Ordinal).ToArray();
        var same = expected.All(reported.Contains) && written == writtenExpected && plan.Unknown.Count == unknownExpected;
        return new JsonObject
        {
            ["case"] = name, ["expectedReasons"] = Strings(expected), ["reportedReasons"] = Strings(reported), ["receiptsExpected"] = writtenExpected, ["receiptsWritten"] = written,
            ["unknownExpected"] = unknownExpected, ["unknown"] = plan.Unknown.Count, ["refusedRows"] = plan.RefusedRows.Count, ["sameAsExpected"] = same,
        };
    }

    private static JsonArray Strings(IEnumerable<string> values) => new([.. values.Select(v => (JsonNode)JsonValue.Create(v))]);

    private static async Task<JsonArray> Group3Async(Run healthy, Run killed, Run v1, string restartDir, Run previous)
    {
        const int K = 2;
        var cases = new JsonArray();
        var reg = healthy.Registry;
        var lines = healthy.Lines;
        var paths = new List<string>();
        RenderStateFile V(List<string> l)
        {
            var f = Temp(l, out var p);
            paths.Add(p);
            return f;
        }
        RenderSessionManifest Sealed(RenderStateFile f) => new(reg.SessionId, reg.RendererContextId, f.End is null ? RenderSessionManifest.Unfinished : RenderSessionManifest.Closed, reg.Intents.Count, f.PreSolveRows.Count, f.FileSha256, true);
        var other = new string('0', 32);
        var restartRegistry = IntentRegistry.Read(Path.Combine(restartDir, "registry.jsonl"));

        cases.Add(await CaseAsync("S1 no end record", [RenderSealReason.EndRecordMissing], 0, 11, killed.Manifest, killed.Registry, killed.File_));
        var truncated = V(RenderFileVariants.Truncated(lines));
        cases.Add(await CaseAsync("S2a truncated", [RenderSealReason.EndCountMismatch], 0, 11, Sealed(truncated), reg, truncated));
        var altered = V(RenderFileVariants.Altered(lines, K));
        cases.Add(await CaseAsync("S2b altered", [RenderSealReason.EndDigestMismatch], 0, 11, Sealed(altered), reg, altered));
        cases.Add(await CaseAsync("S2c altered after sealing", [RenderSealReason.FileDigestMismatch], 0, 11, healthy.Manifest, reg, V(RenderFileVariants.Reend(RenderFileVariants.Altered(lines, K)))));
        cases.Add(await CaseAsync("S3 old format", [RenderSealReason.NotSchemaV2], 0, 11, v1.Manifest, v1.Registry, v1.File_));
        cases.Add(await CaseAsync("S4a other renderer context", [RenderSealReason.RendererContextMismatch], 0, 11, healthy.Manifest with { RendererContextId = other }, reg, healthy.File_));
        cases.Add(await CaseAsync("S4b other session", [RenderSealReason.SessionMismatch], 0, 11, healthy.Manifest with { SessionId = "p1c-other" }, reg with { SessionId = "p1c-other" }, healthy.File_));
        cases.Add(await CaseAsync("S5a restart, first instance", [RenderSealReason.EndRecordMissing], 0, 11,
            RenderSessionManifest.Parse(File.ReadAllText(Path.Combine(restartDir, "manifest.json"))), restartRegistry, RenderStateFile.Read(Path.Combine(restartDir, "client", "aijade-render-state.jsonl"))));
        cases.Add(await CaseAsync("S5b restart, second instance", [RenderSealReason.RendererContextMismatch], 0, 11,
            RenderSessionManifest.Parse(File.ReadAllText(Path.Combine(restartDir, "manifest-2.json"))), restartRegistry, RenderStateFile.Read(Path.Combine(restartDir, "client2", "aijade-render-state.jsonl"))));
        cases.Add(await CaseAsync("S6 earlier session", [RenderSealReason.SessionMismatch, RenderSealReason.RendererContextMismatch], 0, 11, healthy.Manifest, reg, previous.File_));
        var unregistered = V(RenderFileVariants.Reend(RenderFileVariants.TraceReplaced(lines, K, "pi_unregistered")));
        cases.Add(await CaseAsync("S7 unregistered trace", [RenderSealReason.TraceNotRegistered, RenderSealReason.NoRow], 10, 1, Sealed(unregistered), reg, unregistered));
        var noRow = V(RenderFileVariants.Reend(RenderFileVariants.RowRemoved(lines, K)));
        cases.Add(await CaseAsync("S8 intent with no row", [RenderSealReason.NoRow], 10, 1, Sealed(noRow), reg, noRow));
        var badHash = V(RenderFileVariants.Reend(RenderFileVariants.Altered(lines, K)));
        cases.Add(await CaseAsync("S9 hash does not recompute", [RenderSealReason.RendererHashMismatch], 10, 1, Sealed(badHash), reg, badHash));
        var two = V(RenderFileVariants.Reend(RenderFileVariants.TraceAdded(lines, K, reg.Intents[K + 1].IntentId)));
        cases.Add(await CaseAsync("S10 two intents in a row", [RenderSealReason.TwoIntentsInRow], 9, 2, Sealed(two), reg, two));
        cases.Add(await CaseAsync("S11 manifest not complete", [RenderSealReason.ManifestNotComplete], 0, 11, healthy.Manifest with { Complete = false }, reg, healthy.File_));

        var plan = RenderReceiptImporter.Plan(healthy.Manifest, reg, healthy.File_);
        {
            await using var host = await ServerTestHost.StartAsync(worker: false);
            await RenderReceiptImporter.ImportAsync(plan, async e => (await host.PostAsync(Events, e)).Status);
            var first = await host.CountAsync("SELECT count(*) FROM events");
            var firstReceipts = await host.CountAsync("SELECT count(*) FROM events WHERE event_id LIKE 'evt-ready-%'");
            await RenderReceiptImporter.ImportAsync(plan, async e => (await host.PostAsync(Events, e)).Status);
            var second = await host.CountAsync("SELECT count(*) FROM events");
            cases.Add(new JsonObject
            {
                ["case"] = "I1 imported twice", ["receiptsExpected"] = 11, ["receiptsWritten"] = firstReceipts, ["eventsAfterFirst"] = first, ["eventsAfterSecond"] = second,
                ["sameAsExpected"] = firstReceipts == 11 && first == 22 && second == first,
            });
        }
        {
            await using var host = await ServerTestHost.StartAsync(worker: false);
            var posts = 0;
            var stopped = false;
            try
            {
                await RenderReceiptImporter.ImportAsync(plan, async e =>
                {
                    if (++posts > 9)
                        throw new OperationCanceledException("stopped part-way");
                    return (await host.PostAsync(Events, e)).Status;
                });
            }
            catch (OperationCanceledException)
            {
                stopped = true;
            }
            var part = await host.CountAsync("SELECT count(*) FROM events");
            await RenderReceiptImporter.ImportAsync(plan, async e => (await host.PostAsync(Events, e)).Status);
            var whole = await host.CountAsync("SELECT count(*) FROM events");
            var receipts = await host.CountAsync("SELECT count(*) FROM events WHERE event_id LIKE 'evt-ready-%'");
            var distinct = await host.CountAsync("SELECT count(DISTINCT event_id) FROM events");
            cases.Add(new JsonObject
            {
                ["case"] = "I2 stopped part-way", ["receiptsExpected"] = 11, ["receiptsWritten"] = receipts, ["eventsWhenStopped"] = part, ["eventsAfterRerun"] = whole,
                ["sameAsExpected"] = stopped && part == 9 && whole == 22 && receipts == 11 && distinct == 22,
            });
        }
        foreach (var p in paths)
            File.Delete(p);
        return cases;
    }

    private static string Normalize(string line) => Regex.Replace(line, @"\s*\((got )?[^()]*\)\s*$", "").TrimEnd();

    /// <summary>The drift matrix's seven case groups on the receipt topic, with the client's receipts as the valid payload, as assertion lines the matrix's own wording.</summary>
    private static async Task<JsonObject> Group1Async(Run healthy, string golden)
    {
        var plan = RenderReceiptImporter.Plan(healthy.Manifest, healthy.Registry, healthy.File_);
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var log = new List<string>();
        const string T = AijadeEvents.LpmRenderReady;
        void Check(bool ok, string message) => log.Add($"{(ok ? "ok  " : "FAIL")} {message}");
        async Task<(long Events, long Traces)> Counts() => (await host.CountAsync("SELECT count(*) FROM events"), await host.CountAsync("SELECT count(*) FROM render_traces"));

        async Task Positive(string label, ReceiptEvents r, Func<JsonObject, JsonObject> change)
        {
            await host.PostAsync(Events, r.Request);
            var env = change((JsonObject)r.Receipt.DeepClone());
            var accepted = AijadeEvents.IsValid(env);
            Check(accepted, $"[kernel] {T} / {label}: valid payload accepted");
            if (accepted)
            {
                try
                {
                    AijadeEvents.AssertV10RequiredFields(env);
                    Check(true, $"[kernel] {T} / {label}: v10 envelope fields present");
                }
                catch (Exception e) when (e is InvalidOperationException or ArgumentException)
                {
                    Check(false, $"[kernel] {T} / {label}: assertV10RequiredFields threw on the valid fixture");
                }
            }
            var res = await host.PostAsync(Events, env);
            Check(res.Status == 201, $"[http] {T} / {label}: valid payload -> 201 (got {res.Status})");
        }
        await Positive("valid payload", plan.Receipts[0], e => e);
        await Positive("asset_version_hash absent (optional per kernel)", plan.Receipts[1], e =>
        {
            e["payload"]!.AsObject().Remove("asset_version_hash");
            return e;
        });
        (string Name, Action<JsonObject> Change)[] negatives =
        [
            ("missing render_ref", p => p.Remove("render_ref")),
            ("blank render_ref", p => p["render_ref"] = ""),
            ("blank applied_params_hash", p => p["applied_params_hash"] = ""),
            ("blank asset_version_hash", p => p["asset_version_hash"] = ""),
            ("unknown field", p => p["surprise_unknown_field"] = "x"),
        ];
        for (var i = 0; i < negatives.Length; i++)
        {
            var env = (JsonObject)plan.Receipts[2 + i].Receipt.DeepClone();
            negatives[i].Change(env["payload"]!.AsObject());
            var before = await Counts();
            var res = await host.PostAsync(Events, env);
            var after = await Counts();
            Check(res.Status == 400, $"[http] {T} / {negatives[i].Name}: must be 400 (got {res.Status})");
            Check(!AijadeEvents.IsValid(env), $"[kernel] {T} / {negatives[i].Name}: kernel must reject too");
            Check(after.Events == before.Events, $"[no-write] {T} / {negatives[i].Name}: events unchanged ({before.Events} -> {after.Events})");
            Check(after.Traces == before.Traces, $"[no-write] {T} / {negatives[i].Name}: render_traces unchanged ({before.Traces} -> {after.Traces})");
        }
        var recorded = File.ReadAllLines(golden).Where(l => l.Contains($"{T} / ", StringComparison.Ordinal)).Select(Normalize).ToList();
        var got = log.Select(Normalize).ToList();
        return new JsonObject
        {
            ["assertions"] = got.Count, ["recorded"] = recorded.Count, ["same"] = got.Intersect(recorded, StringComparer.Ordinal).Count(),
            ["different"] = Strings(got.Except(recorded, StringComparer.Ordinal).Concat(recorded.Except(got, StringComparer.Ordinal))),
        };
    }

    /// <summary>The honest proposal and the five tampered ones of AdmissionChecksTests, against traces built from the client's receipts.</summary>
    private static async Task<JsonArray> Group2Async(Run healthy)
    {
        var ct = TestContext.Current.CancellationToken;
        var plan = RenderReceiptImporter.Plan(healthy.Manifest, healthy.Registry, healthy.File_);
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var events = host.App.Services.GetRequiredService<V9EventService>();
        foreach (var r in plan.Receipts.Take(plan.Receipts.Count - 1))
        {
            await host.PostAsync(Events, r.Request);
            await host.PostAsync(Events, r.Receipt);
        }
        var unpaired = plan.Receipts[^1];
        await host.PostAsync(Events, unpaired.Receipt);
        var honest = plan.Receipts[0];
        var session = healthy.Registry.SessionId;
        JsonObject Proposal(string? renderRef = null, string? applied = null, string? asset = null) => new()
        {
            ["session_id"] = session, ["render_ref"] = renderRef ?? honest.RenderRef, ["applied_params_hash"] = applied ?? honest.AppliedParamsHash, ["asset_version_hash"] = asset ?? honest.AssetVersionHash,
        };
        (string Name, string Expected, string Id, JsonObject Payload)[] cases =
        [
            ("honest proposal", "admitted", "p0", Proposal()),
            ("reference to a render that does not exist", "render_ref_not_found", "p1", Proposal(renderRef: "render-nowhere")),
            ("reference to an unpaired trace (no request-side intent)", "intent_ref_missing", "p2", Proposal(unpaired.RenderRef, unpaired.AppliedParamsHash, unpaired.AssetVersionHash)),
            ("tampered parameter fingerprint", "applied_params_hash_mismatch", "p3", Proposal(applied: "applied-forged")),
            ("tampered asset version", "asset_version_hash_mismatch", "p4", Proposal(asset: "asset-forged")),
            ("self-reference (render_ref = own trace id)", "self_reference", "p5", Proposal(renderRef: "trace-p5")),
        ];
        var results = new JsonArray();
        foreach (var (name, expected, id, payload) in cases)
        {
            var env = new JsonObject
            {
                ["event_id"] = $"evt-{id}", ["trace_id"] = $"trace-{id}", ["correlation_id"] = $"corr-{id}", ["timestamp"] = 1_760_000_000_000L, ["producer"] = "admission-check", ["origin_device"] = "test-host",
                ["privacy_level"] = 1, ["evidence_refs"] = new JsonArray(), ["causal_context_refs"] = new JsonArray(), ["risk_score"] = 0.1, ["idempotency_key"] = $"idem-{id}", ["replay_mode"] = "live",
                ["risk_level"] = "low", ["topic"] = "aijade.learning.proposed.shadow_params", ["payload"] = payload,
            };
            string got;
            try
            {
                await events.AppendEventAsync(V9EventInput.FromEnvelope(env, payload), ct);
                got = "admitted";
            }
            catch (RenderTraceContractException e)
            {
                got = WireName.Of(e.Reason);
            }
            var written = await host.CountAsync("SELECT count(*) FROM events WHERE event_id = $1", $"evt-{id}");
            results.Add(new JsonObject
            {
                ["case"] = name, ["recorded"] = expected, ["got"] = got, ["eventsWritten"] = written,
                ["sameAsRecorded"] = got == expected && written == (expected == "admitted" ? 1 : 0),
            });
        }
        return results;
    }

    private static JsonObject Denominators(IntentRegistry registry, RenderSessionManifest manifest, RenderStateFile file)
    {
        var plan = RenderReceiptImporter.Plan(manifest, registry, file);
        JsonObject Tally(IEnumerable<string> reasons)
        {
            var o = new JsonObject();
            foreach (var g in reasons.GroupBy(r => r, StringComparer.Ordinal))
                o[g.Key] = g.Count();
            return o;
        }
        int Sum(string field) => file.PreSolveRows.Sum(r => r[field]?.AsArray().Count ?? 0);
        return new JsonObject
        {
            ["session"] = registry.SessionId, ["registered"] = registry.Intents.Count, ["preSolveRows"] = file.PreSolveRows.Count, ["postSolveRows"] = file.PostSolveRows,
            ["fileReasons"] = Strings(plan.FileReasons), ["receipts"] = plan.Receipts.Count, ["unknown"] = plan.Unknown.Count, ["unknownReasons"] = Tally(plan.Unknown.Select(u => u.Reason)),
            ["refusedRows"] = plan.RefusedRows.Count, ["missingKeys"] = Sum("missing_keys"), ["unmapped"] = Sum("unmapped"), ["conflicts"] = Sum("conflicts"),
        };
    }

    private static JsonObject Qualification(Run healthy)
    {
        var f = healthy.File_;
        var plan = RenderReceiptImporter.Plan(healthy.Manifest, healthy.Registry, f);
        var hashes = f.PreSolveRows.Count(r => RenderStateReceipts.RendererHash(RenderStateFile.AppliedOf(r)) == r["applied_params_hash"]?.GetValue<string>());
        return new JsonObject
        {
            ["schemaV2"] = f.Header?["schema"]?.GetValue<string>() == RenderStateFile.SchemaV2,
            ["endRecordVerifies"] = f.End is not null && f.End["lines"]?.GetValue<long>() == f.LinesBeforeLast && f.End["sha256"]?.GetValue<string>() == f.DigestBeforeLast,
            ["rendererHashesRecompute"] = hashes, ["preSolveRows"] = f.PreSolveRows.Count,
            ["registeredIntents"] = healthy.Registry.Intents.Count, ["intentsWithRow"] = healthy.Registry.Intents.Count - plan.Unknown.Count(u => u.Reason == RenderSealReason.NoRow),
            ["rowsNamingTwoIntents"] = plan.RefusedRows.Count(r => r.Reason == RenderSealReason.TwoIntentsInRow),
            ["pmxSha256"] = f.Header?["pmx_sha256"]?.GetValue<string>(), ["clipSha256"] = f.Header?["initial_clip_sha256"]?.GetValue<string>(), ["behaviorPlanSha256"] = f.Header?["behavior_plan_sha256"]?.GetValue<string>(),
        };
    }

    /// <summary>Groups 1 to 3 and the denominators for every round, written to {AIJADE_EXPERIMENT_DIR}/external-renderer-cases.json.</summary>
    [Fact]
    public async Task Cases_on_client_receipts()
    {
        if (Env("AIJADE_P1C_ROUNDS_DIR") is not { } rounds)
        {
            Assert.Skip("AIJADE_P1C_ROUNDS_DIR is not set");
            return;
        }
        var golden = Env("AIJADE_P1C_GOLDEN")!;
        var dirs = Directory.GetDirectories(rounds, "r*").Order(StringComparer.Ordinal).ToList();
        var results = new JsonArray();
        for (var i = 0; i < dirs.Count; i++)
        {
            string Part(int round, string name) => Path.Combine(dirs[round], name);
            var healthy = Load(Part(i, "healthy"));
            var killed = Load(Part(i, "killed"));
            var v1 = Load(Part(i, "v1"));
            var restart = Load(Part(i, "restart"));
            var previous = Load(Part((i + dirs.Count - 1) % dirs.Count, "healthy"));
            var restartSecond = RenderSessionManifest.Parse(File.ReadAllText(Part(i, Path.Combine("restart", "manifest-2.json"))));
            results.Add(new JsonObject
            {
                ["round"] = Path.GetFileName(dirs[i]), ["qualification"] = Qualification(healthy),
                ["sessions"] = new JsonArray(
                    Denominators(healthy.Registry, healthy.Manifest, healthy.File_), Denominators(killed.Registry, killed.Manifest, killed.File_), Denominators(v1.Registry, v1.Manifest, v1.File_),
                    Denominators(restart.Registry, restart.Manifest, restart.File_),
                    Denominators(restart.Registry, restartSecond, RenderStateFile.Read(Part(i, Path.Combine("restart", "client2", "aijade-render-state.jsonl"))))),
                ["group1"] = await Group1Async(healthy, golden), ["group2"] = await Group2Async(healthy),
                ["group3"] = await Group3Async(healthy, killed, v1, Part(i, "restart"), previous),
            });
        }
        var target = Path.Combine(Env("AIJADE_EXPERIMENT_DIR")!, "external-renderer-cases.json");
        await File.WriteAllTextAsync(target, new JsonObject { ["rounds"] = results }.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true }) + "\n", TestContext.Current.CancellationToken);
    }
}
