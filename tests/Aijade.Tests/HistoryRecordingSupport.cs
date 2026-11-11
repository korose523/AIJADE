using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;

using Npgsql;

namespace Aijade.Tests;

internal sealed record HistoryStoreItem(string Id, string Content, long CreatedAt, string Owner, bool HasVector);

internal static class HistoryRecordingSupport
{
    internal static readonly string[] Arms = ["static", "history", "record-after", "record-before", "record-between"];
    internal static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    internal static string Hash(string text) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
    internal static string EventId(int conversation, string source) => "p3-history-" + conversation + "-" + Hash(source);
    internal static bool Records(string arm) => arm.StartsWith("record-", StringComparison.Ordinal);

    internal static async Task<List<HistoryStoreItem>> StoreAsync(ServerTestHost host, CancellationToken ct)
    {
        var result = new List<HistoryStoreItem>();
        await using var conn = await host.Db.OpenConnectionAsync(ct);
        await using var cmd = new NpgsqlCommand("""
            SELECT p.id,c.content,p.created_at,o.user_id,c.embedding IS NOT NULL
            FROM evidence_packs p JOIN evidence_chunks c ON c.pack_id=p.id
            JOIN memory_session_owners o ON o.session_id=p.session_id
            ORDER BY p.id
            """, conn);
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        while (await reader.ReadAsync(ct))
            result.Add(new(reader.GetString(0), reader.GetString(1),
                new DateTimeOffset(DateTime.SpecifyKind(reader.GetDateTime(2), DateTimeKind.Utc)).ToUnixTimeMilliseconds(),
                reader.GetString(3), reader.GetBoolean(4)));
        return result;
    }

    internal static async Task<List<string>> CandidatesAsync(ServerTestHost host, string query, CancellationToken ct)
    {
        var result = new List<string>();
        await using var conn = await host.Db.OpenConnectionAsync(ct);
        await using var cmd = new NpgsqlCommand("""
            SELECT p.id FROM evidence_packs p JOIN evidence_chunks c ON c.pack_id=p.id
            JOIN memory_session_owners o ON o.session_id=p.session_id
            WHERE o.user_id=$1 AND c.content ILIKE '%' || $2 || '%'
            ORDER BY p.created_at DESC
            """, conn);
        cmd.Parameters.AddWithValue(ServerTestHost.UserId);
        cmd.Parameters.AddWithValue(query.Trim());
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        while (await reader.ReadAsync(ct)) result.Add(reader.GetString(0));
        return result;
    }

    internal static JsonObject State(IReadOnlyList<HistoryStoreItem> store, IReadOnlyDictionary<string, string> logical)
    {
        var unmapped = store.Where(s => !logical.ContainsKey(s.Id)).Select(s => s.Id).ToArray();
        var canonical = string.Join("\n", store.OrderBy(s => logical.GetValueOrDefault(s.Id, "UNMAPPED:" + s.Id), StringComparer.Ordinal)
            .Select(s => logical.GetValueOrDefault(s.Id, "UNMAPPED:" + s.Id) + "\t" +
                s.CreatedAt.ToString(CultureInfo.InvariantCulture) + "\t" + Hash(s.Content)));
        return new JsonObject
        {
            ["count"] = store.Count, ["canonicalSha256"] = Hash(canonical),
            ["unmappedIds"] = JsonSerializer.SerializeToNode(unmapped, Json),
            ["vectorItems"] = store.Count(s => s.HasVector),
            ["owners"] = JsonSerializer.SerializeToNode(store.Select(s => s.Owner).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal), Json),
        };
    }

    internal static IReadOnlyList<MemoryItem> Selected(IEnumerable<JsonObject> searches, string question)
    {
        var unique = new Dictionary<string, MemoryItem>(StringComparer.Ordinal);
        foreach (var search in searches)
        {
            if (search["status"]!.GetValue<int>() is < 200 or >= 300) continue;
            foreach (var node in JsonNode.Parse(search["responseBody"]!.GetValue<string>())!["items"]!.AsArray())
            {
                var item = node!.Deserialize<MemoryItem>(Json)!;
                if (!string.Equals(item.Content.Trim(), question.Trim(), StringComparison.OrdinalIgnoreCase))
                    unique.TryAdd(item.Id, item);
            }
        }
        return unique.Values.OrderByDescending(i => i.CreatedAt).Take(5).ToArray();
    }
}

internal sealed class HistoryRecordingClock : TimeProvider
{
    internal DateTimeOffset Now { get; set; } = new(2026, 11, 12, 0, 0, 0, TimeSpan.Zero);
    public override DateTimeOffset GetUtcNow() => Now;
}

internal sealed class HistoryJournal(string path)
{
    private long sequence;
    internal void Add(string key, string phase, JsonNode? detail = null) =>
        File.AppendAllText(path, new JsonObject
        {
            ["sequence"] = Interlocked.Increment(ref sequence),
            ["utc"] = DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture),
            ["monotonicTicks"] = Stopwatch.GetTimestamp(), ["frequency"] = Stopwatch.Frequency,
            ["key"] = key, ["phase"] = phase, ["detail"] = detail?.DeepClone(),
        }.ToJsonString() + "\n");
}

/// <summary>Captures actual product HTTP and deliberately exposes one recorder interleaving.</summary>
internal sealed class HistoryRecordingTap(HttpMessageHandler inner, ServerTestHost host, HistoryJournal journal)
    : DelegatingHandler(inner)
{
    private int call;
    private bool callbackDone;
    private string key = "not-started";
    internal List<JsonObject> Calls { get; } = [];
    internal List<JsonObject> Searches { get; } = [];
    internal string? CompletionBody { get; private set; }
    internal int Completions { get; private set; }
    internal Func<Task>? AfterFirstMemoryResponse { get; set; }

    internal void Begin(string questionKey)
    {
        key = questionKey; Calls.Clear(); Searches.Clear(); CompletionBody = null; Completions = 0;
        call = 0; callbackDone = false; AfterFirstMemoryResponse = null;
    }

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
    {
        var number = ++call;
        var path = request.RequestUri!.AbsolutePath;
        var input = request.Content is null ? null : await request.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        var capture = new JsonObject
        {
            ["call"] = number, ["method"] = request.Method.Method, ["path"] = path,
            ["queryString"] = request.RequestUri.Query, ["requestBody"] = input,
            ["beginTicks"] = Stopwatch.GetTimestamp(),
        };
        Calls.Add(capture);
        journal.Add(key, "http.begin", new JsonObject { ["call"] = number, ["path"] = path, ["requestSha256"] = input is null ? null : HistoryRecordingSupport.Hash(input) });
        HttpResponseMessage response;
        if (path.EndsWith("/openai/v1/chat/completions", StringComparison.Ordinal))
        {
            CompletionBody = input; Completions++;
            response = new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("data: {\"choices\":[{\"delta\":{\"content\":\"ok\"}}]}\n\ndata: [DONE]\n\n", Encoding.UTF8, "text/event-stream"),
            };
        }
        else response = await base.SendAsync(request, ct).ConfigureAwait(false);
        var output = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        capture["status"] = (int)response.StatusCode; capture["responseBody"] = output;
        capture["nativeResponseTicks"] = Stopwatch.GetTimestamp();
        if (path.TrimEnd('/').EndsWith("/api/v1/memory/items", StringComparison.Ordinal) && request.Method == HttpMethod.Get)
        {
            var query = global::System.Web.HttpUtility.ParseQueryString(request.RequestUri.Query);
            var text = query["q"] ?? "";
            capture["memoryQuery"] = text;
            capture["limit"] = int.Parse(query["limit"]!, CultureInfo.InvariantCulture);
            capture["sessionFilter"] = query["session"];
            var candidates = await HistoryRecordingSupport.CandidatesAsync(host, text, ct).ConfigureAwait(false);
            var store = await HistoryRecordingSupport.StoreAsync(host, ct).ConfigureAwait(false);
            capture["candidateIds"] = JsonSerializer.SerializeToNode(candidates, HistoryRecordingSupport.Json);
            capture["storeCountAtResponse"] = store.Count;
            capture["candidateCreatedAt"] = new JsonArray(candidates.Select(id => (JsonNode)JsonValue.Create(store.Single(s => s.Id == id).CreatedAt)!).ToArray());
            capture["nativeStateObservedTicks"] = Stopwatch.GetTimestamp();
            Searches.Add(capture);
            journal.Add(key, "memory.response", new JsonObject { ["call"] = number, ["responseSha256"] = HistoryRecordingSupport.Hash(output),
                ["candidateIdsSha256"] = HistoryRecordingSupport.Hash(capture["candidateIds"]!.ToJsonString()) });
            if (!callbackDone && AfterFirstMemoryResponse is { } action)
            {
                callbackDone = true;
                journal.Add(key, "record.callback.begin");
                await action().ConfigureAwait(false);
                journal.Add(key, "record.callback.end");
            }
        }
        capture["endTicks"] = Stopwatch.GetTimestamp();
        journal.Add(key, "http.end", new JsonObject { ["call"] = number, ["status"] = (int)response.StatusCode,
            ["responseSha256"] = HistoryRecordingSupport.Hash(output) });
        // The original response bytes and media type remain the product's input.
        var mediaType = response.Content.Headers.ContentType?.MediaType ?? "application/json";
        response.Content = new StringContent(output, Encoding.UTF8, mediaType);
        return response;
    }
}
