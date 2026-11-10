using System.IO.Compression;
using System.Net;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;

namespace Aijade.Tests;

/// <summary>Declared research policy; production MemoryRecallProvider remains unchanged.</summary>
internal sealed class PolicyMemoryContext(AijadeApi api, int responseLimit, bool newest) : IContextProvider
{
    public async Task<string?> SupplyAsync(TurnContext turn, CancellationToken ct)
    {
        var items = new Dictionary<string, MemoryItem>(StringComparer.Ordinal);
        void Add(IEnumerable<MemoryItem> found)
        {
            foreach (var item in found)
                if (!string.Equals(item.Content.Trim(), turn.UserText.Trim(), StringComparison.OrdinalIgnoreCase))
                    items.TryAdd(item.Id, item);
        }
        Add(await api.MemoryItemsAsync(turn.UserText, responseLimit, ct: ct).ConfigureAwait(false));
        foreach (var term in items.Count > 0 ? [] : MemoryRecallProvider.Terms(turn.UserText))
            Add(await api.MemoryItemsAsync(term, responseLimit, ct: ct).ConfigureAwait(false));
        if (items.Count == 0)
            return null;
        var selected = newest ? items.Values.OrderByDescending(i => i.CreatedAt).Take(5) : items.Values.Take(5);
        return ProductPromptObservation.Header + string.Join("\n", selected.Select(i => "- " + i.Content));
    }
}

internal sealed record PolicySearch(string Query, int Limit, int Status, string RawBody, IReadOnlyList<string> Ids);

/// <summary>Records actual memory responses and the model request; generates no model answer.</summary>
internal sealed class PolicyTap(HttpMessageHandler inner) : DelegatingHandler(inner)
{
    public string? SystemMessage { get; private set; }
    public List<PolicySearch> Searches { get; } = [];
    public void Reset()
    {
        Searches.Clear();
        SystemMessage = null;
    }

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
    {
        var path = request.RequestUri!.AbsolutePath;
        if (path.EndsWith("/openai/v1/chat/completions", StringComparison.Ordinal))
        {
            var body = JsonNode.Parse(await request.Content!.ReadAsStringAsync(ct).ConfigureAwait(false))!;
            SystemMessage = body["messages"]!.AsArray().First(m => m!["role"]!.GetValue<string>() == "system")!["content"]!.GetValue<string>();
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("data: {\"choices\":[{\"delta\":{\"content\":\"ok\"}}]}\n\ndata: [DONE]\n\n", Encoding.UTF8, "text/event-stream"),
            };
        }
        var response = await base.SendAsync(request, ct).ConfigureAwait(false);
        if (path.TrimEnd('/').EndsWith("/api/v1/memory/items", StringComparison.Ordinal))
        {
            var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            var query = global::System.Web.HttpUtility.ParseQueryString(request.RequestUri.Query);
            var ids = response.IsSuccessStatusCode
                ? JsonNode.Parse(text)!["items"]!.AsArray().Select(i => i!["id"]!.GetValue<string>()).ToArray() : [];
            Searches.Add(new(query["q"] ?? "", int.Parse(query["limit"]!, global::System.Globalization.CultureInfo.InvariantCulture), (int)response.StatusCode, text, ids));
            response.Content = new StringContent(text, Encoding.UTF8, "application/json");
        }
        return response;
    }
}

/// <summary>Only previously observed vectors are available; a missing/conflicting input rejects the experiment.</summary>
internal sealed class PolicyVectorReplay
{
    private readonly Dictionary<string, float[]> vectors = new(StringComparer.Ordinal);
    public int Calls { get; private set; }
    public int Misses { get; private set; }
    public int Inputs => vectors.Count;

    public float[] Get(string text)
    {
        if (vectors.TryGetValue(text, out var vector))
            return vector;
        Misses++;
        throw new InvalidOperationException("Unobserved embedding input; live model fallback is forbidden.");
    }

    public static async Task<PolicyVectorReplay> LoadAsync(string path, CancellationToken ct)
    {
        var result = new PolicyVectorReplay();
        await using var file = File.OpenRead(path);
        await using var zip = new GZipStream(file, CompressionMode.Decompress);
        using var reader = new StreamReader(zip);
        while (await reader.ReadLineAsync(ct).ConfigureAwait(false) is { } line)
        {
            var row = JsonNode.Parse(line)!;
            if (row["status"]!.GetValue<int>() != 200)
                throw new InvalidDataException("Failed upstream response in source replay.");
            var input = row["input"]!["input"]!.AsArray();
            var data = JsonNode.Parse(row["response"]!.GetValue<string>())!["data"]!.AsArray();
            if (data.Count != input.Count)
                throw new InvalidDataException("Incomplete source vector response.");
            foreach (var item in data)
            {
                var text = input[item!["index"]!.GetValue<int>()]!.GetValue<string>();
                var vector = item["embedding"]!.AsArray().Select(v => v!.GetValue<float>()).ToArray();
                if (vector.Length != 768 || vector.Any(v => !float.IsFinite(v)))
                    throw new InvalidDataException("Malformed source embedding.");
                if (result.vectors.TryGetValue(text, out var old) && !old.SequenceEqual(vector))
                    throw new InvalidDataException("Conflicting repeated source embeddings.");
                result.vectors[text] = vector;
            }
        }
        return result;
    }

    public HttpMessageHandler NewHandler() => new ReplayHandler(this);

    private sealed class ReplayHandler(PolicyVectorReplay cache) : HttpMessageHandler
    {
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            var body = JsonNode.Parse(await request.Content!.ReadAsStringAsync(ct).ConfigureAwait(false))!;
            if (body["model"]!.GetValue<string>() != "nomic-embed-text")
                throw new InvalidDataException("Unexpected replay model.");
            var input = body["input"]!.AsArray();
            var data = new JsonArray();
            for (var i = 0; i < input.Count; i++)
                data.Add(new JsonObject
                {
                    ["object"] = "embedding", ["index"] = i,
                    ["embedding"] = new JsonArray([.. cache.Get(input[i]!.GetValue<string>()).Select(v => JsonValue.Create(v))]),
                });
            cache.Calls++;
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(new JsonObject { ["object"] = "list", ["model"] = "nomic-embed-text", ["data"] = data }.ToJsonString(), Encoding.UTF8, "application/json"),
            };
        }
    }
}
