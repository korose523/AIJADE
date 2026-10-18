using System.Diagnostics;
using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Core.Js;

// P1 fault-injection / mutation experiment on the contract-drift matrix and the promotion-gate matrix.
//
// Hard constraints: no production file of the checkout is ever modified. Each mutant is applied to a
// temporary copy of the source tree (an exact, single-occurrence string replacement), built there, and the contract-drift
// matrix test runs against PostgreSQL; its full assertion log decides the verdict. The baseline must be all green, or the
// experiment is invalid and stops.
//
//   aijade-mutation [all | baseline-only | ID ...] --db <postgres url> [--repo .] [--out experiments/p1/mutation]
//                   [--catalogue tools/Aijade.Mutation/mutations.json] [--test <fully qualified test method>] [--title "..."]
// The default catalogue and test are the J1 contract-drift matrix; gate-mutants.json with PromotionGateMatrixTests is the
// P1 limitation-11 experiment (mutants in the promotion gates against the tamper matrix).
// Verdicts: caught (≥1 assertion turned red), survived (all green), notImplemented, mutationError (no match / build failure).
// diffScore = caught / (caught + survived).

string Opt(string name, string fallback)
{
    var i = Array.IndexOf(args, $"--{name}");
    return i >= 0 && i + 1 < args.Length ? args[i + 1] : fallback;
}
var repo = Path.GetFullPath(Opt("repo", "."));
var db = Opt("db", Environment.GetEnvironmentVariable("AIJADE_TEST_DATABASE_URL") ?? "");
var outDir = Path.GetFullPath(Opt("out", Path.Combine(repo, "experiments", "p1", "mutation")));
if (db.Length == 0)
{
    Console.Error.WriteLine("--db (or AIJADE_TEST_DATABASE_URL) is required");
    return 2;
}
var cataloguePath = Path.GetFullPath(Opt("catalogue", Path.Combine(repo, "tools", "Aijade.Mutation", "mutations.json")), repo);
var testMethod = Opt("test", "Aijade.Tests.ContractDriftMatrixTests.Matrix_log_equals_the_recorded_baseline_line_by_line");
var title = Opt("title", "J1 mutation experiment (.NET implementation)");
var catalogue = JsonNode.Parse(File.ReadAllText(cataloguePath))!.AsArray().Select(n => n!.AsObject()).ToList();
var positional = args.TakeWhile(a => !a.StartsWith("--", StringComparison.Ordinal)).ToList();
var ids = positional.Count == 0 || positional[0] == "all" ? catalogue.Select(m => m["id"]!.GetValue<string>()).ToList()
    : positional[0] == "baseline-only" ? [] : positional;
var work = Path.Combine(Path.GetTempPath(), $"aijade-mutation-{DateTime.UtcNow:yyyyMMddHHmmss}");
Directory.CreateDirectory(work);

static void CopyTree(string from, string to)
{
    foreach (var dir in Directory.EnumerateDirectories(from, "*", SearchOption.AllDirectories))
    {
        var rel = Path.GetRelativePath(from, dir);
        if (rel.Split(Path.DirectorySeparatorChar).Any(p => p is "bin" or "obj" or ".git" or "experiments"))
            continue;
        Directory.CreateDirectory(Path.Combine(to, rel));
    }
    foreach (var file in Directory.EnumerateFiles(from, "*", SearchOption.AllDirectories))
    {
        var rel = Path.GetRelativePath(from, file);
        if (rel.Split(Path.DirectorySeparatorChar).Any(p => p is "bin" or "obj" or ".git" or "experiments"))
            continue;
        File.Copy(file, Path.Combine(to, rel), overwrite: true);
    }
}

(int Code, string Output) Run(string file, string arguments, string cwd, IDictionary<string, string> env)
{
    var psi = new ProcessStartInfo(file, arguments) { WorkingDirectory = cwd, RedirectStandardOutput = true, RedirectStandardError = true };
    foreach (var (k, v) in env)
        psi.Environment[k] = v;
    using var p = Process.Start(psi)!;
    var stdout = p.StandardOutput.ReadToEndAsync();
    var stderr = p.StandardError.ReadToEndAsync();
    p.WaitForExit();
    return (p.ExitCode, stdout.Result + stderr.Result);
}

// The checkout is snapshotted once, so every mutant (and the baseline) is built from the same source even if the working
// tree changes while the experiment runs.
var pristine = Path.Combine(work, "pristine");
foreach (var item in new[] { "src", "tests", "tools" })
    CopyTree(Path.Combine(repo, item), Path.Combine(pristine, item));
foreach (var f in Directory.EnumerateFiles(repo).Where(f => Path.GetFileName(f) is "Directory.Build.props" or "Directory.Packages.props" or "Aijade.slnx" or "global.json" or "NuGet.config"))
    File.Copy(f, Path.Combine(pristine, Path.GetFileName(f)), overwrite: true);

// Returns the matrix log of the build with the given replacement (null replacement = baseline), or an error text.
(List<string>? Log, string? Error) RunMutant(string id, JsonObject? m)
{
    var copy = Path.Combine(work, id);
    CopyTree(pristine, copy);
    if (m is not null)
    {
        var target = Path.Combine(copy, m["file"]!.GetValue<string>());
        var text = File.ReadAllText(target);
        var match = m["match"]!.GetValue<string>();
        var first = text.IndexOf(match, StringComparison.Ordinal);
        if (first < 0 || text.IndexOf(match, first + 1, StringComparison.Ordinal) >= 0)
            return (null, first < 0 ? "match not found" : "match is not unique");
        File.WriteAllText(target, text[..first] + m["replace"]!.GetValue<string>() + text[(first + match.Length)..]);
    }
    var artifacts = Path.Combine(copy, ".artifacts");
    var env = new Dictionary<string, string> { ["AIJADE_ARTIFACTS"] = artifacts, ["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1", ["DOTNET_NOLOGO"] = "1" };
    // A mutant is not production code: constant conditions (if (false)) raise unreachable-code warnings, which must not abort it.
    var build = Run("dotnet", "build tests/Aijade.Tests -v q -p:TreatWarningsAsErrors=false", copy, env);
    if (build.Code != 0)
        return (null, "build failed: " + string.Join(" | ", build.Output.Split('\n').Where(l => l.Contains(" error ", StringComparison.Ordinal)).Take(5)));
    var log = Path.Combine(copy, "matrix.log");
    env["AIJADE_MATRIX_LOG"] = log;
    env["AIJADE_TEST_DATABASE_URL"] = db;
    var exe = Path.Combine(artifacts, "bin", "Aijade.Tests", "debug", "Aijade.Tests");
    Run(exe, $"-method {testMethod}", copy, env);
    return File.Exists(log) ? ([.. File.ReadAllLines(log)], null) : (null, "the matrix did not complete (no log)");
}

Console.WriteLine($"work dir {work}");
var (baseLog, baseError) = RunMutant("baseline", null);
if (baseLog is null || baseLog.Any(l => l.StartsWith("FAIL", StringComparison.Ordinal)))
{
    Console.Error.WriteLine($"BASELINE is not all green ({baseError ?? $"{baseLog!.Count(l => l.StartsWith("FAIL", StringComparison.Ordinal))} FAIL"}); the experiment is invalid.");
    return 1;
}
Console.WriteLine($"baseline: {baseLog.Count} assertions, failures=0 OK");

var results = new JsonArray();
int caught = 0, survived = 0, notImplemented = 0, errors = 0;
foreach (var m in catalogue)
{
    var id = m["id"]!.GetValue<string>();
    var row = (JsonObject)m.DeepClone();
    row.Remove("match");
    row.Remove("replace");
    if (!ids.Contains(id))
        continue;
    if (m["implementable"]?.GetValue<bool>() == false)
    {
        row["observedVerdict"] = "notImplemented";
        notImplemented++;
        results.Add(row);
        Console.WriteLine($"{id}: notImplemented");
        continue;
    }
    var (log, error) = RunMutant(id, m);
    if (log is null)
    {
        row["observedVerdict"] = "mutationError";
        row["error"] = error;
        errors++;
        results.Add(row);
        Console.WriteLine($"{id}: mutationError ({error})");
        continue;
    }
    var red = log.Where(l => l.StartsWith("FAIL", StringComparison.Ordinal)).ToList();
    var expected = m["expectedContains"]?.AsArray().Select(x => x!.GetValue<string>()).ToList() ?? [];
    var falseRed = expected.Count == 0 ? 0 : red.Count(l => !expected.Any(e => l.Contains(e, StringComparison.Ordinal)));
    var verdict = red.Count > 0 ? "caught" : "survived";
    if (verdict == "caught")
        caught++;
    else
        survived++;
    row["observedVerdict"] = verdict;
    row["assertions"] = log.Count;
    row["newRed"] = red.Count;
    row["falseRed"] = falseRed;
    row["redSample"] = new JsonArray([.. red.Take(5).Select(l => (JsonNode)l)]);
    results.Add(row);
    Console.WriteLine($"{id}: predicted={m["predictedVerdict"]} observed={verdict} newRed={red.Count} falseRed={falseRed}");
}
var denom = caught + survived;
var report = new JsonObject
{
    ["generatedBy"] = "tools/Aijade.Mutation",
    ["matrix"] = $"{testMethod} (PostgreSQL)",
    ["catalogue"] = Path.GetRelativePath(repo, cataloguePath),
    ["baseline"] = new JsonObject { ["assertions"] = baseLog.Count, ["failures"] = 0 },
    ["mutants"] = results,
    ["summary"] = new JsonObject
    {
        ["total"] = catalogue.Count, ["caught"] = caught, ["survived"] = survived, ["notImplemented"] = notImplemented, ["mutationError"] = errors,
        ["diffScore"] = denom == 0 ? 0 : Math.Round((double)caught / denom, 3),
    },
};
Directory.CreateDirectory(outDir);
File.WriteAllText(Path.Combine(outDir, "mutation-report.json"), JsFormat.Stringify(report, 2) + "\n");
var md = new StringBuilder();
md.AppendLine(CultureInfo.InvariantCulture, $"# {title}").AppendLine();
md.AppendLine(CultureInfo.InvariantCulture, $"- baseline: {baseLog.Count}/{baseLog.Count} assertions green").AppendLine();
md.AppendLine("| ID | file | expected capture | predicted | observed | new red | false red |").AppendLine("|---|---|---|---|---|---|---|");
foreach (var r in results)
{
    md.AppendLine(CultureInfo.InvariantCulture,
        $"| {r!["id"]} | `{r["file"]}` | {r["expectedCapture"]} | {r["predictedVerdict"]} | {r["observedVerdict"]} | {r["newRed"]?.ToString() ?? "-"} | {r["falseRed"]?.ToString() ?? "-"} |");
}
md.AppendLine().AppendLine(CultureInfo.InvariantCulture,
    $"caught {caught}, survived {survived}, notImplemented {notImplemented}, mutationError {errors}; **diffScore = caught / (caught + survived) = {(denom == 0 ? 0 : Math.Round((double)caught / denom, 3)).ToString(CultureInfo.InvariantCulture)}**");
File.WriteAllText(Path.Combine(outDir, "mutation-report.md"), md.ToString());
Console.WriteLine($"report: {outDir}");
try
{
    Directory.Delete(work, recursive: true);
}
catch (IOException)
{
}
return errors > 0 ? 1 : 0;
