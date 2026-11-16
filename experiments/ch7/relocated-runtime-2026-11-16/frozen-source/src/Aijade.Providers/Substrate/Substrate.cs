using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Core.Js;

namespace Aijade.Providers.Substrate;

// The L0 model substrate. Every
// generation carries a run fingerprint (model identity + digest, complete sampling config, server version), sampling is
// never left to server defaults, research mode enforces greedy decoding, and a determinism audit with a positive control
// tells genuine greedy decoding from a server that silently ignores the sampling config.

public enum SubstrateMode
{
    Interactive,
    Research,
}

/// <summary>A complete sampling configuration; a partial one is refused rather than filled from server defaults.</summary>
public sealed record SamplingConfig(double Temperature, double Seed, double TopP, double TopK, double RepeatPenalty, double NumCtx, double NumPredict, bool Think)
{
    /// <summary>The interactive Qwythos preset.</summary>
    public static SamplingConfig QwythosInteractive { get; } = new(0.6, 42, 0.95, 20, 1.05, 32768, 2048, true);

    /// <summary>Greedy decoding for experiments.</summary>
    public static SamplingConfig Research { get; } = new(0, 42, 1, 1, 1, 32768, 2048, false);

    internal IEnumerable<(string Key, JsonValue Value)> Entries() =>
    [
        ("temperature", JsonValue.Create(Temperature)), ("seed", JsonValue.Create(Seed)), ("top_p", JsonValue.Create(TopP)), ("top_k", JsonValue.Create(TopK)),
        ("repeat_penalty", JsonValue.Create(RepeatPenalty)), ("num_ctx", JsonValue.Create(NumCtx)), ("num_predict", JsonValue.Create(NumPredict)), ("think", JsonValue.Create(Think)),
    ];

    /// <summary>The config as JSON, keys in the canonical order.</summary>
    public JsonObject ToJson()
    {
        var o = new JsonObject();
        foreach (var (k, v) in Entries())
            o[k] = v;
        return o;
    }

    /// <summary>This config with the given snake_case overrides applied ({...base, ...overrides}).</summary>
    public SamplingConfig With(JsonObject overrides)
    {
        double D(string k, double v) => overrides[k] is JsonValue x ? double.Parse(x.ToJsonString(), System.Globalization.CultureInfo.InvariantCulture) : v;
        return new SamplingConfig(D("temperature", Temperature), D("seed", Seed), D("top_p", TopP), D("top_k", TopK), D("repeat_penalty", RepeatPenalty),
            D("num_ctx", NumCtx), D("num_predict", NumPredict), overrides["think"] is JsonValue t ? t.GetValue<bool>() : Think);
    }
}

public sealed record ModelIdentity(string Tag, string? Digest = null, double? SizeBytes = null, string? Family = null, string? ParameterSize = null, string? Quantization = null);

public sealed record RunFingerprint(string Schema, SubstrateMode Mode, ModelIdentity Model, SamplingConfig Sampling, string SamplingHash, string? ServerVersion, string Fingerprint);

public enum ChatRole
{
    System,
    User,
    Assistant,
}

public sealed record ChatMessage(ChatRole Role, string Content);

public sealed record GenerateOptions(IReadOnlyList<ChatMessage> Messages, SamplingConfig? Sampling = null, bool Json = false);

public sealed record GenerateResult(string Text, RunFingerprint Fingerprint, string Model, string CreatedAt, double? TotalDurationNs = null, double? EvalCount = null, double? PromptEvalCount = null);

public interface ISubstrate
{
    Task<ModelIdentity> IdentityAsync(CancellationToken cancellationToken = default);

    Task<RunFingerprint> FingerprintAsync(SamplingConfig? sampling = null, CancellationToken cancellationToken = default);

    Task<GenerateResult> GenerateAsync(GenerateOptions options, CancellationToken cancellationToken = default);
}

public sealed class SamplingException(string message) : Exception(message);

public static class SubstrateFingerprint
{
    public const string Schema = "aijade.substrate/1";

    /// <summary>FNV-1a over "temperature=…;seed=…;…" in the fixed key order (independent of how the config was built).</summary>
    public static string HashSampling(SamplingConfig s) => JsFormat.Fnv1a(string.Join(";",
        $"temperature={JsFormat.Number(s.Temperature)}", $"seed={JsFormat.Number(s.Seed)}", $"top_p={JsFormat.Number(s.TopP)}", $"top_k={JsFormat.Number(s.TopK)}",
        $"repeat_penalty={JsFormat.Number(s.RepeatPenalty)}", $"num_ctx={JsFormat.Number(s.NumCtx)}", $"num_predict={JsFormat.Number(s.NumPredict)}",
        $"think={(s.Think ? "true" : "false")}"));

    public static void AssertComplete(SamplingConfig s)
    {
        var bad = new (string Key, double Value)[] { ("temperature", s.Temperature), ("seed", s.Seed), ("top_p", s.TopP), ("top_k", s.TopK), ("repeat_penalty", s.RepeatPenalty),
            ("num_ctx", s.NumCtx), ("num_predict", s.NumPredict) }.Where(e => double.IsNaN(e.Value)).Select(e => e.Key).ToList();
        if (bad.Count > 0)
        {
            throw new SamplingException($"Sampling config is incomplete; missing or wrong-typed: {string.Join(", ", bad)}. "
                + "Refusing to fall back to server defaults — that is what makes runs unreproducible.");
        }
    }

    public static void AssertResearchMode(SamplingConfig s)
    {
        if (s.Temperature != 0)
        {
            throw new SamplingException($"research mode requires temperature=0 (greedy decoding) for reproducibility; got {JsFormat.Number(s.Temperature)}. "
                + "Use mode \"interactive\" if you really want sampling.");
        }
    }

    /// <summary>FNV-1a of "schema|mode|tag[@digest]|samplingHash|serverVersion": one id for "this exact substrate".</summary>
    public static RunFingerprint Build(SubstrateMode mode, ModelIdentity model, SamplingConfig sampling, string? serverVersion = null)
    {
        AssertComplete(sampling);
        var samplingHash = HashSampling(sampling);
        var identity = model.Digest is { Length: > 0 } d ? $"{model.Tag}@{d}" : model.Tag;
        return new RunFingerprint(Schema, mode, model, sampling, samplingHash, serverVersion,
            JsFormat.Fnv1a($"{Schema}|{WireName.Of(mode)}|{identity}|{samplingHash}|{serverVersion ?? "unknown"}"));
    }
}

/// <summary>An Ollama substrate. The identity (tag, digest, details) and server version are resolved once and cached.</summary>
public sealed class OllamaSubstrate : ISubstrate
{
    private readonly HttpClient _http;
    private readonly SamplingConfig _sampling;
    private readonly TimeSpan _timeout;
    private Task<ModelIdentity>? _identity;
    private Task<string?>? _serverVersion;

    public OllamaSubstrate(HttpClient http, string model, SubstrateMode mode = SubstrateMode.Interactive, SamplingConfig? sampling = null, string? baseUrl = null, TimeSpan? timeout = null)
    {
        if (string.IsNullOrWhiteSpace(model))
            throw new SamplingException("createOllamaSubstrate: \"model\" is required");
        _http = http;
        Model = model;
        Mode = mode;
        BaseUrl = (baseUrl ?? "http://127.0.0.1:11434").TrimEnd('/');
        _timeout = timeout ?? TimeSpan.FromMilliseconds(120_000);
        _sampling = sampling ?? (mode == SubstrateMode.Research ? SamplingConfig.Research : SamplingConfig.QwythosInteractive);
        SubstrateFingerprint.AssertComplete(_sampling);
        if (mode == SubstrateMode.Research)
            SubstrateFingerprint.AssertResearchMode(_sampling);
    }

    public string Model { get; }
    public SubstrateMode Mode { get; }
    public string BaseUrl { get; }

    private SamplingConfig Effective(SamplingConfig? over)
    {
        var s = over ?? _sampling;
        SubstrateFingerprint.AssertComplete(s);
        if (Mode == SubstrateMode.Research)
            SubstrateFingerprint.AssertResearchMode(s);
        return s;
    }

    public Task<ModelIdentity> IdentityAsync(CancellationToken cancellationToken = default) => _identity ??= ResolveIdentityAsync(cancellationToken);

    private async Task<ModelIdentity> ResolveIdentityAsync(CancellationToken ct)
    {
        var tags = TryJsonAsync(() => _http.GetAsync(new Uri($"{BaseUrl}/api/tags"), ct), TimeSpan.FromSeconds(10));
        var show = TryJsonAsync(() => _http.PostAsync(new Uri($"{BaseUrl}/api/show"), Body(new JsonObject { ["model"] = Model }), ct), TimeSpan.FromSeconds(10));
        await Task.WhenAll(tags, show).ConfigureAwait(false);
        var candidates = new HashSet<string>(StringComparer.Ordinal) { Model, $"{Model}:latest", Model.EndsWith(":latest", StringComparison.Ordinal) ? Model[..^7] : Model };
        var hit = (tags.Result?["models"] as JsonArray)?.OfType<JsonObject>().FirstOrDefault(m => m["name"]?.GetValue<string>() is { } n && candidates.Contains(n));
        var details = show.Result?["details"];
        return new ModelIdentity(Model, hit?["digest"]?.GetValue<string>(), hit?["size"]?.GetValue<double>(), details?["family"]?.GetValue<string>(),
            details?["parameter_size"]?.GetValue<string>(), details?["quantization_level"]?.GetValue<string>());
    }

    private static StringContent Body(JsonObject o) => new(o.ToJsonString(), Encoding.UTF8, "application/json");

    /// <summary>The JSON body of a successful call, or null on any failure (identity details are best-effort).</summary>
    private static async Task<JsonObject?> TryJsonAsync(Func<Task<HttpResponseMessage>> call, TimeSpan timeout)
    {
        try
        {
            using var res = await call().WaitAsync(timeout).ConfigureAwait(false);
            return res.IsSuccessStatusCode ? await res.Content.ReadFromJsonAsync<JsonObject>().ConfigureAwait(false) : null;
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or TimeoutException or System.Text.Json.JsonException)
        {
            return null;
        }
    }

    public async Task<RunFingerprint> FingerprintAsync(SamplingConfig? sampling = null, CancellationToken cancellationToken = default)
    {
        var effective = Effective(sampling);
        _serverVersion ??= ResolveServerVersionAsync(cancellationToken);
        var identity = await IdentityAsync(cancellationToken).ConfigureAwait(false);
        return SubstrateFingerprint.Build(Mode, identity, effective, await _serverVersion.ConfigureAwait(false));
    }

    private async Task<string?> ResolveServerVersionAsync(CancellationToken ct) =>
        (await TryJsonAsync(() => _http.GetAsync(new Uri($"{BaseUrl}/api/version"), ct), TimeSpan.FromSeconds(5)).ConfigureAwait(false))?["version"]?.GetValue<string>();

    public async Task<GenerateResult> GenerateAsync(GenerateOptions options, CancellationToken cancellationToken = default)
    {
        if (options.Messages.Count == 0)
            throw new SamplingException("generate(): at least one message is required");
        var effective = Effective(options.Sampling);
        var samplingJson = effective.ToJson();
        samplingJson.Remove("think");
        var body = new JsonObject
        {
            ["model"] = Model,
            ["messages"] = new JsonArray(options.Messages.Select(m => (JsonNode?)new JsonObject { ["role"] = WireName.Of(m.Role), ["content"] = m.Content }).ToArray()),
            ["stream"] = false,
            ["think"] = effective.Think,
            ["options"] = samplingJson,
        };
        if (options.Json)
            body["format"] = "json";
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        cts.CancelAfter(_timeout);
        HttpResponseMessage res;
        try
        {
            res = await _http.PostAsync(new Uri($"{BaseUrl}/api/chat"), new StringContent(JsFormat.Stringify(body), Encoding.UTF8, "application/json"), cts.Token).ConfigureAwait(false);
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
        {
            throw new SamplingException($"Ollama unreachable at {BaseUrl}/api/chat — is the server running and is \"{Model}\" pulled? ({e.Message})");
        }
        using (res)
        {
            if (!res.IsSuccessStatusCode)
                throw new SamplingException($"Ollama returned HTTP {(int)res.StatusCode} {res.ReasonPhrase}");
            var data = await res.Content.ReadFromJsonAsync<JsonObject>(cts.Token).ConfigureAwait(false);
            var text = data?["message"]?["content"]?.GetValue<string>() ?? "";
            if (text.Length == 0)
                throw new SamplingException("Ollama returned an empty completion — refusing to fabricate a result");
            return new GenerateResult(text, await FingerprintAsync(effective, cancellationToken).ConfigureAwait(false), data?["model"]?.GetValue<string>() ?? Model,
                data?["created_at"]?.GetValue<string>() ?? DateTimeOffset.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'", System.Globalization.CultureInfo.InvariantCulture),
                data?["total_duration"]?.GetValue<double>(), data?["eval_count"]?.GetValue<double>(), data?["prompt_eval_count"]?.GetValue<double>());
        }
    }
}
