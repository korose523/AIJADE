using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;

namespace Aijade.Research.Telemetry;

/// <summary>Where sessions and turns go. A browser-side store belongs to the web client.</summary>
public interface ITelemetryStorage
{
    Task SaveSessionAsync(SessionMeta session, CancellationToken cancellationToken = default);

    Task AppendTurnAsync(TurnRecord record, CancellationToken cancellationToken = default);

    Task<IReadOnlyList<TurnRecord>> ReadTurnsAsync(string sessionId, CancellationToken cancellationToken = default);

    Task<IReadOnlyList<SessionMeta>> ReadSessionsAsync(CancellationToken cancellationToken = default);

    Task ClearAsync(CancellationToken cancellationToken = default);
}

public sealed class MemoryTelemetryStorage : ITelemetryStorage
{
    private readonly OrderedDictionary<string, SessionMeta> _sessions = new(StringComparer.Ordinal);
    private readonly Dictionary<string, List<TurnRecord>> _turns = new(StringComparer.Ordinal);
    private readonly Lock _gate = new();

    public Task SaveSessionAsync(SessionMeta session, CancellationToken cancellationToken = default)
    {
        lock (_gate)
            _sessions[session.SessionId] = session;
        return Task.CompletedTask;
    }

    public Task AppendTurnAsync(TurnRecord record, CancellationToken cancellationToken = default)
    {
        lock (_gate)
        {
            if (!_turns.TryGetValue(record.SessionId, out var list))
                _turns[record.SessionId] = list = [];
            list.Add(record);
        }
        return Task.CompletedTask;
    }

    public Task<IReadOnlyList<TurnRecord>> ReadTurnsAsync(string sessionId, CancellationToken cancellationToken = default)
    {
        lock (_gate)
            return Task.FromResult<IReadOnlyList<TurnRecord>>((_turns.GetValueOrDefault(sessionId) ?? []).OrderBy(t => t.TurnIndex).ToList());
    }

    public Task<IReadOnlyList<SessionMeta>> ReadSessionsAsync(CancellationToken cancellationToken = default)
    {
        lock (_gate)
            return Task.FromResult<IReadOnlyList<SessionMeta>>([.. _sessions.Values]);
    }

    public Task ClearAsync(CancellationToken cancellationToken = default)
    {
        lock (_gate)
        {
            _sessions.Clear();
            _turns.Clear();
        }
        return Task.CompletedTask;
    }
}

/// <summary>
/// sessions.jsonl (one line per session, rewritten sorted by start time) and turns.jsonl (append-only) in a directory —
/// crash-safe, diffable, and loadable directly by pandas / R / DuckDB. Writes are serialized.
/// </summary>
public sealed class FileTelemetryStorage(string dir) : ITelemetryStorage, IDisposable
{
    private readonly SemaphoreSlim _write = new(1, 1);
    private string SessionsPath => Path.Combine(dir, "sessions.jsonl");
    private string TurnsPath => Path.Combine(dir, "turns.jsonl");

    public void Dispose() => _write.Dispose();

    private async Task Serialized(Func<Task> task, CancellationToken ct)
    {
        Directory.CreateDirectory(dir);
        await _write.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            await task().ConfigureAwait(false);
        }
        finally
        {
            _write.Release();
        }
    }

    private static async Task<List<string>> ReadLinesAsync(string path, CancellationToken ct) =>
        File.Exists(path) ? (await File.ReadAllLinesAsync(path, ct).ConfigureAwait(false)).Where(l => l.Trim().Length > 0).ToList() : [];

    public Task SaveSessionAsync(SessionMeta session, CancellationToken cancellationToken = default) => Serialized(async () =>
    {
        var others = (await ReadLinesAsync(SessionsPath, cancellationToken).ConfigureAwait(false))
            .Select(l => JsonSerializer.Deserialize<SessionMeta>(l, TelemetryJson.Options)!).Where(s => s.SessionId != session.SessionId);
        var all = others.Append(session).OrderBy(s => s.StartedAt).Select(s => JsonSerializer.Serialize(s, TelemetryJson.Options));
        await File.WriteAllTextAsync(SessionsPath, string.Join("\n", all) + "\n", cancellationToken).ConfigureAwait(false);
    }, cancellationToken);

    public Task AppendTurnAsync(TurnRecord record, CancellationToken cancellationToken = default) =>
        Serialized(() => File.AppendAllTextAsync(TurnsPath, JsonSerializer.Serialize(record, TelemetryJson.Options) + "\n", cancellationToken), cancellationToken);

    public async Task<IReadOnlyList<TurnRecord>> ReadTurnsAsync(string sessionId, CancellationToken cancellationToken = default) =>
        (await ReadLinesAsync(TurnsPath, cancellationToken).ConfigureAwait(false)).Select(l => JsonSerializer.Deserialize<TurnRecord>(l, TelemetryJson.Options)!)
            .Where(r => r.SessionId == sessionId).OrderBy(r => r.TurnIndex).ToList();

    public async Task<IReadOnlyList<SessionMeta>> ReadSessionsAsync(CancellationToken cancellationToken = default) =>
        (await ReadLinesAsync(SessionsPath, cancellationToken).ConfigureAwait(false)).Select(l => JsonSerializer.Deserialize<SessionMeta>(l, TelemetryJson.Options)!).ToList();

    public Task ClearAsync(CancellationToken cancellationToken = default) => Serialized(async () =>
    {
        await File.WriteAllTextAsync(SessionsPath, "", cancellationToken).ConfigureAwait(false);
        await File.WriteAllTextAsync(TurnsPath, "", cancellationToken).ConfigureAwait(false);
    }, cancellationToken);
}

public sealed record RecordTurnInput(TurnRole Role)
{
    public PersonaSnapshot? Persona { get; init; }
    public int? SkillLibrarySize { get; init; }
    public int? SkillsCreatedThisTurn { get; init; }
    public int? SkillsRejectedThisTurn { get; init; }
    public LatencyBreakdown? Latency { get; init; }
    public TokenUsage? Tokens { get; init; }
    public int? MemoryHits { get; init; }
    public int? TextLength { get; init; }
    public DynamicsParameters? Parameters { get; init; }
    public JsonObject? Metadata { get; init; }
}

/// <summary>One experiment session: its condition and parameters are fixed at start; turns are numbered in order.</summary>
public sealed class ExperimentSessionRunner
{
    private readonly ITelemetryStorage _storage;
    private readonly Func<double> _now;
    private readonly SessionMeta _meta;
    private int _index;
    private bool _ended;

    public ExperimentSessionRunner(string? condition = null, AblationCondition? conditionObject = null, AblationConfig? config = null, string? participantId = null,
        DynamicsParameters? parameters = null, IReadOnlyDictionary<string, string>? tags = null, ITelemetryStorage? storage = null, string? sessionId = null, Func<double>? now = null)
    {
        _now = now ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        SessionId = sessionId ?? Guid.NewGuid().ToString();
        StartedAt = _now();
        Condition = conditionObject ?? Ablations.Resolve(condition ?? "baseline");
        Config = config ?? Condition.Config;
        ConfigFingerprint = Fingerprints.Config(Config);
        Parameters = parameters ?? DynamicsParameters.Empty;
        ParameterFingerprint = Fingerprints.Parameters(Parameters);
        _storage = storage ?? new MemoryTelemetryStorage();
        _meta = new SessionMeta(SessionId, Condition.Name, ConfigFingerprint, StartedAt, participantId, parameters, parameters is null ? null : ParameterFingerprint, tags);
    }

    public string SessionId { get; }
    public AblationCondition Condition { get; }
    public AblationConfig Config { get; }
    public string ConfigFingerprint { get; }
    public DynamicsParameters Parameters { get; }
    public string ParameterFingerprint { get; }
    public double StartedAt { get; }
    public int TurnCount => _index;
    public ITelemetryStorage Storage => _storage;

    public static async Task<ExperimentSessionRunner> StartAsync(ExperimentSessionRunner runner, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(runner);
        await runner._storage.SaveSessionAsync(runner._meta, cancellationToken).ConfigureAwait(false);
        return runner;
    }

    public bool IsEnabled(string component) => Config.Entries().FirstOrDefault(e => e.Key == component).On;

    public async Task<TurnRecord> RecordTurnAsync(RecordTurnInput input, CancellationToken cancellationToken = default)
    {
        if (_ended)
            throw new InvalidOperationException($"Session {SessionId} has already been closed");
        var ts = _now();
        var record = new TurnRecord(SessionId, _index++, ts, TelemetryJson.IsoTime(ts), input.Role)
        {
            Persona = input.Persona,
            SkillLibrarySize = input.SkillLibrarySize,
            SkillsCreatedThisTurn = input.SkillsCreatedThisTurn,
            SkillsRejectedThisTurn = input.SkillsRejectedThisTurn,
            Latency = input.Latency,
            Tokens = input.Tokens,
            MemoryHits = input.MemoryHits,
            TextLength = input.TextLength,
            Parameters = input.Parameters ?? Parameters,
            Metadata = input.Metadata,
        };
        await _storage.AppendTurnAsync(record, cancellationToken).ConfigureAwait(false);
        return record;
    }

    public async Task<ExperimentSession> CloseAsync(CancellationToken cancellationToken = default)
    {
        if (!_ended)
        {
            _ended = true;
            await _storage.SaveSessionAsync(_meta, cancellationToken).ConfigureAwait(false);
        }
        return new ExperimentSession(_meta, _now(), _index);
    }
}

public sealed record SeriesSummary(int Count, double Min, double Max, double Mean, double Sd);

/// <summary>CSV (fixed columns, quoted only when needed) and JSONL export, plus per-column summaries and persona drift.</summary>
public static class TelemetryExport
{
    private static readonly string[] VectorKeys = ["openness", "warmth", "curiosity", "patience", "formality", "playfulness", "caution", "confidence", "empathy", "spontaneity", "diligence", "assertiveness", "stability"];

    public static IReadOnlyList<string> CsvColumns { get; } =
    [
        "sessionId", "turnIndex", "timestamp", "wallClock", "role",
        .. VectorKeys.Select(k => $"persona.vector.{k}"),
        .. new[] { "dopamine", "serotonin", "cortisol", "oxytocin", "adrenaline" }.Select(k => $"persona.endocrine.{k}"),
        .. new[] { "pleasure", "arousal", "dominance" }.Select(k => $"persona.pad.{k}"),
        .. new[] { "O", "C", "E", "A", "N" }.Select(k => $"persona.bigFive.{k}"),
        .. new[] { "warmth", "trust", "dependence", "security", "familiarity", "longing" }.Select(k => $"persona.intimacy.{k}"),
        "persona.moodLabel", "skillLibrarySize", "skillsCreatedThisTurn", "skillsRejectedThisTurn",
        "latency.vad", "latency.asr", "latency.llm", "latency.tts", "latency.lipsync", "latency.memoryRetrieval", "latency.total",
        "tokens.prompt", "tokens.completion", "tokens.memoryInjected", "memoryHits", "textLength",
    ];

    /// <summary>The flat column → value view of a record (via its JSON form, so key names match the files).</summary>
    public static Dictionary<string, JsonNode?> Flatten(TurnRecord r)
    {
        var json = JsonSerializer.SerializeToNode(r, TelemetryJson.Options)!.AsObject();
        var flat = new Dictionary<string, JsonNode?>(StringComparer.Ordinal);
        foreach (var key in new[] { "sessionId", "turnIndex", "timestamp", "wallClock", "role", "skillLibrarySize", "skillsCreatedThisTurn", "skillsRejectedThisTurn", "memoryHits", "textLength" })
        {
            if (json.TryGetPropertyValue(key, out var v))
                flat[key] = v;
        }
        if (json["persona"] is JsonObject p)
        {
            foreach (var group in new[] { "vector", "endocrine", "pad", "bigFive", "intimacy" })
            {
                foreach (var (k, v) in p[group]?.AsObject() ?? [])
                    flat[$"persona.{group}.{k}"] = v;
            }
            if (p.TryGetPropertyValue("moodLabel", out var mood))
                flat["persona.moodLabel"] = mood;
        }
        foreach (var group in new[] { "latency", "tokens" })
        {
            foreach (var (k, v) in json[group]?.AsObject() ?? [])
                flat[$"{group}.{k}"] = v;
        }
        return flat;
    }

    private static string Cell(JsonNode? v)
    {
        if (v is null)
            return "";
        var s = v.GetValueKind() == JsonValueKind.String ? v.GetValue<string>() : v.GetValueKind() == JsonValueKind.Number ? JsFormat.Number(v.GetValue<double>()) : v.ToJsonString();
        return s.AsSpan().IndexOfAny("\",\n\r") >= 0 ? $"\"{s.Replace("\"", "\"\"", StringComparison.Ordinal)}\"" : s;
    }

    public static string ToCsv(IEnumerable<TurnRecord> records)
    {
        var header = string.Join(",", CsvColumns);
        var body = string.Join("\n", records.Select(Flatten).Select(r => string.Join(",", CsvColumns.Select(c => Cell(r.GetValueOrDefault(c))))));
        return body.Length > 0 ? $"{header}\n{body}\n" : $"{header}\n";
    }

    public static string ToJsonl(IEnumerable<TurnRecord> records) =>
        string.Concat(records.Select(r => JsonSerializer.Serialize(r, TelemetryJson.Options) + "\n"));

    private static SeriesSummary Summarize(List<double> xs)
    {
        if (xs.Count == 0)
            return new SeriesSummary(0, double.NaN, double.NaN, double.NaN, double.NaN);
        var mean = 0.0;
        foreach (var x in xs)
            mean += x;
        mean /= xs.Count;
        if (xs.Count < 2)
            return new SeriesSummary(xs.Count, xs.Min(), xs.Max(), mean, double.NaN);
        var sq = 0.0;
        foreach (var x in xs)
            sq += (x - mean) * (x - mean);
        return new SeriesSummary(xs.Count, xs.Min(), xs.Max(), mean, Math.Sqrt(sq / (xs.Count - 1)));
    }

    /// <summary>Summary statistics per numeric column, and last − first for every persona column with ≥ 2 values.</summary>
    public static (Dictionary<string, SeriesSummary> Columns, Dictionary<string, double> Drift) Summarize(IReadOnlyList<TurnRecord> records)
    {
        var rows = records.Select(r => (r.TurnIndex, Flat: Flatten(r))).ToList();
        var columns = new Dictionary<string, SeriesSummary>(StringComparer.Ordinal);
        var drift = new Dictionary<string, double>(StringComparer.Ordinal);
        foreach (var col in CsvColumns)
        {
            double? Num(Dictionary<string, JsonNode?> row) => row.GetValueOrDefault(col) is JsonValue v && v.GetValueKind() == JsonValueKind.Number ? v.GetValue<double>() : null;
            var values = rows.Select(r => Num(r.Flat)).Where(v => v is { } x && double.IsFinite(x)).Select(v => v!.Value).ToList();
            columns[col] = Summarize(values);
            if (col.StartsWith("persona.", StringComparison.Ordinal) && values.Count >= 2)
            {
                var ordered = rows.Where(r => Num(r.Flat) is not null).OrderBy(r => r.TurnIndex).ToList();
                drift[col] = Num(ordered[^1].Flat)!.Value - Num(ordered[0].Flat)!.Value;
            }
        }
        return (columns, drift);
    }
}
