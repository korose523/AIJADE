using System.Text.Json.Nodes;

using Aijade.Research.RqC;

namespace Aijade.Tests;

/// <summary>The RQ-C runner must write the recorded artifacts (golden: --trials 4, mock backend).</summary>
public class RqcCliTests
{
    private static string GoldenDir => Path.Combine(AppContext.BaseDirectory, "Golden", "rqc-cli");

    [Fact]
    public async Task Saved_candidates_line_up_with_the_steps_and_leave_the_artifacts_unchanged()
    {
        var outRoot = Path.Combine(Path.GetTempPath(), $"rqc-cand-{Guid.NewGuid():N}");
        try
        {
            var cfg = RqcCliConfig.Parse(["--trials", "2", "--out", outRoot, "--save-candidates"]);
            Assert.Equal(RqcCliConfig.Parse(["--trials", "2", "--out", outRoot]).Fingerprint(), cfg.Fingerprint());
            var (outDir, _) = await RqcRunner.RunAsync(cfg, gitHash: "test", ct: TestContext.Current.CancellationToken);
            var steps = await File.ReadAllLinesAsync(Path.Combine(outDir, "trials.jsonl"), TestContext.Current.CancellationToken);
            var candidates = (await File.ReadAllLinesAsync(Path.Combine(outDir, "candidates.jsonl"), TestContext.Current.CancellationToken))
                .Select(l => JsonNode.Parse(l)!.AsObject()).ToList();
            Assert.Equal(steps.Length, candidates.Count);
            for (var i = 0; i < steps.Length; i++)
            {
                var step = JsonNode.Parse(steps[i])!;
                Assert.Equal(i, candidates[i]["step"]!.GetValue<int>());
                Assert.Equal(step["skillId"]!.GetValue<string>(), candidates[i]["skillId"]!.GetValue<string>());
                Assert.Equal(step["execOk"]!.GetValue<bool>(), candidates[i]["execOk"]!.GetValue<bool>());
                Assert.False(string.IsNullOrEmpty(candidates[i]["code"]?.GetValue<string>()));
                // A generation is recorded exactly when the step generated (rather than reused) its skill.
                Assert.Equal(step["reused"]!.GetValue<bool>(), candidates[i]["generation"] is null);
            }
        }
        finally
        {
            if (Directory.Exists(outRoot))
                Directory.Delete(outRoot, true);
        }
    }

    [Fact]
    public async Task An_interrupted_run_resumes_by_replaying_its_recorded_generations()
    {
        var root = Path.Combine(Path.GetTempPath(), $"rqc-resume-{Guid.NewGuid():N}");
        try
        {
            var ct = TestContext.Current.CancellationToken;
            var (full, fullSummary) = await RqcRunner.RunAsync(RqcCliConfig.Parse(["--trials", "2", "--out", Path.Combine(root, "a"), "--save-candidates"]), gitHash: "test", ct: ct);
            // an "interrupted" copy: the first 100 steps of the run
            var cut = Path.Combine(root, "cut");
            Directory.CreateDirectory(cut);
            foreach (var name in new[] { "trials.jsonl", "candidates.jsonl" })
                await File.WriteAllLinesAsync(Path.Combine(cut, name), (await File.ReadAllLinesAsync(Path.Combine(full, name), ct)).Take(100), ct);
            var (resumed, summary) = await RqcRunner.RunAsync(
                RqcCliConfig.Parse(["--trials", "2", "--out", Path.Combine(root, "b"), "--save-candidates", "--resume-from", Path.Combine(cut, "candidates.jsonl")]), gitHash: "test", ct: ct);
            Assert.Equal(100, summary["resumed"]!["replayedSteps"]!.GetValue<int>());
            Assert.Contains(summary["preregistrationDeviation"]!.AsArray(), d => d!.GetValue<string>().StartsWith("resumed: steps 0–99", StringComparison.Ordinal));
            Assert.Equal(fullSummary["fingerprint"]!.GetValue<string>(), summary["fingerprint"]!.GetValue<string>());
            // the replayed prefix equals the interrupted run (the runner also checks this step by step and would have thrown)
            static string Key(string line)
            {
                var o = JsonNode.Parse(line)!.AsObject();
                o.Remove("durationMs");
                return o.ToJsonString();
            }
            var a = (await File.ReadAllLinesAsync(Path.Combine(full, "trials.jsonl"), ct)).Take(100).Select(Key);
            var b = (await File.ReadAllLinesAsync(Path.Combine(resumed, "trials.jsonl"), ct)).Take(100).Select(Key);
            Assert.Equal(a, b);
            // a resume source that does not match the configuration is refused
            await Assert.ThrowsAsync<InvalidOperationException>(() => RqcRunner.RunAsync(
                RqcCliConfig.Parse(["--trials", "2", "--seed", "7", "--out", Path.Combine(root, "c"), "--resume-from", Path.Combine(cut, "candidates.jsonl")]), gitHash: "test", ct: ct));

            // a killed run: both files end in a half-written line, and trials.jsonl stops earlier than candidates.jsonl
            var killed = Path.Combine(root, "killed");
            Directory.CreateDirectory(killed);
            string Cut(string name, int complete)
            {
                var lines = File.ReadAllLines(Path.Combine(full, name));
                return string.Concat(lines.Take(complete).Select(l => l + "\n")) + lines[complete][..(lines[complete].Length / 2)];
            }
            await File.WriteAllTextAsync(Path.Combine(killed, "candidates.jsonl"), Cut("candidates.jsonl", 100), ct);
            await File.WriteAllTextAsync(Path.Combine(killed, "trials.jsonl"), Cut("trials.jsonl", 90), ct);
            var (_, fromKilled) = await RqcRunner.RunAsync(
                RqcCliConfig.Parse(["--trials", "2", "--out", Path.Combine(root, "d"), "--save-candidates", "--resume-from", Path.Combine(killed, "candidates.jsonl")]), gitHash: "test", ct: ct);
            Assert.Equal(90, fromKilled["resumed"]!["replayedSteps"]!.GetValue<int>());
            Assert.Equal(fullSummary["nExecutions"]!.ToJsonString(), fromKilled["nExecutions"]!.ToJsonString());
            // a malformed line before the end is still refused
            var broken = Path.Combine(root, "broken");
            Directory.CreateDirectory(broken);
            var cand = File.ReadAllLines(Path.Combine(full, "candidates.jsonl")).Take(100).ToArray();
            cand[50] = cand[50][..10];
            await File.WriteAllLinesAsync(Path.Combine(broken, "candidates.jsonl"), cand, ct);
            File.Copy(Path.Combine(cut, "trials.jsonl"), Path.Combine(broken, "trials.jsonl"));
            await Assert.ThrowsAnyAsync<System.Text.Json.JsonException>(() => RqcRunner.RunAsync(
                RqcCliConfig.Parse(["--trials", "2", "--out", Path.Combine(root, "e"), "--resume-from", Path.Combine(broken, "candidates.jsonl")]), gitHash: "test", ct: ct));
        }
        finally
        {
            if (Directory.Exists(root))
                Directory.Delete(root, true);
        }
    }

    [Fact]
    public async Task The_inert_negative_control_is_flagged_as_a_constructive_zero()
    {
        var root = Path.Combine(Path.GetTempPath(), $"rqc-inert-{Guid.NewGuid():N}");
        try
        {
            var cfg = RqcCliConfig.Parse(["--trials", "4", "--out", root, "--inert"]);
            Assert.EndsWith("-INERT", cfg.RunId, StringComparison.Ordinal);
            Assert.NotEqual(RqcCliConfig.Parse(["--trials", "4", "--out", root]).Fingerprint(), cfg.Fingerprint());
            var (_, summary) = await RqcRunner.RunAsync(cfg, gitHash: "test", ct: TestContext.Current.CancellationToken);
            Assert.False(summary["degeneracy"]!["manipulationReachable"]!.GetValue<bool>());
            Assert.True(summary["degeneracy"]!["allCellsIdenticalPrecision"]!.GetValue<bool>(), summary["degeneracy"]!.ToJsonString());
            Assert.Contains(summary["preregistrationDeviation"]!.AsArray(), d => d!.GetValue<string>().StartsWith("negative control", StringComparison.Ordinal));
        }
        finally
        {
            if (Directory.Exists(root))
                Directory.Delete(root, true);
        }
    }

    [Fact]
    public async Task Artifacts_match_the_original_cli()
    {
        var expectedSummary = await File.ReadAllTextAsync(Path.Combine(GoldenDir, "summary.json"), TestContext.Current.CancellationToken);
        var gitHash = JsonNode.Parse(expectedSummary)!["gitHash"]!.GetValue<string>();
        var outRoot = Path.Combine(Path.GetTempPath(), $"rqc-{Guid.NewGuid():N}");
        try
        {
            var cfg = RqcCliConfig.Parse(["--trials", "4", "--out", outRoot]);
            var (outDir, _) = await RqcRunner.RunAsync(cfg, gitHash: gitHash, ct: TestContext.Current.CancellationToken);
            Assert.EndsWith("rq-c-s42-mock-t4-r5", outDir, StringComparison.Ordinal);
            // Structure, key order, strings and integers must be identical; doubles may differ only in the last ulp, where
            // V8's and .NET's exp / log round differently (e.g. the power figures).
            var actualSummary = await File.ReadAllTextAsync(Path.Combine(outDir, "summary.json"), TestContext.Current.CancellationToken);
            AssertJsonClose(JsonNode.Parse(expectedSummary), JsonNode.Parse(actualSummary), "$");
            // Durations are wall-clock; every other field of every step must be identical.
            var actualSteps = (await File.ReadAllLinesAsync(Path.Combine(outDir, "trials.jsonl"), TestContext.Current.CancellationToken))
                .Select(l => { var o = JsonNode.Parse(l)!.AsObject(); o["durationMs"] = 0; return o.ToJsonString(); });
            var expectedSteps = (await File.ReadAllLinesAsync(Path.Combine(GoldenDir, "trials.jsonl"), TestContext.Current.CancellationToken))
                .Select(l => JsonNode.Parse(l)!.ToJsonString());
            Assert.Equal(expectedSteps, actualSteps);
            await Assert.ThrowsAsync<IOException>(() => RqcRunner.RunAsync(cfg, gitHash: gitHash, ct: TestContext.Current.CancellationToken));
        }
        finally
        {
            if (Directory.Exists(outRoot))
                Directory.Delete(outRoot, true);
        }
    }

    private static void AssertJsonClose(JsonNode? e, JsonNode? a, string path)
    {
        switch (e)
        {
            case JsonObject eo:
                var ao = Assert.IsType<JsonObject>(a);
                Assert.Equal(eo.Select(kv => kv.Key), ao.Select(kv => kv.Key));
                foreach (var (k, v) in eo)
                    AssertJsonClose(v, ao[k], $"{path}.{k}");
                break;
            case JsonArray ea:
                var aa = Assert.IsType<JsonArray>(a);
                Assert.Equal(ea.Count, aa.Count);
                for (var i = 0; i < ea.Count; i++)
                    AssertJsonClose(ea[i], aa[i], $"{path}[{i}]");
                break;
            case JsonValue ev when ev.GetValueKind() == System.Text.Json.JsonValueKind.Number:
                var x = ev.GetValue<double>();
                var y = a!.GetValue<double>();
                Assert.True(Math.Abs(x - y) <= 1e-12 * Math.Max(1, Math.Abs(x)), $"{path}: {x} vs {y}");
                break;
            default:
                Assert.Equal(e?.ToJsonString(), a?.ToJsonString());
                break;
        }
    }

    [Fact]
    public void Fingerprint_and_sampling_seed_reproduce_the_recorded_live_run()
    {
        var cfg = RqcCliConfig.Parse(["--backend", "ollama", "--model", "qwen2.5-coder:1.5b"]);
        var archived = JsonNode.Parse(File.ReadAllText(Path.Combine(RqcReanalysisTests.RunsDirectory(), "rq-c-s42-ollama-t30-r5", "summary.json")))!;
        Assert.Equal(archived["fingerprint"]!.GetValue<string>(), cfg.Fingerprint());
        Assert.Equal(archived["sampling"]!["seed"]!.GetValue<uint>(), cfg.SamplingSeed);
        Assert.Equal("rq-c-s42-ollama-t30-r5", cfg.RunId);
        Assert.Throws<ArgumentException>(() => RqcCliConfig.Parse(["--backend", "ollama"]));
        Assert.Throws<ArgumentException>(() => RqcCliConfig.Parse(["--bogus"]));
        Assert.Throws<ArgumentException>(() => RqcCliConfig.Parse(["--trials"]));
    }

    private sealed class FakeOllama : HttpMessageHandler
    {
        public List<string> ChatPrompts { get; } = [];

        public List<double> Temperatures { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (request.RequestUri!.AbsolutePath == "/api/version")
                return new HttpResponseMessage(System.Net.HttpStatusCode.OK) { Content = new StringContent("{\"version\":\"0.0-test\"}") };
            if (request.RequestUri.AbsolutePath == "/api/tags")
                return new HttpResponseMessage(System.Net.HttpStatusCode.OK) { Content = new StringContent("{\"models\":[{\"name\":\"other:latest\",\"digest\":\"0000\"},{\"name\":\"m:latest\",\"digest\":\"abc123\"}]}") };
            var body = JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!;
            ChatPrompts.Add(body["messages"]![0]!["content"]!.GetValue<string>());
            Temperatures.Add(body["options"]!["temperature"]!.GetValue<double>());
            var reply = new JsonObject { ["message"] = new JsonObject { ["content"] = "PASS\n```js\nfunction solve(x) { return x; }\n```" } };
            return new HttpResponseMessage(System.Net.HttpStatusCode.OK) { Content = new StringContent(reply.ToJsonString()) };
        }
    }

    [Fact]
    public async Task A_sampled_run_is_a_different_experiment_and_says_it_deviates_from_the_preregistration()
    {
        var ct = TestContext.Current.CancellationToken;
        var outRoot = Path.Combine(Path.GetTempPath(), $"rqc-temp-{Guid.NewGuid():N}");
        try
        {
            string[] args = ["--backend", "ollama", "--model", "m", "--trials", "1", "--rounds", "1", "--tasks", "1", "--out", outRoot];
            var greedy = RqcCliConfig.Parse(args);
            var sampled = RqcCliConfig.Parse([.. args, "--temperature", "0.4"]);
            Assert.Equal(RqcCliConfig.Parse([.. args, "--temperature", "0"]).Fingerprint(), greedy.Fingerprint()); // T=0 changes nothing
            Assert.NotEqual(greedy.Fingerprint(), sampled.Fingerprint());
            Assert.EndsWith("-T0.4", sampled.RunId, StringComparison.Ordinal);
            Assert.Throws<ArgumentException>(() => RqcCliConfig.Parse(["--temperature", "0.4"])); // mock backend
            Assert.Throws<ArgumentException>(() => RqcCliConfig.Parse([.. args, "--temperature", "3"]));

            using var handler = new FakeOllama();
            using var http = new HttpClient(handler);
            var (_, summary) = await RqcRunner.RunAsync(sampled, http, gitHash: "test", ct: ct);
            Assert.All(handler.Temperatures, t => Assert.Equal(0.4, t));
            Assert.Equal(0.4, summary["sampling"]!["temperature"]!.GetValue<double>());
            Assert.Contains(summary["preregistrationDeviation"]!.AsArray(), d => d!.GetValue<string>() == "temperature: run=0.4 preregistered=0");
        }
        finally
        {
            if (Directory.Exists(outRoot))
                Directory.Delete(outRoot, true);
        }
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task Ollama_runs_send_one_discarded_warm_up_request_first(bool warmUp)
    {
        var ct = TestContext.Current.CancellationToken;
        var outRoot = Path.Combine(Path.GetTempPath(), $"rqc-warm-{Guid.NewGuid():N}");
        try
        {
            using var handler = new FakeOllama();
            using var http = new HttpClient(handler);
            string[] args = ["--backend", "ollama", "--model", "m", "--trials", "1", "--rounds", "1", "--tasks", "1", "--out", outRoot];
            var cfg = RqcCliConfig.Parse(warmUp ? args : [.. args, "--no-warmup"]);
            var fingerprint = cfg.Fingerprint();
            var (_, summary) = await RqcRunner.RunAsync(cfg, http, gitHash: "test", ct: ct);
            Assert.Equal(warmUp, handler.ChatPrompts[0] == OllamaBackend.WarmUpPrompt);
            Assert.Equal(warmUp ? 1 : 0, handler.ChatPrompts.Count(p => p == OllamaBackend.WarmUpPrompt));
            Assert.Equal(warmUp, summary["sampling"]!["warmUp"]!.GetValue<bool>());
            Assert.Equal("abc123", summary["sampling"]!["modelDigest"]!.GetValue<string>()); // the weights behind the tag
            Assert.Equal(fingerprint, summary["fingerprint"]!.GetValue<string>()); // infrastructure, not part of the fingerprint
            Assert.Equal(fingerprint, RqcCliConfig.Parse([.. args, "--no-warmup"]).Fingerprint());
        }
        finally
        {
            if (Directory.Exists(outRoot))
                Directory.Delete(outRoot, recursive: true);
        }
    }
    private sealed class RepeatAbortOllama(string error) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            Task.FromResult(new HttpResponseMessage(System.Net.HttpStatusCode.InternalServerError) { Content = new StringContent($"{{\"error\":\"{error}\"}}") });
    }

    [Fact]
    public async Task A_reply_the_server_aborts_for_repetition_is_a_failed_answer_not_a_crash()
    {
        var ct = TestContext.Current.CancellationToken;
        var task = Aijade.Research.SkillBench.Bench.Tasks[0];
        using var http = new HttpClient(new RepeatAbortOllama("prediction aborted, token repeat limit reached"));
        var backend = new OllamaBackend(http, "m", "http://fake", seed: 1);
        Assert.Equal(OllamaBackend.AbortedGeneration, await backend.GenerateAsync(task, new GenerateContext(0, null, null, null), ct));
        var verdict = await backend.VerifyAsync(task, "function f(){}", ct);
        Assert.False(verdict.Pass);
        Assert.StartsWith("FAIL", verdict.Rationale, StringComparison.Ordinal);
        Assert.Equal(2, backend.AbortedReplies);
        Assert.False(new Aijade.Research.SkillBench.Sandbox().RunTask(OllamaBackend.AbortedGeneration, task).Ok);
        // any other server error still stops the run
        using var other = new HttpClient(new RepeatAbortOllama("model runner crashed"));
        await Assert.ThrowsAsync<InvalidOperationException>(() => new OllamaBackend(other, "m", "http://fake", seed: 1).GenerateAsync(task, new GenerateContext(0, null, null, null), ct));
    }

    /// <summary>Answers every chat request with a fixed reply and done_reason; records the request bodies.</summary>
    private sealed class DoneReasonOllama(string doneReason) : HttpMessageHandler
    {
        public List<JsonObject> Requests { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Requests.Add(JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!.AsObject());
            var reply = new JsonObject { ["message"] = new JsonObject { ["content"] = "PASS ```js\nfunction f(){}\n```" }, ["done_reason"] = doneReason };
            return new HttpResponseMessage(System.Net.HttpStatusCode.OK) { Content = new StringContent(reply.ToJsonString()) };
        }
    }

    [Fact]
    public async Task A_reply_at_the_token_cap_is_no_answer_and_the_cap_is_off_by_default()
    {
        var ct = TestContext.Current.CancellationToken;
        var task = Aijade.Research.SkillBench.Bench.Tasks[0];
        var ctx = new GenerateContext(0, null, null, null);

        using var capped = new DoneReasonOllama("length");
        using (var http = new HttpClient(capped))
        {
            var backend = new OllamaBackend(http, "m", "http://fake", seed: 1, maxReplyTokens: 4096);
            Assert.Equal(OllamaBackend.LengthLimitedGeneration, await backend.GenerateAsync(task, ctx, ct));
            var verdict = await backend.VerifyAsync(task, "function f(){}", ct);
            Assert.False(verdict.Pass);
            Assert.StartsWith("FAIL", verdict.Rationale, StringComparison.Ordinal);
            Assert.Equal(2, backend.LengthLimitedReplies);
            Assert.Equal(0, backend.AbortedReplies);
            Assert.All(capped.Requests, r => Assert.Equal(4096, r["options"]!["num_predict"]!.GetValue<int>()));
            Assert.False(new Aijade.Research.SkillBench.Sandbox().RunTask(OllamaBackend.LengthLimitedGeneration, task).Ok);
        }

        // without a cap nothing is sent and a "length" stop is an ordinary reply (the pre-registered runs had no cap)
        using var uncapped = new DoneReasonOllama("length");
        using (var http = new HttpClient(uncapped))
        {
            var backend = new OllamaBackend(http, "m", "http://fake", seed: 1);
            Assert.Contains("function f", await backend.GenerateAsync(task, ctx, ct), StringComparison.Ordinal);
            Assert.True((await backend.VerifyAsync(task, "function f(){}", ct)).Pass);
            Assert.Equal(0, backend.LengthLimitedReplies);
            Assert.All(uncapped.Requests, r => Assert.Null(r["options"]!["num_predict"]));
        }

        // the cap is part of the design: it changes the fingerprint, not the run id, and needs the ollama backend
        var plain = RqcCliConfig.Parse(["--backend", "ollama", "--model", "m"]);
        var withCap = RqcCliConfig.Parse(["--backend", "ollama", "--model", "m", "--max-reply-tokens", "4096"]);
        Assert.NotEqual(plain.Fingerprint(), withCap.Fingerprint());
        Assert.Equal(plain.RunId, withCap.RunId);
        Assert.Throws<ArgumentException>(() => RqcCliConfig.Parse(["--max-reply-tokens", "4096"]));
        Assert.Throws<ArgumentException>(() => RqcCliConfig.Parse(["--backend", "ollama", "--model", "m", "--max-reply-tokens", "0"]));
    }

    [Theory]
    [InlineData("PASS: all cases correct", false, true, true, false)]
    [InlineData("  fail - case 2 is wrong", false, false, true, false)]
    [InlineData("Pass.", false, true, true, false)]
    [InlineData("\n* Case 0: PASS\n* Case 1: PASS\n\nOverall verdict: PASS", false, false, false, false)]
    [InlineData("\n* Case 0: PASS\n* Case 1: PASS\n\nOverall verdict: PASS", true, true, false, true)]
    [InlineData("\n* Case 0: PASS\n* Case 1: FAIL\n\nVerdict - FAIL", true, false, false, true)]
    [InlineData("The code returns the correct result, so it passes.", true, false, false, false)]
    [InlineData("PASS, although an earlier draft had verdict: FAIL", true, true, true, false)]
    public void Verifier_replies_are_read_by_the_preregistered_rule_and_the_optional_fallback(string reply, bool fallback, bool pass, bool conforming, bool byFallback)
    {
        Assert.Equal(pass, OllamaBackend.ReadVerdict(reply, fallback, out var c, out var f));
        Assert.Equal(conforming, c);
        Assert.Equal(byFallback, f);
    }

    [Fact]
    public void The_fallback_reads_every_recorded_reply_of_the_earlier_runs_exactly_as_the_preregistered_rule()
    {
        var rqc = Path.Combine(RqcReanalysisTests.RepoRoot(), "experiments", "rq-c");
        var checkedReplies = 0;
        foreach (var run in new[] { Path.Combine("redo", "rq-c-s42-ollama-t30-r5"), Path.Combine("redo", "rq-c-s42-ollama-t30-r5-INERT"), "rq-c-s42-ollama-t30-r5",
                     Path.Combine("sweep-1.5b", "rq-c-s42-ollama-t30-r5-T0.4"), Path.Combine("sweep-1.5b", "rq-c-s42-ollama-t30-r5-T0.8") })
        {
            var path = Path.Combine(rqc, run, "candidates.jsonl");
            if (!File.Exists(path))
                continue;
            foreach (var line in File.ReadLines(path).Where(l => l.Length > 0))
            {
                if (JsonNode.Parse(line)!["selfRationale"]?.GetValue<string>() is not { } reply)
                    continue;
                Assert.Equal(OllamaBackend.ReadVerdict(reply, false, out var conforming, out _), OllamaBackend.ReadVerdict(reply, true, out _, out var byFallback));
                Assert.True(conforming, $"{run}: {reply[..Math.Min(60, reply.Length)]}");
                Assert.False(byFallback);
                checkedReplies++;
            }
        }
        if (checkedReplies == 0)
            Assert.Skip("no recorded RQ-C runs in this checkout");
    }

    /// <summary>Answers every chat request with one fixed reply.</summary>
    private sealed class FixedReplyOllama(string reply) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            Task.FromResult(new HttpResponseMessage(System.Net.HttpStatusCode.OK)
            {
                Content = new StringContent(new JsonObject { ["message"] = new JsonObject { ["content"] = reply }, ["done_reason"] = "stop" }.ToJsonString()),
            });
    }

    [Fact]
    public async Task A_non_conforming_reply_is_counted_and_its_whole_text_kept_for_audit()
    {
        var ct = TestContext.Current.CancellationToken;
        var task = Aijade.Research.SkillBench.Bench.Tasks[0];
        var reply = "\n" + string.Concat(Enumerable.Range(0, 40).Select(i => $"* Case {i}: PASS\n")) + "\nOverall verdict: PASS";
        Assert.True(reply.Length > 280);
        using var strictHttp = new HttpClient(new FixedReplyOllama(reply));
        var strict = new OllamaBackend(strictHttp, "m", "http://fake", seed: 1);
        var v = await strict.VerifyAsync(task, "function f(){}", ct);
        Assert.False(v.Pass);
        Assert.Equal(280, v.Rationale.Length);
        Assert.Equal(reply, v.FullReply);
        Assert.Equal((1, 0), (strict.NonConformingVerdicts, strict.FallbackVerdicts));

        using var lenientHttp = new HttpClient(new FixedReplyOllama(reply));
        var lenient = new OllamaBackend(lenientHttp, "m", "http://fake", seed: 1, verdictFallback: true);
        Assert.True((await lenient.VerifyAsync(task, "function f(){}", ct)).Pass);
        Assert.Equal((1, 1), (lenient.NonConformingVerdicts, lenient.FallbackVerdicts));

        var plain = RqcCliConfig.Parse(["--backend", "ollama", "--model", "m"]);
        var withFallback = RqcCliConfig.Parse(["--backend", "ollama", "--model", "m", "--verdict-fallback"]);
        Assert.NotEqual(plain.Fingerprint(), withFallback.Fingerprint());
        Assert.Equal(plain.RunId, withFallback.RunId);
        Assert.Throws<ArgumentException>(() => RqcCliConfig.Parse(["--verdict-fallback"]));
    }
}
