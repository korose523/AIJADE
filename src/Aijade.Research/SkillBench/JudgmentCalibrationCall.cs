using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Research.RqC;

namespace Aijade.Research.SkillBench;

/// <summary>One actual guarded verifier call; an external controller supplies the fixed order and resource limits.</summary>
public static class JudgmentCalibrationCall
{
    public static async Task<int> RunAsync(string bankPath, string source, string taskId, string candidatePath,
        string candidateSha256, string policyPath, string template, string baseUrl, string output, int completed,
        CancellationToken ct = default)
    {
        if (completed is < 0 or >= 32 || template is not ("A" or "B"))throw new ArgumentException("Invalid fixed calibration slot.");
        if (Directory.Exists(output))throw new IOException("Use a fresh calibration observation directory.");
        if (PublicBenchBank.FileSha256(candidatePath) != candidateSha256)throw new InvalidDataException("The frozen candidate changed.");
        var bank = PublicBenchBank.Load(bankPath);
        var task = source == "builtin" ? Bench.Tasks.Single(task => task.Id == taskId)
            : source == "public" ? bank.ReadTask(taskId) : throw new InvalidDataException("Unknown task source.");
        var policy = source == "builtin" ? PublicRequestPolicy.Load(policyPath, Bench.ManifestSha256, Bench.Tasks)
            : PublicRequestPolicy.Load(policyPath, bank);
        if (policy.KeepAliveSeconds != 0 || policy.Exposure.Scenario.Id != "compact8k")
            throw new InvalidDataException("Calibration requires the fixed 8k cold-request policy.");
        Directory.CreateDirectory(output);
        var watch = Stopwatch.StartNew();
        using var http = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };
        using var budget = new RequestBudget(policy, new ExternalPromptCounter(policy, Path.Combine(output, "counter.stderr.log")), output, 32)
            { CompletedSteps = completed };
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);timeout.CancelAfter(TimeSpan.FromSeconds(180));
        try
        {
            string? version, digest;
            try
            {
                version = await OllamaBackend.VersionAsync(http, baseUrl, timeout.Token).ConfigureAwait(false);
                digest = await OllamaBackend.DigestAsync(http, baseUrl, policy.Model, timeout.Token).ConfigureAwait(false);
            }
            catch (Exception error) when (error is HttpRequestException or IOException or InvalidOperationException or JsonException or OperationCanceledException)
            { throw budget.Fail("MODEL_METADATA_ERROR", "metadata", taskId, error.Message, error); }
            File.WriteAllText(Path.Combine(output, "model-identity.json"), JsonSerializer.Serialize(new
            {
                model = policy.Model, digest, version, expectedDigest = policy.ModelManifestSha256,
                source, taskId, candidateSha256, policySha256 = policy.Sha256,
                instructionVersion = policy.Exposure.VerifierInstructionVersion, template,
            }));
            if (digest != policy.ModelManifestSha256)
                throw budget.Fail("MODEL_IDENTITY_MISMATCH", "metadata", taskId, "The private service model differs from the fixed policy.");
            var backend = new OllamaBackend(http, policy.Model, baseUrl, temperature: 0, seed: 3759066737,
                timeout: TimeSpan.FromSeconds(180), verifyTemplate: template, requestBudget: budget);
            var code = File.ReadAllText(candidatePath);
            var verdict = await backend.VerifyAsync(task, code, timeout.Token).ConfigureAwait(false);
            File.WriteAllText(Path.Combine(output, "observation.json"), new JsonObject
            {
                ["schema"] = "aijade.p2.constructed-judgment-observation.v1", ["status"] = "OBSERVED",
                ["source"] = source, ["taskId"] = taskId, ["model"] = policy.Model, ["template"] = template,
                ["instructionVersion"] = policy.Exposure.VerifierInstructionVersion,
                ["candidateSha256"] = candidateSha256, ["policySha256"] = policy.Sha256,
                ["pass"] = verdict.Pass, ["rationale"] = verdict.Rationale, ["fullReply"] = verdict.FullReply,
                ["elapsedSeconds"] = watch.Elapsed.TotalSeconds, ["requestsChecked"] = budget.RequestsChecked,
                ["primaryExperiment"] = false, ["completedBeforeThisObservation"] = completed,
            }.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }
        catch (RequestBudgetFailure error)
        {
            Console.Error.WriteLine(error.Status + ": " + error.Message);
            return 1;
        }
    }
}
