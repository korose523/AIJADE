using System.Diagnostics;
using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

using Aijade.Research.SkillBench;

namespace Aijade.Research.RqC;

public sealed record TokenCounterSpec(string Executable, string ExecutableSha256, string Script, string ScriptSha256,
    string Config, string ConfigSha256);

/// <summary>One opt-in, hash-bound request policy; historical runs use none.</summary>
public sealed class PublicRequestPolicy
{
    public const string Schema = "aijade.p2a.request-policy.v1";
    private sealed record Payload(string Schema, string ExposureFile, string ExposureSha256, string Model,
        string ModelManifestSha256, string TemplateSha256, string SystemSha256, TokenCounterSpec Counter);
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web) { UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow };

    public string Sha256 { get; }
    public PromptExposure Exposure { get; }
    public string Model { get; }
    public string ModelManifestSha256 { get; }
    public string TemplateSha256 { get; }
    public string SystemSha256 { get; }
    public TokenCounterSpec Counter { get; }

    private PublicRequestPolicy(string sha, PromptExposure exposure, Payload data, string folder)
    {
        Sha256 = sha;
        Exposure = exposure;
        Model = data.Model;
        ModelManifestSha256 = data.ModelManifestSha256;
        TemplateSha256 = data.TemplateSha256;
        SystemSha256 = data.SystemSha256;
        Counter = data.Counter with
        {
            Executable = Path.GetFullPath(data.Counter.Executable, folder),
            Script = Path.GetFullPath(data.Counter.Script, folder),
            Config = Path.GetFullPath(data.Counter.Config, folder),
        };
    }

    public static PublicRequestPolicy Load(string path, PublicBenchBank bank, string? expectedSha256 = null)
    {
        var sha = PublicBenchBank.FileSha256(path);
        if (expectedSha256 is not null && expectedSha256 != sha)
            throw new InvalidDataException("The request policy has changed.");
        Payload data;
        try { data = JsonSerializer.Deserialize<Payload>(File.ReadAllBytes(path), Json) ?? throw new InvalidDataException("Empty request policy."); }
        catch (JsonException error) { throw new InvalidDataException("Invalid request-policy JSON.", error); }
        if (data.Schema != Schema || data.Counter is null || string.IsNullOrWhiteSpace(data.Model)
            || !new[] { data.ExposureSha256, data.ModelManifestSha256, data.TemplateSha256, data.SystemSha256,
                data.Counter.ExecutableSha256, data.Counter.ScriptSha256, data.Counter.ConfigSha256 }.All(PromptExposure.IsHash)
            || new[] { data.ExposureFile, data.Counter.Executable, data.Counter.Script, data.Counter.Config }.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException("Invalid request-policy identities or paths.");
        var folder = Path.GetDirectoryName(Path.GetFullPath(path))!;
        var exposure = PromptExposure.Load(Path.GetFullPath(data.ExposureFile, folder), bank, data.ExposureSha256);
        if (!exposure.ModelManifestSha256ByName.TryGetValue(data.Model, out var model) || model != data.ModelManifestSha256)
            throw new InvalidDataException("The policy model does not belong to its exposure profile.");
        var result = new PublicRequestPolicy(sha, exposure, data, folder);
        foreach (var pair in new[] { (result.Counter.Executable, result.Counter.ExecutableSha256),
            (result.Counter.Script, result.Counter.ScriptSha256), (result.Counter.Config, result.Counter.ConfigSha256) })
            if (PublicBenchBank.FileSha256(pair.Item1) != pair.Item2)
                throw new InvalidDataException("A request-policy counter input has changed.");
        return result;
    }
}

public sealed record ExactPromptCount(int InputTokens, string RawSha256, string ChatSha256, string TokenIdsSha256, bool CrossEngineAgreement);

public interface IExactPromptCounter : IDisposable
{
    Task<ExactPromptCount> CountAsync(string prompt, CancellationToken cancellationToken = default);
}

/// <summary>Persistent local tokenizer adapter. It cannot send a model inference request.</summary>
public sealed class ExternalPromptCounter(PublicRequestPolicy policy, string stderrPath) : IExactPromptCounter
{
    private Process? _process;
    private Task<string>? _stderr;
    private bool _ready;
    private bool _disposed;
    private int _sequence;
    private readonly SemaphoreSlim _gate = new(1, 1);

    private static async Task<string> ReadLineAsync(StreamReader reader, CancellationToken ct)
    {
        var line = new StringBuilder();
        var buffer = new char[1];
        while (line.Length <= 65536)
        {
            var n = await reader.ReadAsync(buffer.AsMemory(), ct).ConfigureAwait(false);
            if (n == 0)
                throw new InvalidDataException("The tokenizer adapter ended before a response.");
            if (buffer[0] == '\n')
                return line.ToString();
            line.Append(buffer[0]);
        }
        throw new InvalidDataException("The tokenizer response exceeds the bounded JSONL transport.");
    }

    private async Task StartAsync(CancellationToken ct)
    {
        if (_ready)
            return;
        var start = new ProcessStartInfo(policy.Counter.Executable)
        {
            UseShellExecute = false, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = new UTF8Encoding(false, true),
        };
        start.ArgumentList.Add(policy.Counter.Script);
        start.ArgumentList.Add("--config");
        start.ArgumentList.Add(policy.Counter.Config);
        _process = Process.Start(start) ?? throw new IOException("Could not start the local tokenizer adapter.");
        _stderr = _process.StandardError.ReadToEndAsync(ct);
        var ready = JsonNode.Parse(await ReadLineAsync(_process.StandardOutput, ct).ConfigureAwait(false))?.AsObject()
            ?? throw new InvalidDataException("Missing tokenizer identity.");
        var matches = ready["schema"]?.GetValue<string>() == "aijade.p2a.token-counter.ready.v1"
            && ready["configSha256"]?.GetValue<string>() == policy.Counter.ConfigSha256
            && ready["scriptSha256"]?.GetValue<string>() == policy.Counter.ScriptSha256
            && ready["modelManifestSha256"]?.GetValue<string>() == policy.ModelManifestSha256
            && ready["templateSha256"]?.GetValue<string>() == policy.TemplateSha256
            && ready["systemSha256"]?.GetValue<string>() == policy.SystemSha256;
        ready["policyIdentityMatched"] = matches;
        File.WriteAllText(Path.Combine(Path.GetDirectoryName(Path.GetFullPath(stderrPath))!, "token-counter.identity.json"), ready.ToJsonString());
        if (!matches)
            throw new InvalidDataException("The local tokenizer identity does not match the request policy.");
        _ready = true;
    }

    public async Task<ExactPromptCount> CountAsync(string prompt, CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        await _gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (Encoding.UTF8.GetByteCount(prompt) > 1048576)
                throw new InvalidDataException("The prompt exceeds the fixed 1 MiB transport bound.");
            await StartAsync(cancellationToken).ConfigureAwait(false);
            var id = ++_sequence;
            var input = new JsonObject { ["id"] = id, ["prompt"] = prompt };
            await _process!.StandardInput.WriteLineAsync(input.ToJsonString().AsMemory(), cancellationToken).ConfigureAwait(false);
            await _process.StandardInput.FlushAsync(cancellationToken).ConfigureAwait(false);
            var reply = JsonNode.Parse(await ReadLineAsync(_process.StandardOutput, cancellationToken).ConfigureAwait(false))?.AsObject()
                ?? throw new InvalidDataException("Invalid tokenizer response.");
            if (reply["schema"]?.GetValue<string>() != "aijade.p2a.token-counter.count.v1" || reply["id"]?.GetValue<int>() != id)
                throw new InvalidDataException("The tokenizer response is missing or out of order.");
            var result = new ExactPromptCount(reply["inputTokens"]?.GetValue<int>() ?? throw new InvalidDataException("Missing token count."),
                reply["rawSha256"]?.GetValue<string>() ?? throw new InvalidDataException("Missing raw identity."),
                reply["chatSha256"]?.GetValue<string>() ?? throw new InvalidDataException("Missing chat identity."),
                reply["tokenIdsSha256"]?.GetValue<string>() ?? throw new InvalidDataException("Missing token identity."),
                reply["crossEngineAgreement"]?.GetValue<bool>() ?? false);
            if (result.InputTokens is < 0 or > 1048576 || result.RawSha256 != PromptExposure.Hash(prompt)
                || !PromptExposure.IsHash(result.ChatSha256) || !PromptExposure.IsHash(result.TokenIdsSha256) || !result.CrossEngineAgreement)
                throw new InvalidDataException("The tokenizer count, bytes or cross-engine check is invalid.");
            return result;
        }
        catch
        {
            if (_process is { HasExited: false })
                _process.Kill(entireProcessTree: true);
            throw;
        }
        finally { _gate.Release(); }
    }

    public void Dispose()
    {
        if (_disposed)
            return;
        _disposed = true;
        if (_process is not null)
        {
            if (!_process.HasExited)
            {
                _process.StandardInput.Close();
                if (!_process.WaitForExit(3000))
                    _process.Kill(entireProcessTree: true);
            }
            if (_stderr is { IsCompletedSuccessfully: true })
                File.WriteAllText(stderrPath, _stderr.Result);
            _process.Dispose();
        }
        _gate.Dispose();
    }
}

public sealed record BudgetedRequest(int Id, int ReplyTokens, ExactPromptCount Count);

public sealed class RequestBudgetFailure(string status, string message, Exception? inner = null) : InvalidOperationException(message, inner)
{
    public string Status { get; } = status;
}

/// <summary>Checks and persists the exact request before dispatch; an invalid request leaves no verifier verdict.</summary>
public sealed class RequestBudget : IDisposable
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private readonly IExactPromptCounter _counter;
    private readonly StreamWriter _ledger;
    private readonly string _incompletePath;
    private readonly long _plannedSteps;
    private int _requests;
    private bool _disposed;
    public PublicRequestPolicy Policy { get; }
    public int CompletedSteps { get; set; }
    public int RequestsChecked => _requests;

    public RequestBudget(PublicRequestPolicy policy, IExactPromptCounter counter, string folder, long plannedSteps)
    {
        Policy = policy;
        _counter = counter;
        _plannedSteps = plannedSteps;
        _incompletePath = Path.Combine(folder, "incomplete-run.json");
        _ledger = new StreamWriter(Path.Combine(folder, "requests.jsonl"), false, new UTF8Encoding(false));
        Write(new { kind = "start", policySha256 = policy.Sha256, exposureSha256 = policy.Exposure.Sha256,
            scenario = policy.Exposure.Scenario, plannedSteps, model = policy.Model });
    }

    private void Write(object value)
    {
        _ledger.WriteLine(JsonSerializer.Serialize(value, Json));
        _ledger.Flush();
    }

    public RequestBudgetFailure Fail(string status, string stage, string? taskId, string detail, Exception? error = null)
    {
        var record = new { kind = "failure", status, stage, taskId, detail, policySha256 = Policy.Sha256,
            exposureSha256 = Policy.Exposure.Sha256, plannedSteps = _plannedSteps, completedSteps = CompletedSteps,
            notCompletedSteps = _plannedSteps - CompletedSteps, verdict = (bool?)null, requestsChecked = _requests };
        Write(record);
        File.WriteAllText(_incompletePath, JsonSerializer.Serialize(record, Json));
        return new RequestBudgetFailure(status, $"{status}: {detail}", error);
    }

    public async Task<BudgetedRequest> CheckAsync(string prompt, string stage, string? taskId, CancellationToken ct)
    {
        if (stage is not ("warmup" or "generation" or "verification"))
            throw Fail("POLICY_STAGE_ERROR", stage, taskId, "Unknown request stage.");
        var id = ++_requests;
        ExactPromptCount count;
        try { count = await _counter.CountAsync(prompt, ct).ConfigureAwait(false); }
        catch (Exception error) when (error is IOException or InvalidDataException or InvalidOperationException or JsonException or OperationCanceledException or FormatException or OverflowException or DecoderFallbackException)
        {
            Write(new { kind = "request", id, stage, taskId, stepSlot = stage == "warmup" ? (int?)null : CompletedSteps,
                rawPrompt = prompt, rawSha256 = PromptExposure.Hash(prompt), status = "COUNTER_ERROR", verdict = (bool?)null });
            throw Fail("COUNTER_ERROR", stage, taskId, error.Message, error);
        }
        if (count.RawSha256 != PromptExposure.Hash(prompt) || count.InputTokens is < 0 or > 1048576 || !count.CrossEngineAgreement
            || !PromptExposure.IsHash(count.ChatSha256) || !PromptExposure.IsHash(count.TokenIdsSha256))
        {
            Write(new { kind = "request", id, stage, taskId, rawPrompt = prompt, rawSha256 = PromptExposure.Hash(prompt),
                reportedRawSha256 = count.RawSha256, inputTokens = count.InputTokens, status = "COUNTER_ERROR", verdict = (bool?)null });
            throw Fail("COUNTER_ERROR", stage, taskId, "Counter identity or token agreement failed.");
        }
        var cap = stage == "verification" ? Policy.Exposure.Scenario.VerificationReplyTokens : Policy.Exposure.Scenario.GenerationReplyTokens;
        var fits = (long)count.InputTokens + cap <= Policy.Exposure.Scenario.ContextTokens;
        Write(new { kind = "request", id, stage, taskId, stepSlot = stage == "warmup" ? (int?)null : CompletedSteps,
            rawPrompt = prompt, rawSha256 = count.RawSha256, chatSha256 = count.ChatSha256, tokenIdsSha256 = count.TokenIdsSha256,
            inputTokens = count.InputTokens, replyTokens = cap, contextTokens = Policy.Exposure.Scenario.ContextTokens,
            crossEngineAgreement = count.CrossEngineAgreement, status = fits ? "READY_TO_SEND" : "CONTEXT_OVERFLOW", verdict = (bool?)null });
        if (!fits)
            throw Fail("CONTEXT_OVERFLOW", stage, taskId, string.Create(CultureInfo.InvariantCulture,
                $"Input {count.InputTokens} + reply reserve {cap} exceeds context {Policy.Exposure.Scenario.ContextTokens}. No HTTP chat request was sent."));
        return new BudgetedRequest(id, cap, count);
    }

    public void RecordResponse(BudgetedRequest request, string rawResponse) =>
        Write(new { kind = "response", id = request.Id, rawResponse, sha256 = PromptExposure.Hash(rawResponse) });

    public void Dispose()
    {
        if (_disposed)
            return;
        _disposed = true;
        _ledger.Dispose();
        _counter.Dispose();
    }
}
