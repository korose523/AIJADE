using System.Diagnostics;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Memory.Locomo;
using Aijade.Research.MemoryEval;

internal static class LongMemEvalStudy
{
    public const string PlanCommit = "a7961cf8cde1de659c2272a664d4c936a50484c4";
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web);
    private static readonly JsonSerializerOptions Pretty = new(Options) { WriteIndented = true };
    private static readonly string[] ExcludedMetadata = ["provenance", "runtimeSeconds", "generatedAt"];

    public static void Run(string data, string output, string repository)
    {
        if (LocomoCorpus.FileSha256(data) != LongMemEvalCorpus.Sha256)
            throw new InvalidDataException("LongMemEval input hash changed.");
        Directory.CreateDirectory(output);
        var file = Path.Combine(output, "kernel-cases.jsonl");
        using var stream = new FileStream(file, FileMode.CreateNew);
        using var journal = new StreamWriter(stream);
        using var doc = JsonDocument.Parse(File.ReadAllBytes(data));
        var clock = Stopwatch.StartNew();
        var cases = new List<LongMemCase>();
        var i = 0;
        foreach (var q in doc.RootElement.EnumerateArray())
        {
            var conv = LongMemEvalCorpus.ParseQuestion(q, LongMemEvalFrame.LegacyMarkedV1);
            if (conv is not null)
            {
                var row = LongMemEvalReanalysis.Measure(conv, i);
                journal.WriteLine(JsonSerializer.Serialize(row, Options));
                journal.Flush(); stream.Flush(flushToDisk: true);
                cases.Add(row);
            }
            File.WriteAllText(Path.Combine(output, "progress.json"), JsonSerializer.Serialize(new
            {
                phase = "kernel", rawIndex = i, rawQuestions = doc.RootElement.GetArrayLength(), cases = cases.Count,
                elapsedSeconds = clock.Elapsed.TotalSeconds, planCommit = PlanCommit,
            }, Options) + "\n");
            Console.WriteLine($"kernel {i + 1}/{doc.RootElement.GetArrayLength()}, {cases.Count} marked cases, {clock.Elapsed.TotalMinutes:0.0} min");
            i++;
        }
        if (i != 500 || cases.Count != 479 || cases.Count(c => c.Answerable) != 470)
            throw new InvalidDataException("Incomplete kernel population.");
        Aggregate(cases, output, repository);
        if (LocomoCorpus.FileSha256(data) != LongMemEvalCorpus.Sha256)
            throw new InvalidDataException("Input changed during kernel measurement.");
        File.WriteAllText(Path.Combine(output, "kernel-receipt.json"), JsonSerializer.Serialize(new
        {
            schema = "aijade.p3.longmemeval.kernel.v2", planCommit = PlanCommit,
            codeCommit = Environment.GetEnvironmentVariable("AIJADE_GIT_COMMIT"), rawQuestions = i, markedCases = cases.Count,
            primaryCases = cases.Count(c => c.Answerable), corpusSha256 = LongMemEvalCorpus.Sha256,
            journalSha256 = LocomoCorpus.FileSha256(file), elapsedSeconds = clock.Elapsed.TotalSeconds,
            runtime = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
            binaries = new[] { typeof(LongMemEvalStudy).Assembly, typeof(LongMemEvalReanalysis).Assembly, typeof(LongMemEvalCorpus).Assembly }.Select(a => new
            {
                name = a.GetName().Name, sha256 = Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(a.Location))),
                informationalVersion = a.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion,
            }),
            newModelCalls = 0, status = "complete-after-legacy-numeric-reconstruction",
        }, Pretty) + "\n");
    }

    public static void Aggregate(IReadOnlyList<LongMemCase> cases, string output, string repository)
    {
        var legacy = LongMemEvalReanalysis.Reports(cases);
        var differences = new List<string>();
        var metrics = 0;
        foreach (var (name, value) in legacy.Where(p => p.Key != "diagnostics.json"))
        {
            var old = JsonNode.Parse(File.ReadAllText(Path.Combine(repository, "experiments", "memory-longmemeval", name)))!;
            // Reparse to the same JSON number representation: newly constructed JsonValue<int> is not TryGetValue<double>.
            var fresh = JsonNode.Parse(value.ToJsonString())!;
            CompareNumbers(old, fresh, name, differences, ref metrics);
        }
        File.WriteAllText(Path.Combine(output, "legacy-comparison.json"), JsonSerializer.Serialize(new
        {
            status = differences.Count == 0 ? "PASS" : "FAIL", numericalMetrics = metrics, tolerance = 1e-9, differences,
            legacyQuestions = cases.Count, source = "experiments/memory-longmemeval", excludedMetadata = ExcludedMetadata,
        }, Pretty) + "\n");
        WriteReports(legacy, Path.Combine(output, "legacy-marked-v1"), "legacy-marked-v1");
        if (differences.Count != 0)
            throw new InvalidDataException("Legacy numerical reconstruction failed: " + string.Join("; ", differences.Take(8)));
        var primary = cases.Where(c => c.Answerable).ToArray();
        WriteReports(LongMemEvalReanalysis.Reports(primary), Path.Combine(output, "answerable-v2"), "answerable-v2");
    }

    private static void WriteReports(IReadOnlyDictionary<string, JsonObject> reports, string directory, string frame)
    {
        Directory.CreateDirectory(directory);
        foreach (var (name, value) in reports)
        {
            value["frame"] = frame; value["planCommit"] = PlanCommit;
            value["codeCommit"] = Environment.GetEnvironmentVariable("AIJADE_GIT_COMMIT");
            File.WriteAllText(Path.Combine(directory, name), value.ToJsonString(Pretty) + "\n");
        }
    }

    private static void CompareNumbers(JsonNode? old, JsonNode? fresh, string path, List<string> differences, ref int count)
    {
        if (old is JsonObject obj)
        {
            foreach (var (key, value) in obj)
                if (key is not ("provenance" or "runtimeSeconds" or "generatedAt"))
                    CompareNumbers(value, fresh?[key], path + "/" + key, differences, ref count);
        }
        else if (old is JsonArray list)
        {
            if (fresh is not JsonArray newList || newList.Count != list.Count)
                differences.Add(path + ": array shape changed");
            else
                for (var i = 0; i < list.Count; i++)
                    CompareNumbers(list[i], newList[i], path + "/" + i, differences, ref count);
        }
        else if (old is JsonValue v && v.TryGetValue<double>(out var number))
        {
            count++;
            if (fresh is not JsonValue f || !f.TryGetValue<double>(out var actual) || Math.Abs(number - actual) > 1e-9)
                differences.Add($"{path}: old {old}, fresh {fresh}");
        }
    }
}
