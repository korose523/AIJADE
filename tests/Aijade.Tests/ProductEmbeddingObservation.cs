using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Aijade.Tests;

/// <summary>Observes the real gateway's embedding responses; never replaces an embedding or sends an extra request.</summary>
internal sealed class ProductEmbeddingObservation(HttpMessageHandler inner, string? journal = null) : DelegatingHandler(inner)
{
    public Dictionary<string, float[]> Vectors { get; } = new(StringComparer.Ordinal);
    public int Requests { get; private set; }
    public int Failures { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
    {
        var input = JsonNode.Parse(await request.Content!.ReadAsStringAsync(ct).ConfigureAwait(false))!;
        var response = await base.SendAsync(request, ct).ConfigureAwait(false);
        var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        Requests++;
        if (journal is not null)
            await AppendAsync(journal, new { time = DateTimeOffset.UtcNow, status = (int)response.StatusCode, input, response = text }, ct).ConfigureAwait(false);
        if (response.IsSuccessStatusCode)
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
        response.Content = new StringContent(text, Encoding.UTF8, "application/json");
        return response;
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
