using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Research.RqC;
using Aijade.Research.SkillBench;

namespace Aijade.Tests;

public sealed class PublicBenchBankTests
{
    [Fact]
    public void Public_files_and_manifest_are_bound_and_prompts_keep_expected_values_private()
    {
        using var fixture = new BankFixture();
        var bank = PublicBenchBank.Load(fixture.Manifest);
        var checkedTask = PublicBankCheck.RunReference(bank, "public-double");
        Assert.Equal(2, checkedTask.Passed);
        Assert.True(checkedTask.ExpectedOutputNoninterference);
        Assert.Equal("NOT_MEASURED", checkedTask.TokenizerStatus);
        Assert.True(checkedTask.VerifierA.Utf8Bytes > checkedTask.Generation.Utf8Bytes);
        var taskFile = Path.Combine(fixture.BankDirectory, bank.Entries[0].TaskFile);
        File.AppendAllText(taskFile, " ");
        Assert.Throws<InvalidDataException>(() => bank.ReadTask("public-double"));
        File.AppendAllText(fixture.Manifest, " ");
        Assert.Throws<InvalidDataException>(() => PublicBenchBank.Load(fixture.Manifest, bank.ManifestSha256));
    }

    [Fact]
    public void A_task_file_cannot_leave_the_materialized_bank()
    {
        using var fixture = new BankFixture();
        var manifest = JsonNode.Parse(File.ReadAllText(fixture.Manifest))!;
        manifest["tasks"]![0]!["taskFile"] = "../escape.json";
        File.WriteAllText(fixture.Manifest, manifest.ToJsonString());
        var bank = PublicBenchBank.Load(fixture.Manifest);
        Assert.Throws<InvalidDataException>(() => bank.ReadTask("public-double"));
    }

    [Theory]
    [InlineData(12)]
    [InlineData(44)]
    [InlineData(258)]
    [InlineData(338)]
    [InlineData(422)]
    public void Balanced_allocation_reaches_the_declared_exposure(int count)
    {
        var pool = Enumerable.Range(0, count).Select(i =>
            new BenchTask($"task-{i}", "fixture", BenchCategory.Logic, BenchTier.Medium, [])).ToArray();
        const int slots = 12;
        const int q = 8;
        var trials = (q * count + slots - 1) / slots;
        var allocation = TaskAllocation.Balanced(pool, trials, slots, 42);
        var counts = pool.ToDictionary(task => task.Id, _ => 0, StringComparer.Ordinal);
        foreach (var row in allocation)
        {
            Assert.Equal(slots, row.Select(task => task.Id).Distinct(StringComparer.Ordinal).Count());
            foreach (var task in row)
                counts[task.Id]++;
        }
        Assert.True(counts.Values.Min() >= q);
        Assert.InRange(counts.Values.Max() - counts.Values.Min(), 0, 1);
        Assert.Equal(allocation.SelectMany(row => row).Select(task => task.Id),
            TaskAllocation.Balanced(pool, trials, slots, 42).SelectMany(row => row).Select(task => task.Id));
        Assert.Throws<ArgumentOutOfRangeException>(() => TaskAllocation.Balanced(pool, trials, count + 1, 42));
    }

    [Fact]
    public async Task Normal_runner_uses_the_public_bank_and_checks_resume_identity()
    {
        using var fixture = new BankFixture();
        var ct = TestContext.Current.CancellationToken;
        var cfg = RqcCliConfig.Parse([
            "--public-bank", fixture.Manifest, "--trials", "1", "--rounds", "1", "--tasks", "3",
            "--p-correct", "1", "--save-candidates", "--out", Path.Combine(fixture.Root, "full"),
        ]);
        var (full, summary) = await RqcRunner.RunAsync(cfg, gitHash: "test", ct: ct);
        Assert.Equal("simulation", summary["mode"]!.GetValue<string>());
        Assert.Equal(3, summary["publicBank"]!["poolTasks"]!.GetValue<int>());
        Assert.Equal(1, summary["publicBank"]!["minimumPlannedExposure"]!.GetValue<int>());
        var steps = (await File.ReadAllLinesAsync(Path.Combine(full, "trials.jsonl"), ct))
            .Select(line => JsonNode.Parse(line)!).ToArray();
        Assert.Equal(12, steps.Length);
        Assert.All(steps, step =>
        {
            Assert.StartsWith("public-", step["taskId"]!.GetValue<string>(), StringComparison.Ordinal);
            Assert.True(step["execOk"]!.GetValue<bool>());
            Assert.Equal(cfg.PublicBankManifestSha256, step["publicBankManifestSha256"]!.GetValue<string>());
            Assert.Equal(cfg.Fingerprint(), step["runFingerprint"]!.GetValue<string>());
        });
        var cut = Path.Combine(fixture.Root, "cut");
        Directory.CreateDirectory(cut);
        foreach (var name in new[] { "trials.jsonl", "candidates.jsonl" })
            await File.WriteAllLinesAsync(Path.Combine(cut, name),
                (await File.ReadAllLinesAsync(Path.Combine(full, name), ct)).Take(8), ct);
        var resumedCfg = cfg with { ResumeFrom = Path.Combine(cut, "candidates.jsonl"), Out = Path.Combine(fixture.Root, "resumed") };
        var (resumedDir, resumed) = await RqcRunner.RunAsync(resumedCfg, gitHash: "test", ct: ct);
        Assert.Equal(8, resumed["resumed"]!["replayedSteps"]!.GetValue<int>());
        Assert.Equal(summary["fingerprint"]!.GetValue<string>(), resumed["fingerprint"]!.GetValue<string>());
        foreach (var name in new[] { "trials.jsonl", "candidates.jsonl" })
        {
            static IEnumerable<string> Decisions(string file) => File.ReadLines(file).Select(line =>
            {
                var row = JsonNode.Parse(line)!.AsObject();
                row.Remove("durationMs");
                return row.ToJsonString();
            });
            Assert.Equal(Decisions(Path.Combine(full, name)), Decisions(Path.Combine(resumedDir, name)));
        }
        await Assert.ThrowsAsync<InvalidDataException>(() => RqcRunner.RunAsync(
            resumedCfg with { Trials = 2, Out = Path.Combine(fixture.Root, "wrong-design") }, gitHash: "test", ct: ct));
        var wrong = cfg with { PublicBankPath = null, PublicBankManifestSha256 = null,
            ResumeFrom = Path.Combine(cut, "candidates.jsonl"), Out = Path.Combine(fixture.Root, "wrong-bank") };
        await Assert.ThrowsAsync<InvalidDataException>(() => RqcRunner.RunAsync(wrong, gitHash: "test", ct: ct));
        File.AppendAllText(fixture.Manifest, " ");
        await Assert.ThrowsAsync<InvalidDataException>(() => RqcRunner.RunAsync(
            resumedCfg with { PublicBankManifestSha256 = null }, gitHash: "test", ct: ct));
    }

    private sealed class BankFixture : IDisposable
    {
        private static readonly JsonSerializerOptions WebJson = new(JsonSerializerDefaults.Web);
        public string Root { get; } = Path.Combine(Path.GetTempPath(), "p2-bank-" + Guid.NewGuid().ToString("N"));
        public string BankDirectory => Path.Combine(Root, "bank");
        public string Manifest => Path.Combine(BankDirectory, "manifest.json");

        public BankFixture()
        {
            Directory.CreateDirectory(BankDirectory);
            File.WriteAllText(Path.Combine(BankDirectory, "runtime.js"), "");
            var tasks = new[]
            {
                (Id: "public-double", Code: "function solve(x){return x*2;}", Cases: new[] {new BenchCase("[2]", "4"), new BenchCase("[3]", "6")}),
                (Id: "public-bigint", Code: "function solve(x){return x+1n;}", Cases: new[] {new BenchCase("[9007199254740993n]", "9007199254740994n")}),
                (Id: "public-array", Code: "function solve(x){return x.slice().reverse();}", Cases: new[] {new BenchCase("[[1,2,3]]", "[3,2,1]")}),
            };
            var entries = new List<PublicBenchEntry>();
            foreach (var task in tasks)
            {
                var taskFile = task.Id + ".json";
                var reference = task.Id + ".js";
                File.WriteAllText(Path.Combine(BankDirectory, taskFile), JsonSerializer.Serialize(new
                {
                    taskId = task.Id, statement = "Perform the stated fixture operation.",
                    contract = "Use the given JavaScript argument types.", cases = task.Cases,
                }, WebJson));
                File.WriteAllText(Path.Combine(BankDirectory, reference), task.Code);
                entries.Add(new PublicBenchEntry(task.Id, task.Id, taskFile, PublicBenchBank.FileSha256(Path.Combine(BankDirectory, taskFile)),
                    reference, PublicBenchBank.FileSha256(Path.Combine(BankDirectory, reference)), task.Cases.Length));
            }
            File.WriteAllText(Manifest, JsonSerializer.Serialize(new
            {
                schema = PublicBenchBank.Schema, authorReview = "PENDING",
                runtime = new { file = "runtime.js", sha256 = PublicBenchBank.FileSha256(Path.Combine(BankDirectory, "runtime.js")) },
                tasks = entries,
            }, WebJson));
        }

        public void Dispose() => Directory.Delete(Root, true);
    }
}
