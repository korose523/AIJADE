using System.Collections.Concurrent;
using System.Text.Json.Nodes;
using System.Threading.Channels;

using StackExchange.Redis;

namespace Aijade.Server.Infrastructure;

// Background jobs are JSON documents on named lists. With Redis (REDIS_URL) the API and the worker can be separate
// processes; without it an in-process queue keeps a single-process deployment working. Dead letters keep failed jobs
// for inspection under keys shared by the worker and its verifiers.

public interface IJobBroker
{
    Task EnqueueAsync(string queue, JsonNode job, CancellationToken cancellationToken = default);

    /// <summary>The oldest job of <paramref name="queue"/>, or null when it is empty.</summary>
    Task<JsonNode?> TryDequeueAsync(string queue, CancellationToken cancellationToken = default);

    Task ParkDeadLetterAsync(string key, JsonNode job, string reason, CancellationToken cancellationToken = default);

    Task<long> LengthAsync(string queue, CancellationToken cancellationToken = default);
}

public static class Queues
{
    public const string Perception = "aijade:v9:perception";
    public const string PerceptionDeadLetter = "aijade:v9:dead-letter";
    public const string Promotion = "aijade:v9:promotion";
    public const string PromotionDeadLetter = "aijade:v9:promotion:dead-letter";
    public const string VideoObservation = "aijade:v9:video-observation";
    public const string VideoObservationDeadLetter = "aijade:v9:video-observation:dead-letter";
    public const string Memory = "aijade:memory:sync";
    public const string MemoryDeadLetter = "aijade:memory:dead-letter";
}

public sealed class InMemoryJobBroker : IJobBroker
{
    private readonly ConcurrentDictionary<string, Channel<string>> lists = new(StringComparer.Ordinal);

    private Channel<string> List(string name) => lists.GetOrAdd(name, _ => Channel.CreateUnbounded<string>());

    public Task EnqueueAsync(string queue, JsonNode job, CancellationToken cancellationToken = default) =>
        List(queue).Writer.WriteAsync(job.ToJsonString(), cancellationToken).AsTask();

    public Task<JsonNode?> TryDequeueAsync(string queue, CancellationToken cancellationToken = default) =>
        Task.FromResult(List(queue).Reader.TryRead(out var raw) ? JsonNode.Parse(raw) : null);

    public Task ParkDeadLetterAsync(string key, JsonNode job, string reason, CancellationToken cancellationToken = default) =>
        EnqueueAsync(key, new JsonObject { ["job"] = job.DeepClone(), ["error"] = reason }, cancellationToken);

    public Task<long> LengthAsync(string queue, CancellationToken cancellationToken = default) => Task.FromResult((long)List(queue).Reader.Count);
}

/// <summary>Redis lists: LPUSH to enqueue, RPOP to take the oldest (FIFO).</summary>
public sealed class RedisJobBroker(IConnectionMultiplexer redis) : IJobBroker
{
    private IDatabase Db => redis.GetDatabase();

    public Task EnqueueAsync(string queue, JsonNode job, CancellationToken cancellationToken = default) =>
        Db.ListLeftPushAsync(queue, job.ToJsonString());

    public async Task<JsonNode?> TryDequeueAsync(string queue, CancellationToken cancellationToken = default)
    {
        var raw = await Db.ListRightPopAsync(queue).ConfigureAwait(false);
        return raw.IsNullOrEmpty ? null : JsonNode.Parse(raw.ToString());
    }

    public Task ParkDeadLetterAsync(string key, JsonNode job, string reason, CancellationToken cancellationToken = default) =>
        EnqueueAsync(key, new JsonObject { ["job"] = job.DeepClone(), ["error"] = reason }, cancellationToken);

    public Task<long> LengthAsync(string queue, CancellationToken cancellationToken = default) => Db.ListLengthAsync(queue);
}
