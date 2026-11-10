using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Aijade.Tests;

/// <summary>Conversation-level state outlives individual handlers retired by IHttpClientFactory.</summary>
internal sealed class ProductEmbeddingCapture(string? journal = null)
{
    public Dictionary<string, float[]> Vectors { get; } = new(StringComparer.Ordinal);
    public int Requests { get; private set; }
    public int Failures { get; private set; }

    public async Task RecordAsync(JsonNode input, string text, int status, CancellationToken ct)
    {
        Requests++;
        if (journal is not null)
            await AppendAsync(journal, new { time = DateTimeOffset.UtcNow, status, input, response = text }, ct).ConfigureAwait(false);
        if (status is >= 200 and < 300)
        {
            var body = JsonNode.Parse(text)!;
            foreach (var item in body["data"] as JsonArray ?? [])
            {
                var index = item!["index"]?.GetValue<int>() ?? 0;
                var inputs = input["input"]!.AsArray();
                if (index >= 0 && index < inputs.Count && item["embedding"] is JsonArray vector)
                    Vectors[inputs[index]!.GetValue<string>()] = [.. vector.Select(v => v!.GetValue<float>())];
            }
        }
        else
            Failures++;
    }

    public static async Task AppendAsync<T>(string path, T value, CancellationToken ct)
    {
        await using var output = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.Read, 4096, FileOptions.WriteThrough);
        var bytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(value) + "\n");
        await output.WriteAsync(bytes, ct).ConfigureAwait(false);
        await output.FlushAsync(ct).ConfigureAwait(false);
        output.Flush(flushToDisk: true);
    }
}

/// <summary>One transport handler per factory creation; preserves the actual response and shares only recording state.</summary>
internal sealed class ProductEmbeddingObservation(HttpMessageHandler inner, ProductEmbeddingCapture capture) : DelegatingHandler(inner)
{
    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
    {
        var input = JsonNode.Parse(await request.Content!.ReadAsStringAsync(ct).ConfigureAwait(false))!;
        var response = await base.SendAsync(request, ct).ConfigureAwait(false);
        var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        await capture.RecordAsync(input, text, (int)response.StatusCode, ct).ConfigureAwait(false);
        response.Content = new StringContent(text, Encoding.UTF8, "application/json");
        return response;
    }
}
