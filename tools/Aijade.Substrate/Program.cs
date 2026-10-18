using System.Globalization;

using Aijade.Core.Js;
using Aijade.Providers.Substrate;

// L0 substrate determinism verification:
//   dotnet run --project tools/Aijade.Substrate -- verify --model <tag> [--runs N] [--seed-strategy fixed|varied] [--control] [--base-url URL] [--out audit.json]
const string Usage = "Usage: verify --model <tag> [--runs N] [--seed-strategy fixed|varied] [--control] [--base-url URL] [--out audit.json]";
const string Probe = "In about 120 words, explain the water cycle to a student. Write connected prose; do not use bullet points or lists.";
const string Rule = "──────────────────────────────────────────────";

var command = args.Length > 0 ? args[0] : "verify";
var opts = new Dictionary<string, string>(StringComparer.Ordinal);
for (var i = 1; i < args.Length; i++)
{
    if (!args[i].StartsWith("--", StringComparison.Ordinal))
        continue;
    var parts = args[i][2..].Split('=', 2);
    if (parts.Length == 2)
        opts[parts[0]] = parts[1];
    else if (i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
        opts[parts[0]] = args[++i];
    else
        opts[parts[0]] = "true";
}
if (command != "verify")
{
    Console.Error.WriteLine($"Unknown command \"{command}\". {Usage}");
    return 2;
}
if (!opts.TryGetValue("model", out var model))
{
    Console.Error.WriteLine($"--model is required.\n{Usage}");
    return 2;
}
var runs = int.Parse(opts.GetValueOrDefault("runs", "5"), CultureInfo.InvariantCulture);
var strategy = opts.GetValueOrDefault("seed-strategy") == "varied" ? SeedStrategy.Varied : SeedStrategy.Fixed;
var baseUrl = opts.GetValueOrDefault("base-url", "http://127.0.0.1:11434");
var withControl = opts.GetValueOrDefault("control") is "true" or "1";

try
{
    using var http = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };
    var substrate = new OllamaSubstrate(http, model, SubstrateMode.Research, baseUrl: baseUrl);
    var identity = await substrate.IdentityAsync();
    var fp = await substrate.FingerprintAsync();
    Console.WriteLine(Rule);
    Console.WriteLine(" L0 substrate — determinism verification");
    Console.WriteLine(Rule);
    Console.WriteLine($" model        {identity.Tag}");
    Console.WriteLine($" digest       {identity.Digest ?? "(unresolved — tag is mutable, weights are NOT pinned)"}");
    Console.WriteLine($" weights      {(identity.SizeBytes is { } b ? $"{JsFormat.ToFixed(b / 1e9, 2)} GB" : "-")}");
    Console.WriteLine($" family       {identity.Family ?? "-"}  params {identity.ParameterSize ?? "-"}  quant {identity.Quantization ?? "-"}");
    Console.WriteLine($" mode         {WireName.Of(fp.Mode)}");
    Console.WriteLine($" sampling     {JsFormat.Stringify(fp.Sampling.ToJson())}");
    Console.WriteLine($" samplingHash {fp.SamplingHash}");
    Console.WriteLine($" server       {fp.ServerVersion ?? "(unknown)"}");
    Console.WriteLine($" fingerprint  {fp.Fingerprint}");
    Console.WriteLine($" runs         {runs} (seed strategy: {WireName.Of(strategy)})");
    Console.WriteLine($" control      {(withControl ? "ENABLED (positive control + audit verdict)" : "off (passing here does NOT prove greedy decoding)")}");
    Console.WriteLine(Rule);
    ChatMessage[] messages = [new(ChatRole.User, Probe)];
    if (!withControl)
    {
        var report = await Determinism.MeasureAsync(substrate, messages, runs, strategy);
        foreach (var r in report.PerRun)
            Console.WriteLine($" run {r.Index}  seed={JsFormat.Number(r.Seed)}  hash={r.Hash}  chars={r.Chars}");
        Console.WriteLine(Rule);
        Console.WriteLine(report.Identical
            ? $" PASS  {report.UniqueOutputs} distinct output across {report.Runs} runs." + (strategy == SeedStrategy.Varied ? "\n       Outputs match even with different seeds — decoding is genuinely greedy." : "")
            : $" FAIL  {report.UniqueOutputs} distinct outputs across {report.Runs} runs.\n       Do not run experiments on this substrate until this is understood.");
        Console.WriteLine(Rule);
        Console.WriteLine(" NOTE  This is an UNTESTED pass: identical outputs are also what a dropped");
        Console.WriteLine("       sampling config produces. Re-run with --control to make it evidence.");
        Console.WriteLine(Rule);
        return report.Identical ? 0 : 1;
    }
    var control = new OllamaSubstrate(http, model, SubstrateMode.Interactive, fp.Sampling with { Temperature = 1, TopK = 40, TopP = 0.95 }, baseUrl);
    var audit = await Determinism.AuditAsync(substrate, messages, runs, strategy, control, runs);
    foreach (var r in audit.Check.PerRun)
        Console.WriteLine($" check  run {r.Index}  seed={JsFormat.Number(r.Seed)}  hash={r.Hash}  chars={r.Chars}");
    Console.WriteLine($" check  => {audit.Check.UniqueOutputs} distinct across {audit.Check.Runs} runs ({WireName.Of(audit.Check.SeedStrategy)} seed)");
    Console.WriteLine(Rule);
    Console.WriteLine(" POSITIVE CONTROL  (sampling deliberately opened — this arm MUST diverge)");
    Console.WriteLine($" sampling   {JsFormat.Stringify(audit.Control.Sampling.ToJson())}");
    Console.WriteLine($" hash       {audit.Control.SamplingHash}");
    foreach (var r in audit.Control.PerRun)
        Console.WriteLine($" control  run {r.Index}  seed={JsFormat.Number(r.Seed)}  hash={r.Hash}  chars={r.Chars}");
    Console.WriteLine($" control  => verdict={WireName.Of(audit.Control.Verdict)}  {audit.Control.UniqueOutputs} distinct across {audit.Control.Runs} runs");
    if (audit.Control.Error is { } err)
        Console.WriteLine($" control  error: {err}");
    Console.WriteLine(Rule);
    if (opts.TryGetValue("out", out var outPath))
    {
        static System.Text.Json.Nodes.JsonArray Runs(IReadOnlyList<DeterminismRun> rs) => [.. rs.Select(r => (System.Text.Json.Nodes.JsonNode)new System.Text.Json.Nodes.JsonObject
        {
            ["index"] = r.Index, ["seed"] = r.Seed, ["hash"] = r.Hash, ["chars"] = r.Chars,
        })];
        var json = new System.Text.Json.Nodes.JsonObject
        {
            ["experiment"] = "determinism pre-check with a positive control (sampling deliberately opened)",
            ["model"] = identity.Tag, ["digest"] = identity.Digest, ["serverVersion"] = fp.ServerVersion, ["fingerprint"] = fp.Fingerprint,
            ["verdict"] = Determinism.Kebab(audit.Verdict), ["discriminative"] = audit.Discriminative, ["falsePositiveRisk"] = audit.FalsePositiveRisk,
            ["reason"] = audit.Reason,
            ["check"] = new System.Text.Json.Nodes.JsonObject
            {
                ["runs"] = audit.Check.Runs, ["seedStrategy"] = WireName.Of(audit.Check.SeedStrategy), ["uniqueOutputs"] = audit.Check.UniqueOutputs,
                ["sampling"] = System.Text.Json.Nodes.JsonNode.Parse(JsFormat.Stringify(fp.Sampling.ToJson())), ["perRun"] = Runs(audit.Check.PerRun),
            },
            ["control"] = new System.Text.Json.Nodes.JsonObject
            {
                ["runs"] = audit.Control.Runs, ["uniqueOutputs"] = audit.Control.UniqueOutputs, ["verdict"] = WireName.Of(audit.Control.Verdict),
                ["sampling"] = System.Text.Json.Nodes.JsonNode.Parse(JsFormat.Stringify(audit.Control.Sampling.ToJson())), ["perRun"] = Runs(audit.Control.PerRun),
            },
        };
        File.WriteAllText(outPath, JsFormat.Stringify(json, 2) + "\n");
    }
    Console.WriteLine($" VERDICT  {Determinism.Kebab(audit.Verdict)}");
    Console.WriteLine($" {audit.Reason}");
    Console.WriteLine(Rule);
    return audit.Verdict == DeterminismAuditVerdict.Pass ? 0 : 1;
}
catch (SamplingException e)
{
    Console.Error.WriteLine(e.Message);
    return 1;
}
