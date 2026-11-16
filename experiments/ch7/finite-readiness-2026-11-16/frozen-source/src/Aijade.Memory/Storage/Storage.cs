using System.Text.Json;
using System.Text.Json.Serialization;

using Aijade.Memory.Beliefs;
using Aijade.Memory.Hac;
using Aijade.Memory.Identity;
using Aijade.Memory.Interventions;
using Aijade.Memory.Model;
using Aijade.Memory.Replay;

namespace Aijade.Memory.Storage;

// v7 §26 storage tiering: an adapter only carries state — retention and salience stay HAC's decisions — and
// every method is synchronous, so persistence never enters the gating path and I/O jitter cannot disturb an experiment.

public sealed record StoreCollections(
    IReadOnlyList<Episode> Episodes, IReadOnlyList<SemanticFact> Facts, IReadOnlyList<ProceduralMemory> Procedural, IReadOnlyList<WorkingMemory> Working,
    IReadOnlyList<Belief> Beliefs, IReadOnlyList<BeliefRevision> BeliefRevisions, IReadOnlyList<BeliefRejection> BeliefRejections);

public sealed record HacSnapshotState(HacState Z, int Call);

public sealed record CdiSnapshotState(IdentityState State, IReadOnlyList<IdentityVersion> Versions);

/// <summary>Serializable store state: plain data only (no adapter, no functions, no cycles).</summary>
public sealed record StoreSnapshot(
    string Schema, MemoryConfig Config, StoreCollections Collections, HacSnapshotState? Hac = null, CdiSnapshotState? Cdi = null,
    ResolvedIntervention? Intervention = null, IReadOnlyList<ReplayBundle>? CbrBundles = null)
{
    public const string SchemaId = "aijade.store_snapshot@1";

    /// <summary>camelCase properties, snake_case enum names, no nulls written.</summary>
    public static JsonSerializerOptions JsonOptions { get; } = new(JsonSerializerDefaults.Web)
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower) },
        NumberHandling = JsonNumberHandling.AllowNamedFloatingPointLiterals,
    };

    public string ToJson() => JsonSerializer.Serialize(this, JsonOptions);

    public static StoreSnapshot? FromJson(string json)
    {
        var s = JsonSerializer.Deserialize<StoreSnapshot>(json, JsonOptions);
        return s?.Schema == SchemaId ? s : null;
    }
}

public interface IStorageAdapter
{
    string Kind { get; }

    void Persist(StoreSnapshot snapshot);

    StoreSnapshot? Load();

    void Clear();
}

/// <summary>The default for tests and the no-persistence baseline; holds a deep copy so later mutation cannot leak in.</summary>
public sealed class InMemoryStorageAdapter : IStorageAdapter
{
    private string? _json;

    public string Kind => "memory";

    public void Persist(StoreSnapshot snapshot) => _json = snapshot.ToJson();

    public StoreSnapshot? Load() => _json is null ? null : StoreSnapshot.FromJson(_json);

    public void Clear() => _json = null;
}

/// <summary>One JSON snapshot per file; a missing or unreadable file loads as nothing.</summary>
public sealed class JsonFileStorageAdapter(string filePath) : IStorageAdapter
{
    public string Kind => "json-file";

    public void Persist(StoreSnapshot snapshot) => File.WriteAllText(filePath, snapshot.ToJson());

    public StoreSnapshot? Load()
    {
        try
        {
            return File.Exists(filePath) ? StoreSnapshot.FromJson(File.ReadAllText(filePath)) : null;
        }
        catch (JsonException)
        {
            return null;
        }
        catch (IOException)
        {
            return null;
        }
    }

    public void Clear()
    {
        if (File.Exists(filePath))
            File.Delete(filePath);
    }
}
