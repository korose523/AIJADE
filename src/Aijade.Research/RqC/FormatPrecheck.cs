using System.Text.Json.Nodes;

using Aijade.Research.SkillBench;

namespace Aijade.Research.RqC;

/// <summary>One pre-check reply: whether it begins with PASS or FAIL, as the verifier prompt asks.</summary>
public sealed record FormatPrecheckItem(string TaskId, bool CodeIsCorrect, bool Conforming, bool Aborted, string ReplyHead);

/// <summary>
/// Format pre-check for choosing a model for a control run (P2 second-family control, rule fixed on 2026-10-18 before any
/// result): five synthetic tasks that are not in the bench are sent with the run's own verifier prompt, sampling and warm-up,
/// and the model passes when every reply begins with PASS or FAIL. Whether the verdicts are right is not looked at, so the
/// choice cannot lean on the bench outcome.
/// </summary>
public static class FormatPrecheck
{
    private static BenchTask Task(string id, string instruction, BenchCategory category, params (string Args, string Expected)[] tests) =>
        new(id, instruction, category, BenchTier.Easy, [.. tests.Select(t => new BenchCase(t.Args, t.Expected))]);

    /// <summary>The five tasks with one candidate each (three correct, two wrong); none of the ids or functions is in the bench.</summary>
    public static IReadOnlyList<(BenchTask Task, string Code, bool Correct)> Items { get; } =
    [
        (Task("pre-str-count-words", "Write a function `countWords(s)` that returns the number of whitespace-separated words in s.", BenchCategory.String,
            ("[\"a b  c\"]", "3"), ("[\"\"]", "0"), ("[\"  one \"]", "1")),
            "function countWords(s) { return s.split(/\\s+/).filter(w => w.length > 0).length; }", true),
        (Task("pre-arr-last", "Write a function `last(arr)` that returns the last element of arr, or null when arr is empty.", BenchCategory.Array,
            ("[[1,2,3]]", "3"), ("[[]]", "null"), ("[[\"x\"]]", "\"x\"")),
            "function last(arr) { return arr.length ? arr[0] : null; }", false),
        (Task("pre-math-sum-squares", "Write a function `sumOfSquares(nums)` that returns the sum of the squares of the numbers in nums.", BenchCategory.Math,
            ("[[1,2,3]]", "14"), ("[[]]", "0"), ("[[-2]]", "4")),
            "function sumOfSquares(nums) { return nums.reduce((s, n) => s + n * n, 0); }", true),
        (Task("pre-str-initials", "Write a function `initials(name)` that returns the uppercase first letters of the words in name, e.g. \"Ada Lovelace\" -> \"AL\".", BenchCategory.String,
            ("[\"Ada Lovelace\"]", "\"AL\""), ("[\"grace brewster hopper\"]", "\"GBH\"")),
            "function initials(name) { return name.split(' ').map(w => w[0]).join(''); }", false),
        (Task("pre-obj-invert", "Write a function `invert(obj)` that returns a new object whose keys are obj's values and whose values are obj's keys.", BenchCategory.Object,
            ("[{\"a\":\"x\",\"b\":\"y\"}]", "{\"x\":\"a\",\"y\":\"b\"}"), ("[{}]", "{}")),
            "function invert(obj) { const out = {}; for (const [k, v] of Object.entries(obj)) out[v] = k; return out; }", true),
    ];

    /// <summary>Warm up, then verify each item once; an aborted or length-limited reply counts as non-conforming.</summary>
    public static async Task<IReadOnlyList<FormatPrecheckItem>> RunAsync(OllamaBackend backend, CancellationToken ct = default)
    {
        await backend.WarmUpAsync(ct).ConfigureAwait(false);
        var results = new List<FormatPrecheckItem>();
        foreach (var (task, code, correct) in Items)
        {
            var stops = backend.AbortedReplies + backend.LengthLimitedReplies;
            var v = await backend.VerifyAsync(task, code, ct).ConfigureAwait(false);
            var aborted = backend.AbortedReplies + backend.LengthLimitedReplies > stops;
            var reply = v.FullReply ?? v.Rationale;
            OllamaBackend.ReadVerdict(reply, fallback: false, out var conforming, out _);
            results.Add(new FormatPrecheckItem(task.Id, correct, conforming && !aborted, aborted, reply.Length > 200 ? reply[..200] : reply));
        }
        return results;
    }

    /// <summary>The pre-check verdict as JSON (model provenance is added by the caller).</summary>
    public static JsonObject Report(IReadOnlyList<FormatPrecheckItem> items) => new()
    {
        ["rule"] = "pass when every reply begins with PASS or FAIL (verdict correctness not examined); aborted or length-limited replies do not conform",
        ["conforming"] = items.Count(i => i.Conforming),
        ["items"] = items.Count,
        ["pass"] = items.All(i => i.Conforming),
        ["replies"] = new JsonArray([.. items.Select(i => (JsonNode)new JsonObject
        {
            ["task"] = i.TaskId, ["codeIsCorrect"] = i.CodeIsCorrect, ["conforming"] = i.Conforming, ["aborted"] = i.Aborted, ["replyHead"] = i.ReplyHead,
        })]),
    };
}
