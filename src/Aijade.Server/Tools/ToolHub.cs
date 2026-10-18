using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

using Aijade.Server.Auth;
using Aijade.Server.Infrastructure;
using Aijade.Server.Product;
using Aijade.Server.V9;

using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;

using Npgsql;

namespace Aijade.Server.Tools;

// Tools the companion can use while it answers: external MCP servers (HTTP or a local process) and built-in integrations
// (Home Assistant, Xiaomi Mi Home, Factorio). Administrators configure them in config_kv["tools.config"]:
//   { "allowAllUsers": false,
//     "providers": { "<id>": { "kind": "mcp-http" | "mcp-stdio" | "homeassistant" | "xiaomi" | "factorio", ... } } }
// Secrets (token, password, header and environment values) are encrypted at rest and masked when read back, like gateway
// keys. Tools can switch lights or type on a computer, so by default only administrators may use them.

public sealed record ToolSpec(string Name, string Description, JsonObject Parameters);

public sealed record ToolCallOutcome(string Content, bool IsError);

/// <summary>One configured source of tools. Names are the provider's own; the hub prefixes them with the provider id.</summary>
public interface IToolProvider : IAsyncDisposable
{
    Task<IReadOnlyList<ToolSpec>> ListAsync(CancellationToken ct);

    Task<ToolCallOutcome> CallAsync(string tool, JsonObject arguments, CancellationToken ct);
}

public sealed class ToolsConfigStore(NpgsqlDataSource db, IDataProtectionProvider dp)
{
    public const string ConfigKey = "tools.config";
    private const string Purpose = "Aijade.ToolSecret.v1";
    private static readonly string[] SecretFields = ["token", "password"];
    private static readonly string[] SecretMaps = ["headers", "env"];

    private IDataProtector Protector => dp.CreateProtector(Purpose);

    private async Task<JsonObject?> RawAsync(CancellationToken ct)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        var rows = await Sql.QueryAsync(conn, null, "SELECT value::text FROM config_kv WHERE key = $1", r => r.GetString(0), ct, Sql.Text(ConfigKey)).ConfigureAwait(false);
        return rows.Count == 0 ? null : JsonNode.Parse(rows[0]) as JsonObject;
    }

    private static void EachSecret(JsonObject doc, Func<string, string> transform)
    {
        foreach (var (_, p) in doc["providers"] as JsonObject ?? [])
        {
            if (p is not JsonObject provider)
                continue;
            foreach (var field in SecretFields)
            {
                if (provider[field] is JsonValue v && v.TryGetValue<string>(out var s) && s.Length > 0)
                    provider[field] = transform(s);
            }
            foreach (var map in SecretMaps)
            {
                if (provider[map] is not JsonObject values)
                    continue;
                foreach (var key in values.Select(kv => kv.Key).ToList())
                {
                    if (values[key] is JsonValue v && v.TryGetValue<string>(out var s))
                        values[key] = transform(s);
                }
            }
        }
    }

    /// <summary>The configuration with secrets decrypted (for the hub).</summary>
    public async Task<JsonObject> LoadAsync(CancellationToken ct)
    {
        var doc = await RawAsync(ct).ConfigureAwait(false) ?? new JsonObject { ["providers"] = new JsonObject() };
        EachSecret(doc, s => Protector.Unprotect(s));
        return doc;
    }

    public static string Mask(string secret) => $"…{(secret.Length > 4 ? secret[^4..] : "")}";

    /// <summary>For administrators: secrets shown as "…" plus their last four characters.</summary>
    public async Task<JsonObject> MaskedAsync(CancellationToken ct)
    {
        var doc = await LoadAsync(ct).ConfigureAwait(false);
        EachSecret(doc, Mask);
        return doc;
    }

    /// <summary>Save; a secret still in its masked form keeps the stored value it stands for.</summary>
    public async Task SaveAsync(JsonObject doc, CancellationToken ct)
    {
        var current = await LoadAsync(ct).ConfigureAwait(false);
        var stored = (JsonObject)doc.DeepClone();
        foreach (var (id, p) in stored["providers"] as JsonObject ?? [])
        {
            if (p is not JsonObject provider || current["providers"]?[id] is not JsonObject before)
                continue;
            foreach (var field in SecretFields)
            {
                if (provider[field] is JsonValue v && v.TryGetValue<string>(out var s) && s.StartsWith('…') && before[field] is JsonValue old && Mask(old.GetValue<string>()) == s)
                    provider[field] = old.GetValue<string>();
            }
            foreach (var map in SecretMaps)
            {
                if (provider[map] is not JsonObject values || before[map] is not JsonObject oldValues)
                    continue;
                foreach (var key in values.Select(kv => kv.Key).ToList())
                {
                    if (values[key] is JsonValue v && v.TryGetValue<string>(out var s) && s.StartsWith('…') && oldValues[key] is JsonValue old && Mask(old.GetValue<string>()) == s)
                        values[key] = old.GetValue<string>();
                }
            }
        }
        EachSecret(stored, s => s.StartsWith('…') ? throw ApiException.BadRequest("a masked secret does not match the stored one; enter it in full", "INVALID_REQUEST") : Protector.Protect(s));
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await Sql.ExecAsync(conn, null, "INSERT INTO config_kv (key, value) VALUES ($1,$2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()", ct,
            Sql.Text(ConfigKey), Sql.Jsonb(stored)).ConfigureAwait(false);
    }
}

/// <summary>
/// Builds the configured providers (once per configuration version), lists their tools under "provider__tool" names
/// and routes calls. A provider that fails to start or list is skipped and reported, never fatal.
/// </summary>
public sealed partial class ToolHub(ToolsConfigStore store, IHttpClientFactory http, TimeProvider time) : IAsyncDisposable
{
    public const string HttpClientName = "tools";
    public const int MaxResultChars = 16_000;

    [GeneratedRegex("^[a-z][a-z0-9-]{0,23}$")]
    private static partial Regex ProviderId();

    private readonly SemaphoreSlim gate = new(1, 1);
    private string? version;
    private Dictionary<string, IToolProvider> providers = new(StringComparer.Ordinal);

    public IReadOnlyDictionary<string, string> Problems { get; private set; } = new Dictionary<string, string>();

    /// <summary>Reject a configuration the hub could not use (called by the admin editor before saving).</summary>
    public static void Validate(JsonObject doc)
    {
        foreach (var (id, p) in doc["providers"] as JsonObject ?? [])
        {
            if (!ProviderId().IsMatch(id))
                throw ApiException.BadRequest($"provider id '{id}' must be lower-case letters, digits and '-', starting with a letter (max 24)", "INVALID_REQUEST");
            var kind = p?["kind"]?.GetValue<string>();
            switch (kind)
            {
                case "mcp-http" or "homeassistant":
                    if (!Uri.TryCreate(p!["url"]?.GetValue<string>(), UriKind.Absolute, out _))
                        throw ApiException.BadRequest($"providers.{id}.url must be an absolute URL", "INVALID_REQUEST");
                    break;
                case "mcp-stdio":
                    if (p!["command"]?.GetValue<string>() is not { Length: > 0 })
                        throw ApiException.BadRequest($"providers.{id}.command is required", "INVALID_REQUEST");
                    break;
                case "xiaomi":
                    if (p!["username"]?.GetValue<string>() is not { Length: > 0 } || p["password"]?.GetValue<string>() is not { Length: > 0 })
                        throw ApiException.BadRequest($"providers.{id} needs username and password", "INVALID_REQUEST");
                    if (p["region"]?.GetValue<string>() is { } region && !MiCloud.RegionHosts.ContainsKey(region))
                        throw ApiException.BadRequest($"providers.{id}.region must be one of {string.Join(", ", MiCloud.RegionHosts.Keys)}", "INVALID_REQUEST");
                    break;
                case "factorio":
                    if (p!["host"]?.GetValue<string>() is not { Length: > 0 } || p["password"]?.GetValue<string>() is not { Length: > 0 })
                        throw ApiException.BadRequest($"providers.{id} needs host and password", "INVALID_REQUEST");
                    break;
                default:
                    throw ApiException.BadRequest($"providers.{id}.kind must be mcp-http, mcp-stdio, homeassistant, xiaomi or factorio", "INVALID_REQUEST");
            }
        }
    }

    private IToolProvider Create(string id, JsonObject p) => p["kind"]!.GetValue<string>() switch
    {
        "mcp-http" => McpToolProvider.Http(id, new Uri(p["url"]!.GetValue<string>()),
            (p["headers"] as JsonObject ?? []).ToDictionary(kv => kv.Key, kv => kv.Value!.GetValue<string>()), http.CreateClient(HttpClientName)),
        "mcp-stdio" => McpToolProvider.Stdio(id, p["command"]!.GetValue<string>(), [.. (p["args"] as JsonArray ?? []).Select(a => a!.GetValue<string>())],
            (p["env"] as JsonObject ?? []).ToDictionary(kv => kv.Key, kv => (string?)kv.Value!.GetValue<string>()), p["cwd"]?.GetValue<string>()),
        "homeassistant" => new HomeAssistantTools(http.CreateClient(HttpClientName), new Uri(p["url"]!.GetValue<string>()), p["token"]?.GetValue<string>() ?? "",
            [.. (p["domains"] as JsonArray ?? []).Select(d => d!.GetValue<string>())]),
        "xiaomi" => new XiaomiTools(new XiaomiClient(new MiCloud(new MiCredentials(p["username"]!.GetValue<string>(), p["password"]!.GetValue<string>(),
            p["region"]?.GetValue<string>() ?? "cn"), http.CreateClient(HttpClientName), time))),
        "factorio" => new FactorioTools(p["host"]!.GetValue<string>(), p["port"]?.GetValue<int>() ?? 27015, p["password"]!.GetValue<string>(),
            p["allowCommands"]?.GetValue<bool>() ?? false),
        var kind => throw new InvalidOperationException($"unknown tool provider kind '{kind}'"),
    };

    private async Task<(JsonObject Config, Dictionary<string, IToolProvider> Providers)> CurrentAsync(CancellationToken ct)
    {
        var config = await store.LoadAsync(ct).ConfigureAwait(false);
        var v = config.ToJsonString();
        await gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            if (v != version)
            {
                foreach (var old in providers.Values)
                    await old.DisposeAsync().ConfigureAwait(false);
                var built = new Dictionary<string, IToolProvider>(StringComparer.Ordinal);
                var problems = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (var (id, p) in config["providers"] as JsonObject ?? [])
                {
                    try
                    {
                        built[id] = Create(id, (JsonObject)p!);
                    }
#pragma warning disable CA1031 // one broken provider must not take the others down; it is reported to administrators
                    catch (Exception e)
#pragma warning restore CA1031
                    {
                        problems[id] = e.Message;
                    }
                }
                providers = built;
                Problems = problems;
                version = v;
            }
            return (config, providers);
        }
        finally
        {
            gate.Release();
        }
    }

    public async Task<bool> AllowedAsync(string userId, bool isAdmin, CancellationToken ct) =>
        isAdmin || (await store.LoadAsync(ct).ConfigureAwait(false))["allowAllUsers"]?.GetValue<bool>() == true;

    public async Task<IReadOnlyList<ToolSpec>> ListAsync(CancellationToken ct)
    {
        var (_, current) = await CurrentAsync(ct).ConfigureAwait(false);
        var all = new List<ToolSpec>();
        var problems = new Dictionary<string, string>(Problems, StringComparer.Ordinal);
        foreach (var (id, provider) in current)
        {
            try
            {
                all.AddRange((await provider.ListAsync(ct).ConfigureAwait(false)).Select(t => t with { Name = $"{id}__{t.Name}"[..Math.Min(64, id.Length + 2 + t.Name.Length)] }));
                problems.Remove(id);
            }
#pragma warning disable CA1031 // an unreachable provider is reported and skipped
            catch (Exception e) when (e is not OperationCanceledException)
#pragma warning restore CA1031
            {
                problems[id] = e.Message;
            }
        }
        Problems = problems;
        return all;
    }

    public async Task<ToolCallOutcome> CallAsync(string name, JsonObject arguments, CancellationToken ct)
    {
        var split = name.IndexOf("__", StringComparison.Ordinal);
        var (_, current) = await CurrentAsync(ct).ConfigureAwait(false);
        if (split <= 0 || !current.TryGetValue(name[..split], out var provider))
            return new ToolCallOutcome($"unknown tool '{name}'", true);
        try
        {
            var outcome = await provider.CallAsync(name[(split + 2)..], arguments, ct).ConfigureAwait(false);
            return outcome.Content.Length > MaxResultChars ? outcome with { Content = outcome.Content[..MaxResultChars] + "\n[truncated]" } : outcome;
        }
#pragma warning disable CA1031 // a failing tool answers the model with the error, so it can tell the user or try otherwise
        catch (Exception e) when (e is not OperationCanceledException)
#pragma warning restore CA1031
        {
            return new ToolCallOutcome(e.Message, true);
        }
    }

    public async ValueTask DisposeAsync()
    {
        foreach (var p in providers.Values)
            await p.DisposeAsync().ConfigureAwait(false);
        gate.Dispose();
    }
}

public static class ToolEndpoints
{
    public static void Map(IEndpointRouteBuilder app)
    {
        var g = app.MapGroup("/api/v1/tools").RequireAuthorization();
        g.MapGet("", async (HttpContext c, ToolHub hub, CancellationToken ct) =>
        {
            if (!await hub.AllowedAsync(c.User.UserId(), c.User.IsInRole("admin"), ct).ConfigureAwait(false))
                return Results.Json(new JsonObject { ["tools"] = new JsonArray() });
            var tools = await hub.ListAsync(ct).ConfigureAwait(false);
            return Results.Json(new JsonObject
            {
                ["tools"] = new JsonArray([.. tools.Select(t => (JsonNode)new JsonObject { ["name"] = t.Name, ["description"] = t.Description, ["parameters"] = t.Parameters.DeepClone() })]),
            });
        });
        g.MapPost("/call", async (HttpContext c, ToolHub hub, ProductEvents events, CancellationToken ct) =>
        {
            if (!await hub.AllowedAsync(c.User.UserId(), c.User.IsInRole("admin"), ct).ConfigureAwait(false))
                throw new ApiException(403, "TOOLS_FORBIDDEN", "tools are not enabled for this account");
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_REQUEST", ct).ConfigureAwait(false);
            var name = b?["name"]?.GetValue<string>() ?? throw ApiException.BadRequest("name is required", "INVALID_REQUEST");
            var outcome = await hub.CallAsync(name, b?["arguments"] as JsonObject ?? [], ct).ConfigureAwait(false);
            await events.TrackAsync(c.User.UserId(), "tools", "tool_called", outcome.IsError ? "failed" : "succeeded", name, ct: CancellationToken.None).ConfigureAwait(false);
            return Results.Json(new JsonObject { ["content"] = outcome.Content, ["isError"] = outcome.IsError });
        });

        var admin = app.MapGroup("/api/v1/admin/tools").RequireAuthorization(AdminEndpoints.Policy);
        admin.MapGet("", async (ToolsConfigStore store, ToolHub hub, CancellationToken ct) =>
        {
            var doc = await store.MaskedAsync(ct).ConfigureAwait(false);
            doc["problems"] = new JsonObject([.. hub.Problems.Select(kv => KeyValuePair.Create(kv.Key, (JsonNode?)kv.Value))]);
            return Results.Json(doc);
        });
        admin.MapPut("", async (HttpContext c, ToolsConfigStore store, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_REQUEST", ct).ConfigureAwait(false) as JsonObject
                ?? throw ApiException.BadRequest("JSON object body required", "INVALID_REQUEST");
            b.Remove("problems");
            ToolHub.Validate(b);
            await store.SaveAsync(b, ct).ConfigureAwait(false);
            return Results.Json(new JsonObject { ["ok"] = true });
        });
    }
}
