using System.Text.Json;

using Aijade.Research.RqC;
using Aijade.Research.SkillBench;

namespace Aijade.Tests;

/// <summary>
/// The Jint sandbox must give the recorded verdict for every (task, candidate) pair:
/// reference solutions, the wrong candidates and a set of edge cases (syntax error, throw, timeout, no function, host
/// access, in-place mutation of the arguments, NaN / -0 / undefined results, load-time throw).
/// </summary>
// The node-vm parity verdicts include the 2-second time budget, so these run alone: under parallel load on a throttled CPU
// a script that finishes in time on its own can be starved past the budget and flip to "timeout".
[Collection(TimeBudgetGroup.Name)]
public class SandboxTests(ITestOutputHelper output)
{
    private static readonly JsonElement[] Golden =
        [.. JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "sandbox-golden.json"))).RootElement.EnumerateArray()];

    private const string InfiniteLoop = "function solve() { while (true) {} }";

    private static string? S(JsonElement e) => e.ValueKind == JsonValueKind.Null ? null : e.GetString();

    [Fact]
    public void Verdicts_match_node_vm_case_by_case()
    {
        var sandbox = new Sandbox();
        var tasks = Bench.Tasks.ToDictionary(t => t.Id);
        var mismatches = new List<string>();
        var compared = 0;
        var timeoutTasks = Bench.Tasks.Take(3).Select(t => t.Id).ToHashSet();
        foreach (var g in Golden)
        {
            var taskId = g.GetProperty("task").GetString()!;
            var code = g.GetProperty("code").GetString()!;
            // A timeout waits the full 2 s; replaying it on three tasks is enough (it never mutates shared state).
            if (code == InfiniteLoop && !timeoutTasks.Contains(taskId))
                continue;
            compared++;
            var v = sandbox.RunTask(code, tasks[taskId]);
            var expected = $"ok={g.GetProperty("ok").GetBoolean()} passed={g.GetProperty("passed").GetInt32()} error={S(g.GetProperty("error"))} failures="
                + string.Join(";", g.GetProperty("failures").EnumerateArray().Select(f => $"{f.GetProperty("index").GetInt32()}:{S(f.GetProperty("error"))}:{S(f.GetProperty("actual"))}"));
            var actual = $"ok={v.Ok} passed={v.Passed} error={v.Error} failures="
                + string.Join(";", v.Failures.Select(f => $"{f.Index}:{f.Error}:{f.Actual}"));
            if (expected != actual)
                mismatches.Add($"{taskId} | {code}\n  node: {expected}\n  jint: {actual}");
        }
        output.WriteLine($"compared {compared}, mismatches {mismatches.Count}");
        foreach (var m in mismatches.Take(40))
            output.WriteLine(m);
        Assert.Empty(mismatches);
    }

    [Fact]
    public void Reference_solutions_pass_and_wrong_candidates_fail_everywhere()
    {
        var sandbox = new Sandbox();
        Assert.Equal(Bench.Tasks.Select(t => t.Id).Order(StringComparer.Ordinal), Bench.ReferenceSolutions.Keys.Order(StringComparer.Ordinal));
        Assert.True(Bench.Tasks.Count >= 40);
        Assert.Equal(7, Bench.Tasks.Select(t => t.Category).Distinct().Count());
        foreach (var t in Bench.Tasks)
        {
            Assert.True(sandbox.RunTask(Bench.ReferenceSolutions[t.Id], t).Ok, t.Id);
            Assert.All(Bench.WrongCandidates, w => Assert.False(sandbox.RunTask(w, t).Ok));
        }
    }

    [Fact]
    public void Code_extraction_and_sampling()
    {
        Assert.Equal("const a = 1", Bench.ExtractCodeBlock("text\n```js\nconst a = 1\n```\nmore"));
        Assert.Equal("x()", Bench.ExtractCodeBlock("```JavaScript\nx()\n```"));
        Assert.Equal("first", Bench.ExtractCodeBlock("```js\nfirst\n```\n```js\nsecond\n```"));
        Assert.Equal("plain code", Bench.ExtractCodeBlock("plain code"));
        Assert.Null(Bench.ExtractCodeBlock(null));
        Assert.Equal(Bench.SampleTasks(10, 42).Select(t => t.Id), Bench.SampleTasks(10, 42).Select(t => t.Id));
        Assert.NotEqual(Bench.SampleTasks(10, 42).Select(t => t.Id), Bench.SampleTasks(10, 43).Select(t => t.Id));
        Assert.Equal(10, Bench.SampleTasks(10, 1).Select(t => t.Id).Distinct().Count());
        Assert.Equal(Bench.Tasks.Count, Bench.SampleTasks(1000, 1).Count);
    }

    [Fact]
    public void Public_task_requires_explicit_solve_and_discloses_it_in_both_prompts()
    {
        var task = new BenchTask("public", "Return the first element.", BenchCategory.Array, BenchTier.Easy,
            [new BenchCase("[[3]]", "3")]) { PublicContract = "Numeric values use Number." };
        var sandbox = new Sandbox();
        Assert.True(sandbox.RunTask("const solve = xs => xs[0];", task).Ok);
        Assert.True(sandbox.RunTask("let solve = xs => xs[0];", task).Ok);
        Assert.False(sandbox.RunTask("function alternative(xs) { return xs[0]; }", task).Ok);
        var promptTask = task with { Tests = [new BenchCase("[[(3n)]]", "\"held-output-marker\"")] };
        var generation = Backends.BuildGeneratePrompt(promptTask, new GenerateContext(0));
        var verifierPrompts = new[] { Backends.BuildVerifyPrompt(promptTask, "const solve = xs => xs[0];"),
            Backends.BuildVerifyPromptB(promptTask, "const solve = xs => xs[0];") };
        Assert.Contains(BenchTask.PublicCallingRule, generation, StringComparison.Ordinal);
        Assert.All(verifierPrompts, prompt =>
        {
            Assert.Contains(BenchTask.PublicCallingRule, prompt, StringComparison.Ordinal);
            Assert.Contains("[[(3n)]]", prompt, StringComparison.Ordinal);
            Assert.DoesNotContain("held-output-marker", prompt, StringComparison.Ordinal);
        });
    }

    [Theory]
    [InlineData("9007199254740993n", "9007199254740993n", false, true)]
    [InlineData("9007199254740992n", "9007199254740993n", false, false)]
    [InlineData("255n", "(0xffn)", false, true)]
    [InlineData("-255n", "(-0xffn)", false, true)]
    [InlineData("1n", "1", false, false)]
    [InlineData("1.0000004", "1", true, true)]
    [InlineData("1.0000004", "1", false, false)]
    [InlineData("'1'", "1", true, false)]
    [InlineData("true", "1", true, false)]
    [InlineData("[1.0000004,2]", "[1,2]", true, true)]
    [InlineData("[1.0000004]", "[1,2]", true, false)]
    [InlineData("[1,,3]", "[1,2,3]", false, false)]
    [InlineData("new Date(0)", "{}", false, false)]
    [InlineData("null", "{}", false, false)]
    public void Public_comparison_uses_the_case_policy(string actual, string expected, bool tolerance, bool pass)
    {
        var task = new BenchTask("public", "Return a value.", BenchCategory.Logic, BenchTier.Easy,
            [new BenchCase("[]", expected) { PublicFloatTolerance = tolerance }]) { PublicContract = "Return the declared value." };
        Assert.Equal(pass, new Sandbox().RunTask($"const solve = () => ({actual});", task).Ok);
    }
}

[CollectionDefinition(Name, DisableParallelization = true)]
public sealed class TimeBudgetGroup
{
    public const string Name = "time-budget";
}
