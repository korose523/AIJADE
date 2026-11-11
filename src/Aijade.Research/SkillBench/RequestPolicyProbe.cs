using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Research.RqC;

namespace Aijade.Research.SkillBench;

/// <summary>Exercises actual tokenizer/dispatch code with a synthetic HTTP handler; never contacts a model server.</summary>
public static class RequestPolicyProbe
{
    private sealed record Probe(string Id, string Stage, string Template, string Candidate, GenerateContext Context,
        string? ExpectedStatus, string ResponseKind = "normal", string CounterKind = "normal");

    public static async Task<JsonObject> RunAsync(string bankPath, string policyPath, string output, CancellationToken ct = default)
    {
        if (Directory.Exists(output))throw new IOException("Use a fresh policy-probe output directory.");
        var bank = PublicBenchBank.Load(bankPath);
        var policy = PublicRequestPolicy.Load(policyPath, bank);
        var task = bank.ReadTask(bank.Entries[0].TaskId);
        var indices = policy.Exposure.ForTask(task);
        var reference = bank.ReadReference(task.Id);
        Directory.CreateDirectory(output);
        var scenario = policy.Exposure.Scenario;
        const string stub = "function solve() {}";
        var marker = policy.Model.StartsWith("qwen", StringComparison.Ordinal) ? "<|im_end|>" : "<|eot_id|>";
        var probes = new List<Probe>
        {
            new("initial-generation", "generation", "A", stub, new GenerateContext(0), null),
            new("empty-A", "verification", "A", stub, new GenerateContext(0), null),
            new("empty-B", "verification", "B", stub, new GenerateContext(0), null),
        };
        var preparation = new JsonArray();
        using (var counter = new ExternalPromptCounter(policy, Path.Combine(output, "construction.stderr.log")))
        {
            foreach (var template in new[] { "A", "B" })
            {
                var prompt = template == "A" ? Backends.BuildVerifyPrompt(task, reference, indices) : Backends.BuildVerifyPromptB(task, reference, indices);
                var count = await counter.CountAsync(prompt, ct).ConfigureAwait(false);
                probes.Add(new Probe("reference-" + template, "verification", template, reference, new GenerateContext(0),
                    count.InputTokens + scenario.VerificationReplyTokens > scenario.ContextTokens ? "CONTEXT_OVERFLOW" : null));
                preparation.Add(new JsonObject { ["id"] = "reference-" + template, ["inputTokens"] = count.InputTokens,
                    ["rawSha256"] = count.RawSha256, ["tokenIdsSha256"] = count.TokenIdsSha256 });
            }
            foreach (var stage in new[] { "generation", "verification-A", "verification-B" })
            {
                var verification = stage != "generation";
                var template = stage == "verification-B" ? "B" : "A";
                string Code(int n) => "function solve() {}\n/*" + string.Concat(Enumerable.Repeat(marker, n)) + "*/";
                GenerateContext Context(int n) => new(1, SelfCritique: "Controlled request-budget fixture.", PreviousCode: Code(n));
                string Prompt(int n) => !verification ? Backends.BuildGeneratePrompt(task, Context(n))
                    : template == "A" ? Backends.BuildVerifyPrompt(task, Code(n), indices) : Backends.BuildVerifyPromptB(task, Code(n), indices);
                var cap = verification ? scenario.VerificationReplyTokens : scenario.GenerationReplyTokens;
                var baseline = await counter.CountAsync(Prompt(0), ct).ConfigureAwait(false);
                var n = scenario.ContextTokens - cap - baseline.InputTokens;
                if (n < 0)throw new InvalidDataException("The fixed boundary-control prefix does not fit; retain the failed probe.");
                var exact = await counter.CountAsync(Prompt(n), ct).ConfigureAwait(false);
                var over = await counter.CountAsync(Prompt(n + 1), ct).ConfigureAwait(false);
                if (exact.InputTokens + cap != scenario.ContextTokens || over.InputTokens != exact.InputTokens + 1)
                    throw new InvalidDataException("The fixed marker boundary construction is not exact.");
                preparation.Add(new JsonObject { ["id"] = stage, ["marker"] = marker, ["markerCount"] = n,
                    ["atBoundaryTokens"] = exact.InputTokens, ["overBoundaryTokens"] = over.InputTokens,
                    ["atBoundaryRawSha256"] = exact.RawSha256, ["overBoundaryRawSha256"] = over.RawSha256 });
                probes.Add(new Probe(stage + "-boundary", verification ? "verification" : "generation", template, Code(n), Context(n), null));
                probes.Add(new Probe(stage + "-one-over", verification ? "verification" : "generation", template, Code(n + 1), Context(n + 1), "CONTEXT_OVERFLOW"));
            }
        }
        var oversized = "function solve() {}\n/*" + string.Concat(Enumerable.Repeat(" long controlled input 1234567890 ", 12000)) + "*/";
        probes.AddRange([
            new("large-retry", "generation", "A", oversized, new GenerateContext(1, SelfCritique: "Controlled long retry.", PreviousCode: oversized), "CONTEXT_OVERFLOW"),
            new("large-verification", "verification", "A", oversized, new GenerateContext(0), "CONTEXT_OVERFLOW"),
            new("malformed-counter", "verification", "A", stub, new GenerateContext(0), "COUNTER_ERROR", CounterKind: "malformed"),
            new("changed-counter-identity", "verification", "A", stub, new GenerateContext(0), "COUNTER_ERROR", CounterKind: "identity"),
            new("length-limited-verdict", "verification", "A", stub, new GenerateContext(0), "REPLY_LENGTH_LIMIT", "length"),
            new("nonconforming-verdict", "verification", "A", stub, new GenerateContext(0), "VERDICT_FORMAT_ERROR", "format"),
            new("http-error", "verification", "A", stub, new GenerateContext(0), "HTTP_ERROR", "error"),
        ]);
        var results = new JsonArray();
        foreach (var probe in probes)
        {
            var folder = Path.Combine(output, probe.Id);Directory.CreateDirectory(folder);
            var selectedPolicy = policy;
            if (probe.CounterKind != "normal")
            {
                var script = Path.Combine(folder, "synthetic-counter.py");
                File.WriteAllText(script, BadCounterScript.Replace("COUNTER_KIND", probe.CounterKind, StringComparison.Ordinal));
                var raw = JsonNode.Parse(File.ReadAllText(policyPath))!.AsObject();
                raw["exposureFile"] = Path.GetFullPath(raw["exposureFile"]!.GetValue<string>(), Path.GetDirectoryName(Path.GetFullPath(policyPath))!);
                raw["counter"]!["script"] = script;raw["counter"]!["scriptSha256"] = PublicBenchBank.FileSha256(script);
                var changed = Path.Combine(folder, "synthetic-policy.json");File.WriteAllText(changed, raw.ToJsonString());
                selectedPolicy = PublicRequestPolicy.Load(changed, bank);
            }
            var handler = new SyntheticHandler(probe.ResponseKind, probe.Stage);
            using var http = new HttpClient(handler);
            string? failure = null;
            using (var budget = new RequestBudget(selectedPolicy, new ExternalPromptCounter(selectedPolicy, Path.Combine(folder, "counter.stderr.log")), folder, 48))
            {
                var backend = new OllamaBackend(http, policy.Model, timeout: TimeSpan.FromSeconds(120), verifyTemplate: probe.Template, requestBudget: budget);
                try
                {
                    if (probe.Stage == "generation")await backend.GenerateAsync(task, probe.Context, ct).ConfigureAwait(false);
                    else await backend.VerifyAsync(task, probe.Candidate, ct).ConfigureAwait(false);
                }
                catch (RequestBudgetFailure error) { failure = error.Status; }
                if (failure != probe.ExpectedStatus || handler.Calls != (probe.ExpectedStatus is "CONTEXT_OVERFLOW" or "COUNTER_ERROR" ? 0 : 1))
                    throw new InvalidDataException($"Policy probe {probe.Id} did not meet the fixed dispatch/failure rule.");
            }
            var incomplete = Path.Combine(folder, "incomplete-run.json");
            if (failure is not null && (!File.Exists(incomplete) || JsonNode.Parse(File.ReadAllText(incomplete))!["verdict"] is not null))
                throw new InvalidDataException("A failed policy probe acquired a verdict or lost its incomplete receipt.");
            results.Add(new JsonObject { ["id"] = probe.Id, ["expectedStatus"] = probe.ExpectedStatus,
                ["actualStatus"] = failure ?? "FITTING_SYNTHETIC_RESPONSE", ["syntheticHttpDispatches"] = handler.Calls,
                ["noAcceptedRunSummary"] = !File.Exists(Path.Combine(folder, "summary.json")), ["passed"] = true });
        }
        var summary = new JsonObject
        {
            ["schema"] = "aijade.p2a.request-policy-probe.v1", ["model"] = policy.Model,
            ["scenario"] = scenario.Id, ["taskId"] = task.Id, ["policySha256"] = policy.Sha256,
            ["fixtureRule"] = "First bank task; exact lengths built with literal special-token markers, not realistic skill candidates.",
            ["construction"] = preparation, ["probes"] = results, ["status"] = "PASS",
            ["newModelCompletionCalls"] = 0, ["httpHandler"] = "Synthetic in-process handler; no network/model service.",
            ["managedHeapHardLimitEnvironment"] = Environment.GetEnvironmentVariable("DOTNET_GCHeapHardLimit"),
            ["gcTotalAvailableMemoryBytes"] = GC.GetGCMemoryInfo().TotalAvailableMemoryBytes,
            ["gcConfiguration"] = JsonSerializer.SerializeToNode(GC.GetConfigurationVariables()),
        };
        File.WriteAllText(Path.Combine(output, "summary.json"), summary.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
        return summary;
    }

    private sealed class SyntheticHandler(string kind, string stage) : HttpMessageHandler
    {
        public int Calls { get; private set; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            var content = kind == "format" ? "Synthetic undecidable reply."
                : stage == "generation" ? "```js\nfunction solve() {}\n```" : "PASS synthetic transport control";
            return Task.FromResult(new HttpResponseMessage(kind == "error" ? HttpStatusCode.InternalServerError : HttpStatusCode.OK)
            {
                Content = new StringContent(JsonSerializer.Serialize(new { message = new { content }, done_reason = kind == "length" ? "length" : "stop" }), Encoding.UTF8, "application/json"),
            });
        }
    }

    private const string BadCounterScript = """
        import hashlib,json,sys
        from pathlib import Path
        config=Path(sys.argv[sys.argv.index('--config')+1]);data=json.loads(config.read_text());model=data['modelConfig']
        sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
        print(json.dumps({'schema':'aijade.p2a.token-counter.ready.v1','configSha256':sha(config),'scriptSha256':sha(__file__),
            'modelManifestSha256':model['manifestSha256'],'templateSha256':'0'*64 if 'COUNTER_KIND'=='identity' else model['effectiveTemplateSha256'],
            'systemSha256':model['effectiveSystemSha256']}),flush=True)
        line=sys.stdin.readline()
        if line:
            request=json.loads(line)
            print(json.dumps({'schema':'aijade.p2a.token-counter.count.v1','id':request['id'],'inputTokens':'malformed'}),flush=True)
        """;
}
