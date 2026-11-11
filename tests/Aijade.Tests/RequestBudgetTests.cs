using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Research.RqC;
using Aijade.Research.SkillBench;

namespace Aijade.Tests;

public sealed class RequestBudgetTests
{
    [Fact]
    public void Visible_examples_keep_original_indices_and_never_replace_the_oracle()
    {
        using var fixture = new Fixture();
        var task = fixture.Bank.ReadTask("identity");
        var a = Backends.BuildVerifyPrompt(task, "function solve(){return 0;}", [0]);
        var b = Backends.BuildVerifyPromptB(task, "function solve(){return 0;}", [2]);
        Assert.Contains("Only 1 of 3", a, StringComparison.Ordinal);
        Assert.Contains("case 0: args = [0]", a, StringComparison.Ordinal);
        Assert.DoesNotContain("case 1:", a, StringComparison.Ordinal);
        Assert.Contains("  3. [2]", b, StringComparison.Ordinal);
        Assert.Contains("No test inputs are displayed", Backends.BuildVerifyPrompt(task, "", []), StringComparison.Ordinal);
        var actual = new Sandbox().RunTask("function solve(){return 0;}", task);
        Assert.Equal(3, actual.Total);
        Assert.Equal(1, actual.Passed);
        Assert.True(PublicBankCheck.CheckExpectedNoninterference(task, fixture.Bank.ReadReference("identity"), [0]));
        var changed = task with { Tests = task.Tests.Select(test => test with { Expected = "'secret-output'" }).ToArray() };
        Assert.Equal(PromptExposure.Describe(task).InputSha256, PromptExposure.Describe(changed).InputSha256);
        Assert.Equal(a, Backends.BuildVerifyPrompt(changed, "function solve(){return 0;}", [0]));
    }

    [Theory]
    [InlineData("duplicate-index")]
    [InlineData("unsorted-index")]
    [InlineData("out-of-range")]
    [InlineData("excess-cases")]
    [InlineData("missing-task")]
    [InlineData("duplicate-task")]
    [InlineData("changed-input")]
    [InlineData("changed-bank")]
    [InlineData("changed-scenario")]
    public void Exposure_loader_rejects_population_and_identity_changes(string kind)
    {
        using var fixture = new Fixture();
        var data = JsonNode.Parse(File.ReadAllText(fixture.ExposureFile))!;
        var first = data["tasks"]![0]!;
        switch (kind)
        {
            case "duplicate-index": first["selectedCaseIndices"] = new JsonArray(0, 0); break;
            case "unsorted-index": first["selectedCaseIndices"] = new JsonArray(2, 0); break;
            case "out-of-range": first["selectedCaseIndices"] = new JsonArray(3); break;
            case "excess-cases": first["selectedCaseIndices"] = new JsonArray(0, 1, 2, 3); break;
            case "missing-task": data["tasks"]!.AsArray().RemoveAt(0); break;
            case "duplicate-task": data["tasks"]![1]!["taskId"] = "identity"; break;
            case "changed-input": first["inputSha256"] = new string('0', 64); break;
            case "changed-bank": data["bankManifestSha256"] = new string('0', 64); break;
            case "changed-scenario": data["scenario"]!["verificationReplyTokens"] = 512; break;
        }
        File.WriteAllText(fixture.ExposureFile, data.ToJsonString());
        Assert.Throws<InvalidDataException>(() => PromptExposure.Load(fixture.ExposureFile, fixture.Bank));
    }

    [Theory]
    [InlineData("generation", 2048)]
    [InlineData("verification", 3840)]
    [InlineData("warmup", 2048)]
    public async Task Exact_budget_boundary_dispatches_with_the_stage_cap_but_one_extra_token_does_not(string stage, int boundary)
    {
        using var fixture = new Fixture();
        var ct = TestContext.Current.CancellationToken;
        var task = fixture.Bank.ReadTask("identity");
        var handler = new RecordingHandler();
        using var http = new HttpClient(handler);
        var policy = PublicRequestPolicy.Load(fixture.PolicyFile, fixture.Bank);
        using (var budget = new RequestBudget(policy, new Counter(boundary), fixture.Output("fit"), 12))
        {
            var backend = new OllamaBackend(http, policy.Model, requestBudget: budget);
            await CallAsync(backend, task, stage, ct);
            Assert.Equal(1, handler.Calls);
            Assert.Equal(4096, handler.Last!["options"]!["num_ctx"]!.GetValue<int>());
            Assert.Equal(stage == "verification" ? 256 : 2048, handler.Last["options"]!["num_predict"]!.GetValue<int>());
        }
        handler.Calls = 0;
        var folder = fixture.Output("overflow");
        using (var budget = new RequestBudget(policy, new Counter(boundary + 1), folder, 12))
        {
            var backend = new OllamaBackend(http, policy.Model, requestBudget: budget);
            var error = await Assert.ThrowsAsync<RequestBudgetFailure>(() => CallAsync(backend, task, stage, ct));
            Assert.Equal("CONTEXT_OVERFLOW", error.Status);
            Assert.Equal(0, handler.Calls);
            var missing = JsonNode.Parse(File.ReadAllText(Path.Combine(folder, "incomplete-run.json")))!;
            Assert.Null(missing["verdict"]);
            Assert.Equal(12, missing["notCompletedSteps"]!.GetValue<int>());
            Assert.False(File.Exists(Path.Combine(folder, "summary.json")));
            Assert.Contains("rawPrompt", File.ReadAllText(Path.Combine(folder, "requests.jsonl")), StringComparison.Ordinal);
        }
    }

    [Theory]
    [InlineData("wrong-raw-hash", "COUNTER_ERROR", 0)]
    [InlineData("negative-count", "COUNTER_ERROR", 0)]
    [InlineData("disagree", "COUNTER_ERROR", 0)]
    [InlineData("bad-counter-json", "COUNTER_ERROR", 0)]
    [InlineData("reply-length", "REPLY_LENGTH_LIMIT", 1)]
    [InlineData("empty", "EMPTY_RESPONSE", 1)]
    [InlineData("nonconforming", "VERDICT_FORMAT_ERROR", 1)]
    [InlineData("bad-response-json", "RESPONSE_FORMAT_ERROR", 1)]
    [InlineData("http-error", "HTTP_ERROR", 1)]
    public async Task Counter_and_response_failures_leave_a_missing_verdict(string kind, string status, int requests)
    {
        using var fixture = new Fixture();
        var ct = TestContext.Current.CancellationToken;
        var handler = new RecordingHandler { Kind = kind };
        using var http = new HttpClient(handler);
        var policy = PublicRequestPolicy.Load(fixture.PolicyFile, fixture.Bank);
        var folder = fixture.Output("failure");
        using var budget = new RequestBudget(policy, new Counter(100, kind), folder, 12);
        var backend = new OllamaBackend(http, policy.Model, requestBudget: budget);
        var error = await Assert.ThrowsAsync<RequestBudgetFailure>(() => backend.VerifyAsync(fixture.Bank.ReadTask("identity"), "function solve(x){return x;}", ct));
        Assert.Equal(status, error.Status);
        Assert.Equal(requests, handler.Calls);
        Assert.Null(JsonNode.Parse(File.ReadAllText(Path.Combine(folder, "incomplete-run.json")))!["verdict"]);
    }

    [Fact]
    public async Task Normal_runner_binds_the_policy_and_rejects_a_different_resume_before_output()
    {
        using var fixture = new Fixture();
        var ct = TestContext.Current.CancellationToken;
        var cfg = RqcCliConfig.Parse(["--public-bank", fixture.Manifest, "--request-policy", fixture.PolicyFile,
            "--trials", "1", "--rounds", "1", "--tasks", "3", "--save-candidates", "--out", fixture.Output("run")]);
        var (full, summary) = await RqcRunner.RunAsync(cfg, gitHash: "test", ct: ct);
        Assert.Equal(0, summary["requestPolicy"]!["requestsChecked"]!.GetValue<int>());
        var lines = await File.ReadAllLinesAsync(Path.Combine(full, "trials.jsonl"), ct);
        Assert.Equal(12, lines.Length);
        Assert.All(lines.Select(line => JsonNode.Parse(line)!), row => Assert.Equal(cfg.RequestPolicySha256, row["requestPolicySha256"]!.GetValue<string>()));
        var cut = fixture.Output("cut");
        foreach (var name in new[] { "trials.jsonl", "candidates.jsonl" })
            await File.WriteAllLinesAsync(Path.Combine(cut, name), (await File.ReadAllLinesAsync(Path.Combine(full, name), ct)).Take(8), ct);
        var resumed = cfg with { ResumeFrom = Path.Combine(cut, "candidates.jsonl"), Out = fixture.Output("resume") };
        var (resumedDir, resumedSummary) = await RqcRunner.RunAsync(resumed, gitHash: "test", ct: ct);
        Assert.Equal(8, resumedSummary["resumed"]!["replayedSteps"]!.GetValue<int>());
        static IEnumerable<string> Decisions(string file) => File.ReadLines(file).Select(line =>
        {
            var row = JsonNode.Parse(line)!.AsObject();row.Remove("durationMs");return row.ToJsonString();
        });
        Assert.Equal(Decisions(Path.Combine(full, "trials.jsonl")), Decisions(Path.Combine(resumedDir, "trials.jsonl")));
        fixture.RewriteExposure([2]);
        fixture.WritePolicy();
        var different = resumed with { RequestPolicySha256 = null, Out = Path.Combine(fixture.Root, "wrong") };
        await Assert.ThrowsAsync<InvalidDataException>(() => RqcRunner.RunAsync(different, gitHash: "test", ct: ct));
        Assert.False(Directory.Exists(different.Out));
    }

    private static async Task CallAsync(OllamaBackend backend, BenchTask task, string stage, CancellationToken ct)
    {
        if (stage == "warmup")await backend.WarmUpAsync(ct);
        else if (stage == "generation")await backend.GenerateAsync(task, new GenerateContext(0), ct);
        else await backend.VerifyAsync(task, "function solve(x){return x;}", ct);
    }

    private sealed class Counter(int count, string kind = "") : IExactPromptCounter
    {
        public Task<ExactPromptCount> CountAsync(string prompt, CancellationToken cancellationToken = default)
        {
            if (kind == "bad-counter-json")return Task.FromException<ExactPromptCount>(new JsonException("synthetic malformed counter reply"));
            return Task.FromResult(new ExactPromptCount(kind == "negative-count" ? -1 : count,
                kind == "wrong-raw-hash" ? new string('0', 64) : PromptExposure.Hash(prompt), new string('a', 64), new string('b', 64), kind != "disagree"));
        }
        public void Dispose() { }
    }

    private sealed class RecordingHandler : HttpMessageHandler
    {
        public int Calls { get; set; }
        public JsonObject? Last { get; private set; }
        public string Kind { get; init; } = "";
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            Last = JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!.AsObject();
            var reply = Kind switch { "empty" => "", "nonconforming" => "Maybe; cannot decide.", _ => "PASS synthetic response" };
            var raw = Kind == "bad-response-json" ? "not JSON" : JsonSerializer.Serialize(new
            {
                message = new { content = reply }, done_reason = Kind == "reply-length" ? "length" : "stop",
            });
            return new HttpResponseMessage(Kind == "http-error" ? HttpStatusCode.InternalServerError : HttpStatusCode.OK)
            {
                Content = new StringContent(raw, Encoding.UTF8, "application/json"),
            };
        }
    }

    private sealed class Fixture : IDisposable
    {
        private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
        public string Root { get; } = Path.Combine(Path.GetTempPath(), "p2-exposure-" + Guid.NewGuid().ToString("N"));
        public string Manifest => Path.Combine(Root, "manifest.json");
        public string ExposureFile => Path.Combine(Root, "exposure.json");
        public string PolicyFile => Path.Combine(Root, "policy.json");
        public PublicBenchBank Bank { get; }

        public Fixture()
        {
            Directory.CreateDirectory(Root);
            File.WriteAllText(Path.Combine(Root, "runtime.js"), "");
            var entries = new List<PublicBenchEntry>();
            foreach (var id in new[] { "identity", "identity2", "identity3" })
            {
                var cases = new[] { new BenchCase("[0]", "0"), new BenchCase("[1]", "1"), new BenchCase("[2]", "2") };
                File.WriteAllText(Path.Combine(Root, id + ".json"), JsonSerializer.Serialize(new
                {
                    taskId = id, statement = "Return x unchanged.", contract = "Arguments are provided in this order (x).", cases,
                }, Json));
                File.WriteAllText(Path.Combine(Root, id + ".js"), "function solve(x){return x;}");
                entries.Add(new PublicBenchEntry(id, id, id + ".json", PublicBenchBank.FileSha256(Path.Combine(Root, id + ".json")),
                    id + ".js", PublicBenchBank.FileSha256(Path.Combine(Root, id + ".js")), cases.Length));
            }
            File.WriteAllText(Manifest, JsonSerializer.Serialize(new
            {
                schema = PublicBenchBank.Schema, authorReview = "PENDING", runtime = new { file = "runtime.js", sha256 = PublicBenchBank.FileSha256(Path.Combine(Root, "runtime.js")) }, tasks = entries,
            }, Json));
            Bank = PublicBenchBank.Load(Manifest);
            File.WriteAllText(Path.Combine(Root, "counter.py"), "# never executed in these interface tests\n");
            File.WriteAllText(Path.Combine(Root, "counter.json"), "{}");
            RewriteExposure([0]);WritePolicy();
        }

        public void RewriteExposure(int[] selected) => File.WriteAllText(ExposureFile, JsonSerializer.Serialize(new
        {
            schema = PromptExposure.Schema, bankManifestSha256 = Bank.ManifestSha256,
            scenario = new ExposureScenario("compact4k", 4096, 2048, 256, 3, 512),
            modelManifestSha256ByName = new Dictionary<string, string>(StringComparer.Ordinal) { ["fixture-qwen"] = new string('a', 64), ["fixture-llama"] = new string('b', 64) },
            tasks = Bank.Entries.Select(entry => new ExposureTask(entry.TaskId, entry.CaseCount, PromptExposure.Describe(Bank.ReadTask(entry.TaskId)).InputSha256, selected)),
        }, Json));

        public void WritePolicy()
        {
            var executable = Environment.ProcessPath!;
            var script = Path.Combine(Root, "counter.py");var config = Path.Combine(Root, "counter.json");
            File.WriteAllText(PolicyFile, JsonSerializer.Serialize(new
            {
                schema = PublicRequestPolicy.Schema, exposureFile = ExposureFile, exposureSha256 = PublicBenchBank.FileSha256(ExposureFile),
                model = "fixture-qwen", modelManifestSha256 = new string('a', 64), templateSha256 = new string('c', 64), systemSha256 = new string('d', 64),
                counter = new TokenCounterSpec(executable, PublicBenchBank.FileSha256(executable), script, PublicBenchBank.FileSha256(script), config, PublicBenchBank.FileSha256(config)),
            }, Json));
        }
        public string Output(string name) { var path = Path.Combine(Root, name);Directory.CreateDirectory(path);return path; }
        public void Dispose() => Directory.Delete(Root, true);
    }
}
