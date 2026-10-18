using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Contracts;

namespace Aijade.Memory.Experiments;

// v7 §38: every eval upserts its ExperimentManifest into a committed registry at startup, so the seed, conditions and
// committed metrics of each published claim are recorded and can be re-run. The file format is unchanged, so the
// registry is read and rewritten byte-for-byte.

public sealed record ManifestSpec(
    string Id, string Name, IReadOnlyList<ExperimentCondition> Conditions, IReadOnlyList<string> Metrics,
    string? Version = null, double? Seed = null, string? Notes = null);

public sealed class ExperimentManifestException(string message) : Exception(message);

public static class ExperimentManifests
{
    public const double DefaultSeed = 0;

    /// <summary>The version of the code under test (the assembly version, major.minor.patch).</summary>
    public static string PackageVersion { get; } = typeof(ExperimentManifests).Assembly.GetName().Version is { } v ? $"{v.Major}.{v.Minor}.{v.Build}" : "0.1.0";

    /// <summary>Build a §38 manifest, pin the seed and validate it. Throws on a non-finite seed, no condition or no metric.</summary>
    public static ExperimentManifest Build(ManifestSpec spec, TimeProvider? time = null)
    {
        var seed = spec.Seed ?? DefaultSeed;
        if (!double.IsFinite(seed))
            throw new ExperimentManifestException($"ExperimentManifest \"{spec.Id}\" requires a finite seed (reproducibility)");
        var manifest = new ExperimentManifest(spec.Id, spec.Name, spec.Version ?? PackageVersion, seed, spec.Conditions, spec.Metrics,
            (time ?? TimeProvider.System).GetUtcNow().ToUnixTimeMilliseconds(), string.IsNullOrEmpty(spec.Notes) ? null : spec.Notes);
        var v = ContractValidation.Validate(manifest);
        if (!v.Ok)
            throw new ExperimentManifestException($"ExperimentManifest \"{spec.Id}\" invalid: {v.Reason}");
        return manifest;
    }

    public static JsonObject ToJson(ExperimentManifest m)
    {
        var o = new JsonObject
        {
            ["id"] = m.Id,
            ["schema"] = ExperimentManifest.SchemaId,
            ["name"] = m.Name,
            ["version"] = m.Version,
            ["seed"] = m.Seed,
            ["conditions"] = new JsonArray(m.Conditions.Select(ConditionToJson).ToArray<JsonNode?>()),
            ["metrics"] = new JsonArray(m.Metrics.Select(x => (JsonNode?)x).ToArray()),
            ["createdAt"] = m.CreatedAt,
        };
        if (m.Notes is not null)
            o["notes"] = m.Notes;
        return o;
    }

    private static JsonObject ConditionToJson(ExperimentCondition c)
    {
        var o = new JsonObject { ["name"] = c.Name, ["description"] = c.Description };
        if (c.Params is not null)
            o["params"] = JsonSerializer.SerializeToNode(c.Params);
        return o;
    }
}

/// <summary>The committed registry file, keyed by manifest id; re-registration overwrites but keeps the first createdAt.</summary>
public sealed class ExperimentRegistry(string path, TimeProvider? time = null)
{
    public const string Schema = "aijade.experiment_registry@1";

    private readonly TimeProvider _time = time ?? TimeProvider.System;

    public string Path { get; } = path;

    /// <summary>The registry as stored, or an empty one when the file is absent, corrupt or of another schema.</summary>
    public JsonObject Read()
    {
        try
        {
            if (File.Exists(Path) && JsonNode.Parse(File.ReadAllText(Path)) is JsonObject parsed
                && parsed["schema"] is JsonValue s && s.TryGetValue<string>(out var schema) && schema == Schema
                && parsed["experiments"] is JsonObject)
                return parsed;
        }
        catch (JsonException)
        {
            // fall through to an empty registry
        }
        return new JsonObject { ["schema"] = Schema, ["updatedAt"] = 0, ["count"] = 0, ["experiments"] = new JsonObject() };
    }

    /// <summary>Upsert a manifest and persist the registry. Refuses an invalid manifest.</summary>
    public JsonObject Register(ExperimentManifest manifest)
    {
        var v = ContractValidation.Validate(manifest);
        if (!v.Ok)
            throw new ExperimentManifestException($"Refusing to register invalid ExperimentManifest \"{manifest.Id}\": {v.Reason}");
        var reg = Read();
        var experiments = (JsonObject)reg["experiments"]!;
        var entry = ExperimentManifests.ToJson(manifest);
        if (experiments[manifest.Id] is JsonObject prev && prev["createdAt"] is { } createdAt)
            entry["createdAt"] = createdAt.DeepClone();
        // Assigning an existing key keeps its position, as in a JS object.
        experiments[manifest.Id] = entry;
        reg["updatedAt"] = _time.GetUtcNow().ToUnixTimeMilliseconds();
        reg["count"] = experiments.Count;
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(Path))!);
        File.WriteAllText(Path, JsFormat.Stringify(reg, 2) + "\n");
        return reg;
    }
}
