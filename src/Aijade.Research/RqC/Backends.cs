using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Core.Random;
using Aijade.Research.SkillBench;

namespace Aijade.Research.RqC;

// The candidate
// generator / self-verifier backends of the RQ-C harness — a seeded mock (the positive control whose recovery is gated
// on the presence of a feedback signal) and an Ollama backend with locked sampling (temperature 0 + seed).

/// <summary>What the environment told the loop about the previous candidate.</summary>
public sealed record EnvironmentFeedbackSignal(IReadOnlyList<int> FailedCaseIndices, int Passed, int Total, IReadOnlyList<string> Errors);

public sealed record GenerateContext(int Attempt, EnvironmentFeedbackSignal? EnvFeedback = null, string? SelfCritique = null, string? PreviousCode = null, string? PreviousFailure = null);

/// <param name="Pass">The verdict.</param>
/// <param name="Score">0.8 for a pass, 0.2 for a fail.</param>
/// <param name="Rationale">The reply as fed back to the generator (the first 280 characters).</param>
/// <param name="FullReply">The whole reply, recorded for audit only; null when it equals <paramref name="Rationale"/>.</param>
public sealed record SelfVerifierVerdict(bool Pass, double Score, string Rationale, string? FullReply = null);

/// <summary>
/// Resume an interrupted run: answer the first calls with the generations and self-verification replies the interrupted run
/// recorded (candidates.jsonl, in call order), then hand over to the live backend. Every other part of the harness is
/// deterministic, so the replayed prefix reproduces the interrupted run's state exactly; the runner checks that it does.
/// </summary>
public sealed class ResumingBackend(ILlmBackend live, IReadOnlyList<string> generations, IReadOnlyList<(bool Pass, string Rationale)> verdicts) : ILlmBackend
{
    private int nextGeneration;
    private int nextRationale;

    public string Name => live.Name;

    public int ReplayedGenerations => nextGeneration;

    public int ReplayedVerifications => nextRationale;

    public bool Exhausted => nextGeneration >= generations.Count && nextRationale >= verdicts.Count;

    public Task<string> GenerateAsync(BenchTask task, GenerateContext ctx, CancellationToken cancellationToken = default) =>
        nextGeneration < generations.Count ? Task.FromResult(generations[nextGeneration++]) : live.GenerateAsync(task, ctx, cancellationToken);

    public Task<SelfVerifierVerdict> VerifyAsync(BenchTask task, string candidate, CancellationToken cancellationToken = default)
    {
        if (nextRationale >= verdicts.Count)
            return live.VerifyAsync(task, candidate, cancellationToken);
        // the rationale is what the live backend kept (the Ollama reply cut to 280 characters), the verdict the one it logged;
        // the score is the Ollama backend's function of the verdict
        var (pass, rationale) = verdicts[nextRationale++];
        return Task.FromResult(new SelfVerifierVerdict(pass, pass ? 0.8 : 0.2, rationale));
    }
}

/// <summary>The negative-control generator: the first generation of each task is returned for every later attempt.</summary>
public sealed class InertBackend(ILlmBackend live) : ILlmBackend
{
    private readonly Dictionary<string, string> first = new(StringComparer.Ordinal);

    public string Name => live.Name;

    public async Task<string> GenerateAsync(BenchTask task, GenerateContext ctx, CancellationToken cancellationToken = default)
    {
        if (first.TryGetValue(task.Id, out var cached))
            return cached;
        var candidate = await live.GenerateAsync(task, new GenerateContext(0, null, null, null), cancellationToken).ConfigureAwait(false);
        first[task.Id] = candidate;
        return candidate;
    }

    public Task<SelfVerifierVerdict> VerifyAsync(BenchTask task, string candidate, CancellationToken cancellationToken = default) =>
        live.VerifyAsync(task, candidate, cancellationToken);
}

public interface ILlmBackend
{
    string Name { get; }

    Task<string> GenerateAsync(BenchTask task, GenerateContext ctx, CancellationToken cancellationToken = default);

    Task<SelfVerifierVerdict> VerifyAsync(BenchTask task, string candidate, CancellationToken cancellationToken = default);
}

public static class Backends
{
    internal static string WrapCode(string code) =>
        string.Join("\n", "Here is the implementation. Return ONLY the function; do not explain.", "", "```js", code, "```");

    /// <summary>
    /// The generation prompt. On an informed retry the evidence comes first and the request last, so the model reads the
    /// diagnosis before writing (evidence placed after the request measurably failed to change the output).
    /// </summary>
    public static string BuildGeneratePrompt(BenchTask task, GenerateContext ctx)
    {
        var s = ctx.SelfCritique;
        var e = ctx.EnvFeedback;
        var informedRetry = (e is not null || s is not null || ctx.PreviousFailure is not null) && ctx.Attempt > 0;
        var lines = new List<string>();
        if (informedRetry)
        {
            lines.Add("You are an expert JavaScript programmer fixing a previous failure.");
            lines.Add($"Task: {task.Instruction}");
            lines.Add("");
            lines.Add("--- WHY THE PREVIOUS ATTEMPT FAILED ---");
            if (e is not null)
            {
                lines.Add($"The previous implementation was executed against the task's test suite and FAILED: {e.Passed}/{e.Total} cases passed.");
                if (e.FailedCaseIndices.Count > 0)
                    lines.Add($"Failing case indices (0-based): {string.Join(", ", e.FailedCaseIndices)}.");
                if (e.Errors.Count > 0)
                    lines.Add($"It raised: {string.Join(" | ", e.Errors)}");
                lines.Add("The expected outputs of the test cases are withheld from you. Diagnose the defect from the case inputs and the failure pattern.");
            }
            if (s is not null)
                lines.Add($"Your own verification step REJECTED the previous implementation with this critique: {s}");
            lines.Add("");
            if (!string.IsNullOrWhiteSpace(ctx.PreviousCode))
            {
                lines.Add("The rejected implementation, which you MUST NOT repeat:");
                lines.Add("```js");
                lines.Add(Text.JsTrim(ctx.PreviousCode));
                lines.Add("```");
                lines.Add("");
            }
            lines.Add("Write a CORRECTED implementation that is materially DIFFERENT from the rejected one.");
            lines.Add("Re-examine the specification and the failing cases; do not just re-emit the same logic with cosmetic edits.");
        }
        else
        {
            lines.Add("You are an expert JavaScript programmer.");
            lines.Add($"Implement the following function. Task: {task.Instruction}");
        }
        lines.Add("Respond with ONLY a single fenced JavaScript code block (```js ... ```)");
        lines.Add("that defines a function named `solve` (or a single callable expression).");
        lines.Add("Do not include any explanation outside the code block.");
        return string.Join("\n", lines);
    }

    /// <summary>The verification prompt: the case inputs (as JSON.stringify writes them) but never the expected outputs.</summary>
    public static string BuildVerifyPrompt(BenchTask task, string code) => string.Join("\n",
        "You are verifying a JavaScript solution against a task.",
        $"Task: {task.Instruction}",
        "Candidate code:",
        "```js",
        code,
        "```",
        "You are given ONLY the inputs of the test cases, never the expected outputs:",
        string.Join("\n", task.Tests.Select((t, i) => $"  case {i}: args = {JsJson.Stringify(t.Args)} (expected WITHHELD)")),
        "For each case, decide whether the code returns the correct result, then give an overall verdict.",
        "Respond with a single line: either \"PASS\" or \"FAIL\", followed by a short reason.");

    /// <summary>
    /// Template B of the verifier prompt (P2 prompt-template control, wording registered 2026-10-18 before any run): the same
    /// information and the same requested output format as <see cref="BuildVerifyPrompt"/>, in a different order and
    /// phrasing, saying what PASS and FAIL mean.
    /// </summary>
    public static string BuildVerifyPromptB(BenchTask task, string code) => string.Join("\n",
        $"Task: {task.Instruction}",
        "A candidate solution:",
        "```js",
        code,
        "```",
        "Test inputs (the expected outputs are not shown):",
        string.Join("\n", task.Tests.Select((t, i) => $"  {i + 1}. {JsJson.Stringify(t.Args)}")),
        "Question: does the candidate return the correct output for every one of these inputs?",
        "Answer on one line that starts with PASS (it does) or FAIL (it does not), then give a brief justification.");

    /// <summary>FNV-1a over the first UTF-16 unit of each code point of "model|baseUrl" — the default locked seed.</summary>
    public static uint DeriveOllamaSeed(string model, string baseUrl)
    {
        var h = 0x811C9DC5u;
        Span<char> buf = stackalloc char[2];
        foreach (var rune in $"{model}|{baseUrl}".EnumerateRunes())
        {
            rune.EncodeToUtf16(buf);
            h = unchecked((h ^ buf[0]) * 0x01000193u);
        }
        return h;
    }
}

/// <summary>JavaScript helpers evaluated in a throwaway engine (JSON.stringify and String.prototype.trim semantics).</summary>
internal static class JsJson
{
    public static string Stringify(string literal) =>
        Jint.Runtime.TypeConverter.ToString(new Jint.Engine().Evaluate($"JSON.stringify({literal})"));
}

internal static class Text
{
    public static string JsTrim(string s) => Aijade.Core.Js.JsText.Trim(s);
}

/// <summary>
/// The seeded simulation backend. A retry carrying evidence recovers with probability pRetrySuccess; a retry without
/// evidence is the null design. The self-verdict is sampled from the injected hallucination / miss rates around the true
/// sandbox verdict, which is what lets the estimator's unbiasedness be tested.
/// </summary>
public sealed class MockBackend(uint seed, Sandbox sandbox, double pCorrect = 0.5, double hallucination = 0.3, double miss = 0.1, double pRetrySuccess = 0.7) : ILlmBackend
{
    private readonly Mulberry32 _rng = new(seed);

    public string Name => "mock";

    private static bool HasSignal(GenerateContext c) => c.EnvFeedback is not null || c.SelfCritique is not null || c.PreviousFailure is not null;

    public Task<string> GenerateAsync(BenchTask task, GenerateContext ctx, CancellationToken cancellationToken = default)
    {
        if (ctx.Attempt > 0 && HasSignal(ctx) && _rng.Next() < pRetrySuccess)
            return Task.FromResult(Backends.WrapCode(Bench.ReferenceSolutions[task.Id]));
        var code = _rng.Next() < pCorrect
            ? Bench.ReferenceSolutions[task.Id]
            : Bench.WrongCandidates[(int)Math.Floor(_rng.Next() * Bench.WrongCandidates.Count)];
        return Task.FromResult(Backends.WrapCode(code));
    }

    public Task<SelfVerifierVerdict> VerifyAsync(BenchTask task, string candidate, CancellationToken cancellationToken = default)
    {
        var code = Bench.ExtractCodeBlock(candidate) ?? candidate;
        var ok = sandbox.RunTask(code, task).Ok;
        var pass = ok ? _rng.Next() >= miss : _rng.Next() < hallucination;
        var score = pass ? 0.6 + (_rng.Next() * 0.39) : _rng.Next() * 0.39;
        return Task.FromResult(new SelfVerifierVerdict(pass, score,
            $"[simulation] true_ok={(ok ? "true" : "false")}; sampled self-verdict from hallucination={Aijade.Core.Js.JsFormat.Number(hallucination)}, miss={Aijade.Core.Js.JsFormat.Number(miss)}"));
    }
}

/// <summary>Ollama chat backend with locked sampling (temperature 0 + seed) so generations and verdicts are reproducible.</summary>
public sealed class OllamaBackend(HttpClient http, string model, string baseUrl = "http://localhost:11434", double temperature = 0, uint? seed = null, TimeSpan? timeout = null, int? maxReplyTokens = null, bool verdictFallback = false, int? numCtx = null, string verifyTemplate = "A") : ILlmBackend
{
    public string Name => "ollama";

    private int aborted;
    private int lengthLimited;
    private int nonConforming;
    private int fallbackRead;

    /// <summary>
    /// Verifier replies that do not begin with PASS or FAIL, as the prompt asks. Under the verdict rule fixed before the runs
    /// they are FAIL verdicts; with <c>verdictFallback</c> their last explicit "verdict: PASS|FAIL" is read instead.
    /// </summary>
    public int NonConformingVerdicts => Volatile.Read(ref nonConforming);

    /// <summary>Non-conforming replies whose verdict the fallback read from an explicit "verdict: PASS|FAIL".</summary>
    public int FallbackVerdicts => Volatile.Read(ref fallbackRead);

    /// <summary>
    /// Replies the server aborted because the model kept repeating one token under greedy decoding ("token repeat limit
    /// reached"). Such a reply is the model failing to answer, not an infrastructure fault: a generation becomes a candidate
    /// without code, a verification a FAIL verdict. Counted for the run summary.
    /// </summary>
    public int AbortedReplies => Volatile.Read(ref aborted);

    /// <summary>Replies that reached the run's token bound (<c>done_reason</c> "length"); treated like an aborted reply.</summary>
    public int LengthLimitedReplies => Volatile.Read(ref lengthLimited);

    /// <summary>The text recorded for a generation at the token bound (it contains no code, so execution fails).</summary>
    public const string LengthLimitedGeneration = "[no answer: the reply reached the token limit]";

    /// <summary>The text recorded for an aborted generation (it contains no code, so execution fails).</summary>
    public const string AbortedGeneration = "[no answer: the server aborted a repetitive generation]";

    private async Task<(string Content, bool Aborted)> ChatAsync(string prompt, CancellationToken ct)
    {
        var (content, stop) = await ChatOnceAsync(prompt, ct).ConfigureAwait(false);
        return stop switch
        {
            Stop.Repetition => (AbortedGeneration, true),
            Stop.Length => (LengthLimitedGeneration, true),
            _ => (content, false),
        };
    }

    private enum Stop { None, Repetition, Length }

    private async Task<(string Content, Stop Stop)> ChatOnceAsync(string prompt, CancellationToken ct)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(timeout ?? TimeSpan.FromMilliseconds(120_000));
        var body = new JsonObject
        {
            ["model"] = model,
            ["messages"] = new JsonArray(new JsonObject { ["role"] = "user", ["content"] = prompt }),
            ["stream"] = false,
            ["options"] = new JsonObject { ["temperature"] = temperature, ["seed"] = seed ?? Backends.DeriveOllamaSeed(model, baseUrl) },
        };
        if (maxReplyTokens is { } cap)
            body["options"]!["num_predict"] = cap;
        if (numCtx is { } ctxTokens)
            body["options"]!["num_ctx"] = ctxTokens;   // newer Ollama servers otherwise load the model's full native context
        HttpResponseMessage res;
        try
        {
            res = await http.PostAsync(new Uri($"{baseUrl}/api/chat"), new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json"), cts.Token).ConfigureAwait(false);
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
        {
            throw new InvalidOperationException($"Ollama backend unreachable at {baseUrl}/api/chat — is the model server running? ({e.Message})", e);
        }
        using (res)
        {
            if (!res.IsSuccessStatusCode)
            {
                var error = await res.Content.ReadAsStringAsync(cts.Token).ConfigureAwait(false);
                if (error.Contains("token repeat limit", StringComparison.OrdinalIgnoreCase))
                {
                    Interlocked.Increment(ref aborted);
                    return ("", Stop.Repetition);
                }
                throw new InvalidOperationException($"Ollama backend returned HTTP {(int)res.StatusCode} {res.ReasonPhrase}");
            }
            var data = await res.Content.ReadFromJsonAsync<JsonObject>(cts.Token).ConfigureAwait(false);
            if (maxReplyTokens is not null && data?["done_reason"]?.GetValue<string>() == "length")
            {
                Interlocked.Increment(ref lengthLimited);
                return ("", Stop.Length);
            }
            return (data?["message"]?["content"]?.GetValue<string>() ?? "", Stop.None);
        }
    }

    /// <summary>The fixed prompt of the discarded warm-up request.</summary>
    public const string WarmUpPrompt = "Reply with the single word READY.";

    /// <summary>
    /// One request with the run's sampling options whose output is discarded. After a model load, Ollama's first greedy
    /// request can differ from all later ones (observed with qwen2.5-coder:1.5b on Ollama 0.35.1); warming up first makes
    /// every recorded request a "warm" one.
    /// </summary>
    public Task WarmUpAsync(CancellationToken cancellationToken = default) => ChatAsync(WarmUpPrompt, cancellationToken);   // output (or an abort) discarded

    public async Task<string> GenerateAsync(BenchTask task, GenerateContext ctx, CancellationToken cancellationToken = default)
    {
        var (content, wasAborted) = await ChatAsync(Backends.BuildGeneratePrompt(task, ctx), cancellationToken).ConfigureAwait(false);
        if (wasAborted)
            return content;   // AbortedGeneration or LengthLimitedGeneration
        return content.Length > 0 ? content : throw new InvalidOperationException("Ollama generate() returned an empty response");
    }

    public async Task<SelfVerifierVerdict> VerifyAsync(BenchTask task, string candidate, CancellationToken cancellationToken = default)
    {
        var code = Bench.ExtractCodeBlock(candidate) ?? candidate;
        var prompt = verifyTemplate == "B" ? Backends.BuildVerifyPromptB(task, code) : Backends.BuildVerifyPrompt(task, code);
        var (content, wasAborted) = await ChatAsync(prompt, cancellationToken).ConfigureAwait(false);
        if (wasAborted)
            return new SelfVerifierVerdict(false, 0.2, content == LengthLimitedGeneration ? "FAIL [the reply reached the token limit]" : "FAIL [the server aborted a repetitive reply]");
        if (content.Length == 0)
            throw new InvalidOperationException("Ollama verify() returned an empty response");
        var pass = ReadVerdict(content, verdictFallback, out var conforming, out var fallback);
        if (!conforming)
            Interlocked.Increment(ref nonConforming);
        if (fallback)
            Interlocked.Increment(ref fallbackRead);
        return new SelfVerifierVerdict(pass, pass ? 0.8 : 0.2, content.Length > 280 ? content[..280] : content, content.Length > 280 ? content : null);
    }

    /// <summary>
    /// The verdict rule fixed before the runs: a reply passes when it begins with PASS. A reply that begins with neither PASS
    /// nor FAIL is non-conforming; with <paramref name="fallback"/> its last explicit "verdict: PASS|FAIL" decides, and
    /// without one it stays a FAIL.
    /// </summary>
    public static bool ReadVerdict(string reply, bool fallback, out bool conforming, out bool readByFallback)
    {
        readByFallback = false;
        conforming = PassLine.IsMatch(reply) || FailLine.IsMatch(reply);
        if (conforming || !fallback)
            return PassLine.IsMatch(reply);
        var m = VerdictLine.Matches(reply);
        if (m.Count == 0)
            return false;
        readByFallback = true;
        return m[^1].Groups[1].Value.Equals("PASS", StringComparison.OrdinalIgnoreCase);
    }

    private static readonly System.Text.RegularExpressions.Regex PassLine = new(@"^\s*PASS\b", System.Text.RegularExpressions.RegexOptions.IgnoreCase | System.Text.RegularExpressions.RegexOptions.CultureInvariant);
    private static readonly System.Text.RegularExpressions.Regex FailLine = new(@"^\s*FAIL\b", System.Text.RegularExpressions.RegexOptions.IgnoreCase | System.Text.RegularExpressions.RegexOptions.CultureInvariant);
    private static readonly System.Text.RegularExpressions.Regex VerdictLine = new(@"verdict\W{0,3}\s*(PASS|FAIL)\b", System.Text.RegularExpressions.RegexOptions.IgnoreCase | System.Text.RegularExpressions.RegexOptions.CultureInvariant);

    /// <summary>The server version for the run summary, or null on any failure (a missing version never aborts a run).</summary>
    public static async Task<string?> VersionAsync(HttpClient http, string baseUrl, CancellationToken ct = default)
    {
        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(3000);
            var data = await http.GetFromJsonAsync<JsonObject>(new Uri($"{baseUrl}/api/version"), cts.Token).ConfigureAwait(false);
            return data?["version"]?.GetValue<string>();
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or System.Text.Json.JsonException)
        {
            return null;
        }
    }

    /// <summary>
    /// The digest of the model's weights as the server lists them (a tag such as "qwen2.5-coder:7b" can be re-pulled to other
    /// weights; the digest cannot), or null on any failure.
    /// </summary>
    public static async Task<string?> DigestAsync(HttpClient http, string baseUrl, string model, CancellationToken ct = default)
    {
        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(3000);
            var data = await http.GetFromJsonAsync<JsonObject>(new Uri($"{baseUrl}/api/tags"), cts.Token).ConfigureAwait(false);
            var name = model.Contains(':', StringComparison.Ordinal) ? model : model + ":latest";
            return (data?["models"] as JsonArray)?.OfType<JsonObject>()
                .FirstOrDefault(m => m["name"]?.GetValue<string>() == name || m["model"]?.GetValue<string>() == name)?["digest"]?.GetValue<string>();
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or System.Text.Json.JsonException or InvalidOperationException)
        {
            return null;
        }
    }
}
