using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Research.RqC;
using Aijade.Research.SkillBench;

// Exports frozen development requests using the production experiment's prompt
// builders. It calls no model and never changes the historical bench or archives.
if (args.Length == 3 && args[0] == "classify")
{
    var resultPath = Path.GetFullPath(args[1]);
    var result = JsonNode.Parse(File.ReadAllText(resultPath))!.AsObject();
    var rows = new JsonArray();
    foreach (var model in result["models"]!.AsArray())
    {
        var alias = model!["model"]!.GetValue<string>().StartsWith("qwen", StringComparison.Ordinal) ? "qwen7b" : "llama8b";
        foreach (var request in model["requests"]!.AsArray())
        {
            var kind = request!["kind"]!.GetValue<string>();
            if (kind is not ("verifier-A" or "verifier-B" or "format-A") || request["metrics"] is not JsonObject metrics)
                continue;
            var id = request["id"]!.GetValue<string>();
            if (Path.GetFileName(id) != id)
                throw new InvalidDataException("Unsafe case identity");
            var responsePath = Path.Combine(Path.GetDirectoryName(resultPath)!, alias, id, "response.json");
            var response = JsonNode.Parse(File.ReadAllText(responsePath))!.AsObject();
            var reply = response["message"]!["content"]!.GetValue<string>();
            OllamaBackend.ReadVerdict(reply, fallback: false, out var conforming, out _);
            rows.Add(new JsonObject { ["model"] = model["model"]!.GetValue<string>(), ["case"] = id,
                ["existingParserConforming"] = conforming, ["monitorConforming"] = metrics["verdictPrefixConforming"]!.GetValue<bool>(),
                ["matches"] = conforming == metrics["verdictPrefixConforming"]!.GetValue<bool>() });
        }
    }
    var report = new JsonObject { ["kind"] = "independent classification by existing OllamaBackend.ReadVerdict; no model calls or accuracy selection",
        ["allMatch"] = rows.All(r => r!["matches"]!.GetValue<bool>()), ["rows"] = rows };
    File.WriteAllText(args[2], report.ToJsonString(new() { WriteIndented = true }) + "\n");
    return report["allMatch"]!.GetValue<bool>() ? 0 : 1;
}
if (args.Length != 2)
{
    Console.Error.WriteLine("Usage: Aijade.MacPreflight <repository-root> <new-fixtures.json>");
    return 2;
}
var root = Path.GetFullPath(args[0]);
var output = Path.GetFullPath(args[1]);
if (File.Exists(output))
    throw new IOException("Refusing to overwrite frozen fixtures");
var tasks = Bench.Tasks.ToDictionary(t => t.Id, StringComparer.Ordinal);
var runs = new[]
{
    "experiments/rq-c/family-gpu/rq-c-s42-ollama-t30-r5",
    "experiments/rq-c/template-gpu/A/rq-c-s42-ollama-t30-r5",
    "experiments/rq-c/template-gpu/B/rq-c-s42-ollama-t30-r5",
};
var sources = new JsonObject();
var candidates = new List<ArchivedCandidate>();
foreach (var run in runs)
{
    var trialsPath = Path.Combine(root, run, "trials.jsonl");
    var codesPath = Path.Combine(root, run, "candidates.jsonl");
    sources[$"{run}/trials.jsonl"] = Hash(trialsPath);
    sources[$"{run}/candidates.jsonl"] = Hash(codesPath);
    var trials = File.ReadLines(trialsPath).Where(l => !string.IsNullOrWhiteSpace(l)).Select(l => JsonNode.Parse(l)!.AsObject()).ToArray();
    foreach (var line in File.ReadLines(codesPath).Where(l => !string.IsNullOrWhiteSpace(l)))
    {
        var row = JsonNode.Parse(line)!.AsObject();
        if (row["reused"]!.GetValue<bool>() || row["code"]?.GetValue<string>() is not { Length: > 0 } code)
            continue;
        var step = row["step"]!.GetValue<int>();
        var trial = trials[step];
        if (row["skillId"]!.GetValue<string>() != trial["skillId"]!.GetValue<string>())
            throw new InvalidDataException("Archive step/candidate identity mismatch");
        candidates.Add(new ArchivedCandidate(trial["taskId"]!.GetValue<string>(), code, run, step,
            row["execOk"]!.GetValue<bool>(), row["selfRationale"]?.GetValue<string>()));
    }
}

var initial = tasks.Values.Select(t => new { Task = t, Prompt = Backends.BuildGeneratePrompt(t, new GenerateContext(0)) })
    .OrderByDescending(x => x.Prompt.Length).ThenBy(x => x.Task.Id, StringComparer.Ordinal).First();
var longest = candidates.OrderByDescending(c => Backends.BuildVerifyPrompt(tasks[c.TaskId], c.Code).Length)
    .ThenBy(c => c.TaskId, StringComparer.Ordinal).ThenBy(c => c.Source, StringComparer.Ordinal).ThenBy(c => c.Step).First();
var failed = candidates.Where(c => !c.ExecutionOk).OrderByDescending(c => c.Code.Length)
    .ThenBy(c => c.TaskId, StringComparer.Ordinal).ThenBy(c => c.Source, StringComparer.Ordinal).ThenBy(c => c.Step).First();
var failedTask = tasks[failed.TaskId];
var verdict = new Sandbox().RunTask(failed.Code, failedTask);
if (verdict.Ok)
    throw new InvalidDataException("The selected failed candidate no longer fails; do not fabricate retry feedback");
var feedback = new EnvironmentFeedbackSignal(verdict.Failures.Select(f => f.Index).ToList(), verdict.Passed, verdict.Total,
    (verdict.Error is { } error ? new[] { error } : []).Concat(verdict.Failures.Where(f => f.Error is not null).Select(f => f.Error!)).Take(4).ToList());
var retry = Backends.BuildGeneratePrompt(failedTask, new GenerateContext(1, feedback, failed.Critique, failed.Code));
var fixtures = new JsonArray
{
    Item("cold-ready", "startup", OllamaBackend.WarmUpPrompt),
    Item("warm-initial-longest", "generation", initial.Prompt, initial.Task.Id),
    Item("warm-retry-longest-code", "retry", retry, failed.TaskId, failed),
    Item("warm-verifier-longest-A", "verifier-A", Backends.BuildVerifyPrompt(tasks[longest.TaskId], longest.Code), longest.TaskId, longest),
    Item("warm-verifier-longest-B", "verifier-B", Backends.BuildVerifyPromptB(tasks[longest.TaskId], longest.Code), longest.TaskId, longest),
};
foreach (var (task, code, _) in FormatPrecheck.Items)
    fixtures.Add(Item($"format-{task.Id}", "format-A", Backends.BuildVerifyPrompt(task, code), task.Id));

foreach (var path in new[] { "src/Aijade.Research/RqC/Backends.cs", "src/Aijade.Research/RqC/FormatPrecheck.cs",
                            "src/Aijade.Research/SkillBench/Bench.cs", "src/Aijade.Research/SkillBench/Sandbox.cs",
                            "src/Aijade.Research/SkillBench/bench-data.json", "tools/Aijade.MacPreflight/Program.cs",
                            "tools/Aijade.MacPreflight/Aijade.MacPreflight.csproj", "tools/Aijade.MacPreflight/run_preflight.py",
                            "experiments/plans/2026-11-09-mac-capacity-preflight.md" })
    sources[path] = Hash(Path.Combine(root, path));
var binaries = new JsonObject();
foreach (var path in Directory.EnumerateFiles(AppContext.BaseDirectory, "*.dll").Order(StringComparer.Ordinal))
    binaries[Path.GetFileName(path)] = Hash(path);
var document = new JsonObject
{
    ["kind"] = "frozen development capacity/latency fixtures; not primary outcome data",
    ["initialTaskCount"] = tasks.Count, ["archiveCandidateRowsConsidered"] = candidates.Count,
    ["selection"] = "longest initial prompt and longest template-A verifier prompt by UTF-16 length; longest failed code for constructed retry; ties taskId/source/step ordinal; five existing format tasks unchanged",
    ["sampling"] = new JsonObject { ["temperature"] = 0, ["seed"] = 3759066737L, ["num_ctx"] = 4096, ["num_predict"] = 4096 },
    ["sourcesSha256"] = sources, ["binarySha256"] = binaries,
    ["items"] = fixtures,
};
Directory.CreateDirectory(Path.GetDirectoryName(output)!);
using (var stream = new FileStream(output, FileMode.CreateNew, FileAccess.Write))
    stream.Write(Encoding.UTF8.GetBytes(document.ToJsonString(new() { WriteIndented = true }) + "\n"));
Console.WriteLine($"Exported {fixtures.Count} requests; {tasks.Count} tasks and {candidates.Count} archived candidate rows; no model calls.");
return 0;

static string Hash(string path) => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(path)));

static JsonObject Item(string id, string kind, string prompt, string? taskId = null, ArchivedCandidate? candidate = null) => new()
{
    ["id"] = id, ["kind"] = kind, ["taskId"] = taskId, ["prompt"] = prompt,
    ["promptUtf16Length"] = prompt.Length,
    ["promptSha256"] = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(prompt))),
    ["archive"] = candidate is null ? null : new JsonObject
    {
        ["run"] = candidate.Source, ["step"] = candidate.Step,
        ["codeSha256"] = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(candidate.Code))),
        ["construction"] = kind == "retry" ? "one constructed attempt-1 retry using the saved program and current sandbox feedback; not a reconstructed historical trajectory" : "existing archived candidate",
    },
};

sealed record ArchivedCandidate(string TaskId, string Code, string Source, int Step, bool ExecutionOk, string? Critique);
