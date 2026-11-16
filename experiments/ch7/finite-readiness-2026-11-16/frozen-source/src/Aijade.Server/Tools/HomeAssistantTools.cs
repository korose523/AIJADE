using System.Net.Http.Headers;
using System.Text;
using System.Text.Json.Nodes;

namespace Aijade.Server.Tools;

/// <summary>
/// Home Assistant through its REST API (a long-lived access token): list entities and their states, read one, and call a
/// service on an entity. <paramref name="domains"/> limits what the companion may see and control (e.g. light, switch,
/// climate); empty allows every domain.
/// </summary>
public sealed class HomeAssistantTools(HttpClient http, Uri baseUrl, string token, IReadOnlyList<string> domains) : IToolProvider
{
    private static JsonObject Schema(params (string Name, string Type, string Description, bool Required)[] props) => new()
    {
        ["type"] = "object",
        ["properties"] = new JsonObject([.. props.Select(p => KeyValuePair.Create(p.Name, (JsonNode?)new JsonObject { ["type"] = p.Type, ["description"] = p.Description }))]),
        ["required"] = new JsonArray([.. props.Where(p => p.Required).Select(p => (JsonNode)p.Name)]),
    };

    public Task<IReadOnlyList<ToolSpec>> ListAsync(CancellationToken ct) => Task.FromResult<IReadOnlyList<ToolSpec>>(
    [
        new("list_entities", "List Home Assistant entities with their state and friendly name, optionally of one domain (light, switch, climate …).",
            Schema(("domain", "string", "Only this domain.", false))),
        new("get_state", "Read the state and attributes of one entity.", Schema(("entity_id", "string", "e.g. light.living_room", true))),
        new("call_service", "Call a service on an entity, e.g. domain light, service turn_on, with optional data such as brightness_pct.",
            Schema(("domain", "string", "Service domain, e.g. light.", true), ("service", "string", "e.g. turn_on, turn_off, toggle.", true),
                ("entity_id", "string", "The entity to act on.", true), ("data", "object", "Extra service data.", false))),
    ]);

    private bool Allowed(string entityOrDomain) =>
        domains.Count == 0 || domains.Contains(entityOrDomain.Split('.')[0], StringComparer.Ordinal);

    private async Task<string> SendAsync(HttpMethod method, string path, JsonNode? body, CancellationToken ct)
    {
        using var req = new HttpRequestMessage(method, new Uri(baseUrl, path));
        req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        if (body is not null)
            req.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
        using var res = await http.SendAsync(req, ct).ConfigureAwait(false);
        var text = await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        return res.IsSuccessStatusCode ? text : throw new InvalidOperationException($"Home Assistant answered {(int)res.StatusCode}: {(text.Length > 200 ? text[..200] : text)}");
    }

    public async Task<ToolCallOutcome> CallAsync(string tool, JsonObject arguments, CancellationToken ct)
    {
        var a = arguments;
        switch (tool)
        {
            case "list_entities":
            {
                var domain = a["domain"]?.GetValue<string>();
                if (domain is not null && !Allowed(domain))
                    return new($"domain '{domain}' is not enabled for the companion", true);
                var states = JsonNode.Parse(await SendAsync(HttpMethod.Get, "api/states", null, ct).ConfigureAwait(false)) as JsonArray ?? [];
                var lines = states.Select(s => (Id: s!["entity_id"]!.GetValue<string>(), State: s["state"]?.ToString() ?? "", Name: s["attributes"]?["friendly_name"]?.ToString()))
                    .Where(s => Allowed(s.Id) && (domain is null || s.Id.StartsWith(domain + ".", StringComparison.Ordinal)))
                    .Select(s => $"{s.Id} = {s.State}{(s.Name is { } n ? $" ({n})" : "")}");
                var text = string.Join("\n", lines);
                return new(text.Length == 0 ? "No entities." : text, false);
            }
            case "get_state":
            {
                var id = a["entity_id"]?.GetValue<string>() ?? "";
                if (!Allowed(id))
                    return new($"'{id}' is not in an enabled domain", true);
                return new(await SendAsync(HttpMethod.Get, $"api/states/{Uri.EscapeDataString(id)}", null, ct).ConfigureAwait(false), false);
            }
            case "call_service":
            {
                var domain = a["domain"]?.GetValue<string>() ?? "";
                var service = a["service"]?.GetValue<string>() ?? "";
                var id = a["entity_id"]?.GetValue<string>() ?? "";
                if (!Allowed(domain) || !Allowed(id))
                    return new($"'{domain}' / '{id}' is not in an enabled domain", true);
                var data = a["data"] is JsonObject d ? (JsonObject)d.DeepClone() : [];
                data["entity_id"] = id;
                await SendAsync(HttpMethod.Post, $"api/services/{Uri.EscapeDataString(domain)}/{Uri.EscapeDataString(service)}", data, ct).ConfigureAwait(false);
                return new($"Called {domain}.{service} on {id}.", false);
            }
            default:
                return new($"unknown Home Assistant tool '{tool}'", true);
        }
    }

    public ValueTask DisposeAsync() => ValueTask.CompletedTask;
}
