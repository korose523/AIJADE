using System.Security.Cryptography;
using System.Text;

using Aijade.Research.RqC;

namespace Aijade.Research.SkillBench;

public sealed record PromptSize(int Utf16Units, int Utf8Bytes, string Sha256);
public sealed record PublicCaseFailure(int Index, string? Error, string? ActualPreview);
public sealed record PublicTaskCheck(
    string TaskId, int Passed, int Total, string? Error, double DurationMs,
    IReadOnlyList<PublicCaseFailure> Failures, string ManifestSha256,
    PromptSize Generation, PromptSize VerifierA, PromptSize VerifierB,
    PromptSize VerifierAWithStub, PromptSize VerifierBWithStub, int ReferenceCodeUtf8Bytes,
    bool ExpectedOutputNoninterference, string TokenizerStatus);

public static class PublicBankCheck
{
    public static IReadOnlyDictionary<string, string> BuildPrompts(PublicBenchBank bank, string taskId, IReadOnlyList<int>? visibleCases = null)
    {
        ArgumentNullException.ThrowIfNull(bank);
        var task = bank.ReadTask(taskId);
        var reference = bank.ReadReference(taskId);
        return BuildPrompts(task, reference, visibleCases);
    }

    public static IReadOnlyDictionary<string, string> BuildPrompts(BenchTask task, string reference, IReadOnlyList<int>? visibleCases)
    {
        ArgumentNullException.ThrowIfNull(task);
        return new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["generation"] = Backends.BuildGeneratePrompt(task, new GenerateContext(0)),
            ["verifierA"] = Backends.BuildVerifyPrompt(task, reference, visibleCases),
            ["verifierB"] = Backends.BuildVerifyPromptB(task, reference, visibleCases),
            ["verifierAWithStub"] = Backends.BuildVerifyPrompt(task, "function solve() {}", visibleCases),
            ["verifierBWithStub"] = Backends.BuildVerifyPromptB(task, "function solve() {}", visibleCases),
        };
    }

    public static bool CheckExpectedNoninterference(BenchTask task, string reference, IReadOnlyList<int> visibleCases)
    {
        var original = BuildPrompts(task, reference, visibleCases);
        var changed = task with { Tests = task.Tests.Select(test => test with { Expected = "'EXPECTED_SENTINEL_4f75'" }).ToArray() };
        var replaced = BuildPrompts(changed, reference, visibleCases);
        return original.All(pair => replaced[pair.Key] == pair.Value)
            && PromptExposure.Describe(task).InputSha256 == PromptExposure.Describe(changed).InputSha256;
    }

    public static PublicTaskCheck RunReference(PublicBenchBank bank, string taskId)
    {
        ArgumentNullException.ThrowIfNull(bank);
        var task = bank.ReadTask(taskId);
        var code = bank.ReadReference(taskId);
        var verdict = new Sandbox().RunTask(code, task);
        var generation = Backends.BuildGeneratePrompt(task, new GenerateContext(0));
        var a = Backends.BuildVerifyPrompt(task, code);
        var b = Backends.BuildVerifyPromptB(task, code);
        var replaced = task with
        {
            Tests = task.Tests.Select(test => test with { Expected = "'ORACLE_OUTPUT_SENTINEL_7d5a0d5e'" }).ToArray(),
        };
        var withheld = generation == Backends.BuildGeneratePrompt(replaced, new GenerateContext(0))
            && a == Backends.BuildVerifyPrompt(replaced, code)
            && b == Backends.BuildVerifyPromptB(replaced, code);
        return new PublicTaskCheck(taskId, verdict.Passed, verdict.Total, verdict.Error, verdict.DurationMs,
            verdict.Failures.Select(failure => new PublicCaseFailure(failure.Index, failure.Error,
                failure.Actual?.Length > 180 ? failure.Actual[..180] : failure.Actual)).ToArray(),
            bank.ManifestSha256, Measure(generation), Measure(a), Measure(b),
            Measure(Backends.BuildVerifyPrompt(task, "function solve() {}")),
            Measure(Backends.BuildVerifyPromptB(task, "function solve() {}")),
            Encoding.UTF8.GetByteCount(code), withheld, "NOT_MEASURED");
    }

    private static PromptSize Measure(string text)
    {
        var bytes = Encoding.UTF8.GetBytes(text);
        return new PromptSize(text.Length, bytes.Length, Convert.ToHexStringLower(SHA256.HashData(bytes)));
    }
}
