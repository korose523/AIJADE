using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Research.RqC;

namespace Aijade.Research.SkillBench;

/// <summary>Input-only matched preparation and explicitly constructed controls, not a new task-eligibility decision.</summary>
public static class JudgmentPreparation
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web) { WriteIndented = true };
    private static readonly JsonSerializerOptions LineJson = new(JsonSerializerDefaults.Web);

    public static IReadOnlyList<BenchTask> Tasks(string source, PublicBenchBank bank) => source switch
    {
        "builtin" => Bench.Tasks,
        "public" => bank.Entries.Select(entry => bank.ReadTask(entry.TaskId)).ToArray(),
        _ => throw new ArgumentException("Task source must be builtin or public."),
    };

    public static void Export(string bankPath, string output)
    {
        if (Directory.Exists(output))throw new IOException("Use a fresh input-export directory.");
        var bank = PublicBenchBank.Load(bankPath);
        Directory.CreateDirectory(output);
        var summaries = new JsonArray();
        foreach (var source in new[] { "builtin", "public" })
        {
            var tasks = Tasks(source, bank);
            var identity = source == "builtin" ? Bench.ManifestSha256 : bank.ManifestSha256;
            using var writer = new StreamWriter(Path.Combine(output, source + "-inputs.jsonl"), false, new UTF8Encoding(false));
            foreach (var task in tasks)
            {
                var input = PromptExposure.Describe(task);
                var cases = input.Cases.Select(row => new
                {
                    row.Index, rawArgs = row.Args, rawSha256 = row.Sha256,
                    promptArgs = Backends.FormatCaseInput(task, row.Index),
                    promptSha256 = PromptExposure.Hash(Backends.FormatCaseInput(task, row.Index)),
                });
                writer.WriteLine(JsonSerializer.Serialize(new
                {
                    source, bankManifestSha256 = identity, taskId = task.Id, instruction = input.Instruction,
                    caseCount = input.CaseCount, inputSha256 = input.InputSha256,
                    callingConvention = task.PublicContract is null ? "original" : "public-contract", cases,
                }, LineJson));
            }
            summaries.Add(new JsonObject { ["source"] = source, ["bankManifestSha256"] = identity,
                ["tasks"] = tasks.Count, ["cases"] = tasks.Sum(task => task.Tests.Count) });
        }
        using (var writer = new StreamWriter(Path.Combine(output, "legacy-builtin-prompts.jsonl"), false, new UTF8Encoding(false)))
            foreach (var task in Bench.Tasks)
                writer.WriteLine(JsonSerializer.Serialize(new { taskId = task.Id,
                    prompts = PublicBankCheck.BuildPrompts(task, Bench.ReferenceSolutions[task.Id], null) }, LineJson));
        File.WriteAllText(Path.Combine(output, "summary.json"), new JsonObject
        {
            ["schema"] = "aijade.p2.judgment-inputs.v1", ["banks"] = summaries, ["newModelCompletionCalls"] = 0,
        }.ToJsonString(Json));
    }

    public static void Serve(string bankPath)
    {
        var bank = PublicBenchBank.Load(bankPath);
        var cache = new Dictionary<string, BenchTask>(StringComparer.Ordinal);
        string? line;
        while ((line = Console.ReadLine()) is not null)
        {
            var request = JsonNode.Parse(line)!.AsObject();
            var source = request["source"]!.GetValue<string>();var id = request["taskId"]!.GetValue<string>();
            var key = source + ":" + id;
            if (!cache.TryGetValue(key, out var task))
                cache[key] = task = source == "builtin" ? Bench.Tasks.Single(t => t.Id == id)
                    : source == "public" ? bank.ReadTask(id) : throw new InvalidDataException("Unknown task source.");
            var indices = request["indices"]!.AsArray().Select(value => value!.GetValue<int>()).ToArray();
            var version = request["instructionVersion"]!.GetValue<string>();
            PromptExposure.ValidateIndices(task, indices);
            const string stub = "";
            var prompts = new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["A"] = Backends.BuildVerifyPrompt(task, stub, indices, version),
                ["B"] = Backends.BuildVerifyPromptB(task, stub, indices, version),
            };
            var replaced = task with { Tests = task.Tests.Select(test => test with { Expected = "'EXPECTED_SENTINEL_c0a5'" }).ToArray() };
            var unchanged = prompts["A"] == Backends.BuildVerifyPrompt(replaced, stub, indices, version)
                && prompts["B"] == Backends.BuildVerifyPromptB(replaced, stub, indices, version)
                && PromptExposure.Describe(task).InputSha256 == PromptExposure.Describe(replaced).InputSha256;
            Console.WriteLine(JsonSerializer.Serialize(new
            {
                source, taskId = id, instructionVersion = version, inputSha256 = PromptExposure.Describe(task).InputSha256,
                fullOracleCases = task.Tests.Count, selectedCaseIndices = indices, expectedOutputNoninterference = unchanged, prompts,
            }, LineJson));
        }
    }

    public static void Controls(string bankPath, string builtinExposure, string publicExposure, string output)
    {
        if (Directory.Exists(output))throw new IOException("Use a fresh control directory.");
        var bank = PublicBenchBank.Load(bankPath);
        var old = PromptExposure.Load(builtinExposure, Bench.ManifestSha256, Bench.Tasks);
        var external = PromptExposure.Load(publicExposure, bank);
        var screen = Bench.Tasks.Select(task => new
        {
            taskId = task.Id, cases = task.Tests.Count,
            distinctPromptArguments = Enumerable.Range(0, task.Tests.Count).Select(i => Backends.FormatCaseInput(task, i)).Distinct(StringComparer.Ordinal).Count(),
        }).ToArray();
        var legacy = Bench.Tasks.Single(task => task.Id == screen.First(row => row.cases > 3 && row.distinctPromptArguments >= 4).taskId);
        var proposed = bank.ReadTask(bank.Entries[0].TaskId);
        if (proposed.Id != "HumanEval/0" || proposed.Tests.Count <= 3
            || Enumerable.Range(0, proposed.Tests.Count).Select(i => Backends.FormatCaseInput(proposed, i)).Distinct().Count() < 4)
            throw new InvalidDataException("The fixed public control does not meet the construction rule.");
        Directory.CreateDirectory(output);
        var rows = new JsonArray();
        foreach (var (source, task, exposure, positive) in new[]
        {
            ("builtin", legacy, old, Bench.ReferenceSolutions[legacy.Id]),
            ("public", proposed, external, PublicPositive),
        })
        {
            var indices = exposure.ForTask(task);
            if (indices.Count != 3)throw new InvalidDataException("The fixed controls require three displayed cases.");
            var lookup = new StringBuilder("function solve() {\n  switch (JSON.stringify(Array.from(arguments))) {\n");
            foreach (var i in indices)
                lookup.Append("    case ").Append(JsonSerializer.Serialize(Backends.FormatCaseInput(task, i)))
                    .Append(": return (").Append(task.Tests[i].Expected).AppendLine(");");
            lookup.AppendLine("    default: throw new Error('Input outside the displayed lookup');\n  }\n}");
            foreach (var (kind, code) in new[] { ("positive", positive), ("limited", lookup.ToString()) })
            {
                var full = new Sandbox().RunTask(code, task);
                var visible = new Sandbox().RunTask(code, task with { Tests = indices.Select(i => task.Tests[i]).ToArray() });
                if (!visible.Ok || kind == "positive" && !full.Ok || kind == "limited" && full.Ok)
                    throw new InvalidDataException("The fixed candidate-construction rule failed; do not substitute after model observations.");
                var id = source + "-" + kind;var filename = id + ".js";
                File.WriteAllText(Path.Combine(output, filename), code, new UTF8Encoding(false));
                rows.Add(new JsonObject
                {
                    ["id"] = id, ["source"] = source, ["taskId"] = task.Id, ["kind"] = kind,
                    ["candidateFile"] = filename, ["candidateSha256"] = PromptExposure.Hash(code),
                    ["inputSha256"] = PromptExposure.Describe(task).InputSha256,
                    ["selectedCaseIndices"] = JsonSerializer.SerializeToNode(indices),
                    ["full"] = JsonSerializer.SerializeToNode(full, Json), ["visible"] = JsonSerializer.SerializeToNode(visible, Json),
                    ["expectedOutputsEncodedInLimitedCandidate"] = kind == "limited",
                });
            }
        }
        File.WriteAllText(Path.Combine(output, "controls.json"), new JsonObject
        {
            ["schema"] = "aijade.p2.constructed-controls.v1", ["builtinEligibilityScreen"] = JsonSerializer.SerializeToNode(screen),
            ["candidates"] = rows, ["newModelCompletionCalls"] = 0,
            ["scope"] = "Two constructed development tasks; four candidates, not agent-generated or held out. Truth is finite complete-oracle success.",
        }.ToJsonString(Json));
    }

    private const string PublicPositive = """
        function solve(numbers, threshold) {
          for (let i = 0; i < numbers.length; i++)
            for (let j = i + 1; j < numbers.length; j++)
              if (Math.abs(numbers[i] - numbers[j]) < threshold) return true;
          return false;
        }
        """;
}
