using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Aijade.Research.SkillBench;

/// <summary>One task's hidden suite and how the distinct test-passing candidates fared on it.</summary>
public sealed record DifferentialTask(string TaskId, int HiddenCases, int Candidates, int Disagreeing, IReadOnlyList<string> Examples);

/// <summary>
/// A construct-validity check for "passes the test cases" (P2 §7): candidates that pass a task's tests are compared with the
/// task's reference solution on new inputs derived from the test arguments by type-preserving perturbations. A candidate
/// that disagrees with the reference on any new input passed the tests without being equivalent to the reference. New
/// inputs on which the reference throws are dropped (outside the function's domain); inputs outside the instruction's
/// stated domain are not detected, so the disagreement rate is an upper bound on test-passing-but-wrong skills.
/// </summary>
public static class DifferentialTesting
{
    public const int VariantsPerCase = 8;

    /// <summary>Type-preserving perturbations of one JSON value (numbers, strings, arrays, booleans, objects).</summary>
    public static IEnumerable<JsonNode?> Perturb(JsonNode? v)
    {
        switch (v)
        {
            case JsonValue n when n.TryGetValue<double>(out var d) && n.GetValueKind() == JsonValueKind.Number:
                var integral = Math.Abs(d % 1) < 1e-12;
                foreach (var x in integral ? new[] { d + 1, d - 1, d * 2, 0, -d } : [d + 0.5, d * 2, 0, -d])
                    yield return integral ? JsonValue.Create((long)x) : JsonValue.Create(x);
                break;
            case JsonValue s when s.GetValueKind() == JsonValueKind.String:
                var str = s.GetValue<string>();
                yield return JsonValue.Create(new string(str.Reverse().ToArray()));
                yield return JsonValue.Create(str + "a");
                yield return JsonValue.Create(str.ToUpperInvariant());
                yield return JsonValue.Create("");
                if (str.Length > 1)
                    yield return JsonValue.Create(str[1..]);
                break;
            case JsonValue b when b.GetValueKind() is JsonValueKind.True or JsonValueKind.False:
                yield return JsonValue.Create(!b.GetValue<bool>());
                break;
            case JsonArray a:
                var items = a.Select(x => x?.DeepClone()).ToList();
                yield return new JsonArray([.. Enumerable.Reverse(items).Select(x => x?.DeepClone())]);
                if (items.Count > 0)
                {
                    yield return new JsonArray([.. items.Skip(1).Select(x => x?.DeepClone())]);
                    yield return new JsonArray([.. items.Select(x => x?.DeepClone()), items[^1]?.DeepClone()]);
                    // perturb one element in place
                    foreach (var p in Perturb(items[0]).Take(2))
                        yield return new JsonArray([p, .. items.Skip(1).Select(x => x?.DeepClone())]);
                }
                yield return new JsonArray();
                break;
            case JsonObject o when o.Count > 0:
                var first = o.First();
                foreach (var p in Perturb(first.Value).Take(3))
                {
                    var copy = (JsonObject)o.DeepClone();
                    copy[first.Key] = p;
                    yield return copy;
                }
                break;
        }
    }

    /// <summary>New argument lists for a test: each argument perturbed in turn, deduplicated, at most <see cref="VariantsPerCase"/>.</summary>
    public static IReadOnlyList<string> Variants(string argsLiteral)
    {
        JsonArray args;
        try
        {
            args = JsonNode.Parse(argsLiteral) as JsonArray ?? [];
        }
        catch (JsonException)
        {
            return [];   // not plain JSON (undefined, NaN, functions): left out
        }
        var seen = new HashSet<string>(StringComparer.Ordinal) { args.ToJsonString() };
        var output = new List<string>();
        for (var i = 0; i < args.Count && output.Count < VariantsPerCase; i++)
        {
            foreach (var p in Perturb(args[i]))
            {
                var copy = (JsonArray)args.DeepClone();
                copy[i] = p;
                var text = copy.ToJsonString();
                if (seen.Add(text))
                    output.Add(text);
                if (output.Count >= VariantsPerCase)
                    break;
            }
        }
        return output;
    }

    /// <summary>The hidden suite of a task: perturbed inputs with the reference's output as expected value (twice, identically).</summary>
    public static BenchTask HiddenSuite(BenchTask task, Sandbox sandbox)
    {
        var reference = Bench.ReferenceSolutions[task.Id];
        var inputs = task.Tests.SelectMany(t => Variants(t.Args)).Distinct(StringComparer.Ordinal).ToList();
        // an expected value nothing equals, so that every case reports the reference's actual output
        var probe = task with { Tests = [.. inputs.Select(a => new BenchCase(a, "Symbol()"))] };
        string?[] Outputs()
        {
            var verdict = sandbox.RunTask(reference, probe);
            var byIndex = verdict.Failures.ToDictionary(f => f.Index);
            return [.. inputs.Select((_, i) => byIndex.TryGetValue(i, out var f) && f.Error is null ? f.Actual : null)];
        }
        var first = Outputs();
        var second = Outputs();
        var cases = inputs.Select((a, i) => (a, first[i], second[i]))
            .Where(c => c.Item2 is not null && c.Item2 == c.Item3 && !c.Item2.Contains("Symbol(", StringComparison.Ordinal))
            .Select(c => new BenchCase(c.a, c.Item2!)).ToList();
        return task with { Tests = cases };
    }

    /// <summary>Run the distinct test-passing candidates of each task against its hidden suite.</summary>
    public static IReadOnlyList<DifferentialTask> Run(IReadOnlyDictionary<string, IReadOnlyCollection<string>> passingCandidatesByTask)
    {
        var sandbox = new Sandbox { IsolateArguments = true };
        var results = new List<DifferentialTask>();
        foreach (var task in Bench.Tasks.Where(t => passingCandidatesByTask.ContainsKey(t.Id)).OrderBy(t => t.Id, StringComparer.Ordinal))
        {
            var hidden = HiddenSuite(task, sandbox);
            var candidates = passingCandidatesByTask[task.Id];
            var disagreeing = 0;
            var examples = new List<string>();
            foreach (var code in candidates.Order(StringComparer.Ordinal))
            {
                if (hidden.Tests.Count == 0)
                    break;
                var verdict = sandbox.RunTask(code, hidden);
                if (verdict.Ok)
                    continue;
                disagreeing++;
                if (examples.Count < 2 && verdict.Failures.Count > 0 && verdict.Failures[0] is { } f)
                    examples.Add(string.Create(CultureInfo.InvariantCulture, $"args {f.Args}: reference {f.Expected}, candidate {f.Actual ?? f.Error ?? verdict.Error}"));
            }
            results.Add(new DifferentialTask(task.Id, hidden.Tests.Count, candidates.Count, disagreeing, examples));
        }
        return results;
    }
}
