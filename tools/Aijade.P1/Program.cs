using System.Globalization;

using Aijade.P1;

using Npgsql;

// P1 evaluation driver against a running server.
//   aijade-p1 e2e-main|e2e-negative-fork|bench-ingest|bench-loop --base http://localhost:3901 --token T --db <postgres url or conn string>
//             [--mode sequential|concurrent|both] [--n 100] [--warmup 10] [--out file.json]
// Exit code: 0 all checks pass, 1 a check failed (or a bench request was not 201), 2 usage error.

if (args.Length == 0)
{
    Console.Error.WriteLine("usage: aijade-p1 e2e-main|e2e-negative-fork|bench-ingest --base URL --token T --db CONN [...]");
    return 2;
}
var command = args[0];
string Opt(string name, string fallback)
{
    var i = Array.IndexOf(args, $"--{name}");
    return i >= 0 && i + 1 < args.Length ? args[i + 1] : fallback;
}
var baseUrl = Opt("base", Environment.GetEnvironmentVariable("AIJADE_E2E_BASE") ?? "http://localhost:3901");
var token = Opt("token", Environment.GetEnvironmentVariable("AIJADE_E2E_TOKEN") ?? "e2e-test-token-aijade-2026");
var dbArg = Opt("db", Environment.GetEnvironmentVariable("DATABASE_URL") ?? "");
if (dbArg.StartsWith("postgres", StringComparison.Ordinal))
{
    var uri = new Uri(dbArg);
    var userInfo = uri.UserInfo.Split(':', 2);
    dbArg = new NpgsqlConnectionStringBuilder
    {
        Host = uri.Host, Port = uri.Port > 0 ? uri.Port : 5432, Database = uri.AbsolutePath.Trim('/'),
        Username = Uri.UnescapeDataString(userInfo[0]), Password = userInfo.Length > 1 ? Uri.UnescapeDataString(userInfo[1]) : null,
    }.ConnectionString;
}
using var http = new HttpClient { BaseAddress = new Uri(baseUrl), Timeout = TimeSpan.FromSeconds(30) };
await using var db = NpgsqlDataSource.Create(dbArg);
var target = new Target(http, db, token);

if (command == "bench-loop")
{
    var loop = await Scenarios.BenchLoopAsync(target, int.Parse(Opt("n", "20"), CultureInfo.InvariantCulture));
    var text = Aijade.Core.Js.JsFormat.Stringify(loop, 2) + "\n";
    if (Opt("out", "") is { Length: > 0 } loopOut)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(loopOut))!);
        await File.WriteAllTextAsync(loopOut, text);
    }
    var run = loop["runs"]!["loop"]!;
    Console.WriteLine($"loop: n={run["n"]} errors={run["errors"]} p50 {run["p50"]} ms p95 {run["p95"]} ms mean {run["mean"]} ms");
    return run["errors"]!.GetValue<int>() > 0 ? 1 : 0;
}
if (command == "bench-ingest")
{
    var mode = Opt("mode", "both");
    var n = int.Parse(Opt("n", "100"), CultureInfo.InvariantCulture);
    var warmup = int.Parse(Opt("warmup", "10"), CultureInfo.InvariantCulture);
    var result = await Scenarios.BenchIngestAsync(target, mode, n, warmup);
    var outPath = Opt("out", "");
    var text = Aijade.Core.Js.JsFormat.Stringify(result, 2) + "\n";
    if (outPath.Length > 0)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outPath))!);
        await File.WriteAllTextAsync(outPath, text);
        Console.WriteLine($"raw samples written to {outPath}");
    }
    foreach (var (name, run) in result["runs"]!.AsObject())
    {
        string F(string k) => run![k] is { } v ? $"{v.GetValue<double>().ToString("F1", CultureInfo.InvariantCulture)} ms" : "—";
        Console.WriteLine($"{name}: n={run!["n"]} errors={run["errors"]} min {F("min")} p50 {F("p50")} p95 {F("p95")} p99 {F("p99")} max {F("max")} mean {F("mean")}");
    }
    var errors = result["runs"]!.AsObject().Sum(r => r.Value!["errors"]!.GetValue<int>());
    return errors > 0 ? 1 : 0;
}

IReadOnlyList<CheckResult> results = command switch
{
    "e2e-main" => await Scenarios.MainFlowAsync(target),
    "e2e-negative-fork" => await Scenarios.NegativeForkAsync(target),
    _ => throw new ArgumentException($"unknown command {command}"),
};
foreach (var r in results)
    Console.WriteLine($"{(r.Pass ? "PASS" : "FAIL")}  {r.Name}{(r.Detail.Length > 0 ? $"  — {r.Detail}" : "")}");
var passed = results.Count(r => r.Pass);
Console.WriteLine($"\n===== {command}: {passed}/{results.Count} passed =====");
return passed == results.Count ? 0 : 1;
