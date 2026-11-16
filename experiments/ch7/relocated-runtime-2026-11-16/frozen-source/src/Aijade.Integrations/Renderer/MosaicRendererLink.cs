using System.Diagnostics;
using System.Globalization;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Memory.Contracts;

namespace Aijade.Integrations.Renderer;

// Drive an external renderer that speaks the AIJADE renderer contract — the author's MOSAIC native MMD client
// (`--behavior-live PORT`) — from the companion's PEF PerformanceIntents. The contract (MOSAIC Mosaic.Scene.Core
// AijadePackets; AIJADE brain/cerebellum/renderer guide §3.5): the renderer consumes AffectToAvatarPacket and
// ControlToAvatarPosePacket, one JSON object per UDP datagram (≤ 8 KiB) on 127.0.0.1, each carrying run_id, a per-type
// strictly increasing seq, a non-decreasing t_sim and schema_version v1.x; fields outside the packet type's whitelist are
// refused. The renderer never feeds back into the affect chain; what it applied comes back as RenderStatePacket rows
// (aijade-render-state.jsonl), which RenderStateReceipts turns into the server's render receipts.

/// <summary>Stamps the AIJADE base fields: run_id, seq per packet type (from 0), t_sim (seconds since start), schema_version.</summary>
public sealed class AijadePacketStamper(string runId, Func<double>? clock = null)
{
    public const string SchemaVersion = "v1.0";
    private readonly Func<double> clock = clock ?? StopwatchClock();
    private readonly Dictionary<string, long> seq = new(StringComparer.Ordinal);
    private double lastT;

    public string RunId { get; } = runId;

    private static Func<double> StopwatchClock()
    {
        var sw = Stopwatch.StartNew();
        return () => sw.Elapsed.TotalSeconds;
    }

    public JsonObject Stamp(JsonObject packet)
    {
        var type = packet["packet_type"]?.GetValue<string>() ?? throw new ArgumentException("packet_type required", nameof(packet));
        lock (seq)
        {
            var next = seq.TryGetValue(type, out var s) ? s + 1 : 0;
            seq[type] = next;
            lastT = Math.Max(lastT, Math.Round(clock(), 4)); // t_sim must never go back
            packet["run_id"] = RunId;
            packet["seq"] = next;
            packet["t_sim"] = lastT;
            packet["schema_version"] = SchemaVersion;
            return packet;
        }
    }
}

/// <summary>PerformanceIntent → the two renderer packets. Deterministic: the same intent always gives the same packets.</summary>
public static class AijadeRendererPackets
{
    public const string Affect = "AffectToAvatarPacket", Control = "ControlToAvatarPosePacket", RenderState = "RenderStatePacket";

    /// <summary>The emotion dimensions the renderer contract maps (valence −1…1, the others 0…1, as in PEF).</summary>
    public static readonly string[] EmotionSemantics = ["valence", "arousal", "dominance", "curiosity"];

    /// <summary>The pose dimensions sent (normalised −1…1; the renderer scales them to ±60°/±30°/±30°/±20°).</summary>
    public static readonly string[] PoseSemantics = ["head_yaw", "head_pitch", "head_roll", "lean"];

    // PEF posture and gaze channels → normalised pose. The values are a presentational choice of this adapter, kept small
    // so that the renderer's own behaviour layer (breathing, gaze, nods) stays visible on top.
    private static readonly Dictionary<string, (double Pitch, double Lean)> Postures = new(StringComparer.Ordinal)
    {
        ["upright_forward"] = (0.10, 0.20), ["leaning_in"] = (0.0, 0.35), ["relaxed_settled"] = (-0.05, -0.15), ["neutral_engaged"] = (0, 0),
    };

    private static readonly Dictionary<string, (double Yaw, double Pitch, double Roll)> Gazes = new(StringComparer.Ordinal)
    {
        ["briefly_averted_thinking"] = (0.20, 0.15, 0), ["sustained_soft"] = (0, 0, 0.15), ["steady_direct"] = (0, 0, 0), ["natural_conversational"] = (0, 0, 0),
    };

    private static double R(double v) => Math.Round(Math.Clamp(v, -1, 1), 6);

    /// <summary>
    /// The affect packet: the PEF emotion vector (and, when the caller knows the model's morphs, their weights 0…1), the face
    /// channel as the animation hint, and the intent id as trace_id so that render states can be paired with the intent.
    /// </summary>
    public static JsonObject AffectOf(PerformanceIntent intent, string? episodeId = null, IReadOnlyDictionary<string, double>? morphTargets = null)
    {
        var e = intent.Expression;
        var packet = new JsonObject
        {
            ["packet_type"] = Affect,
            ["trace_id"] = intent.Id,
            ["avatar_emotion_vector"] = new JsonArray(R(e.Valence), Math.Clamp(R(e.Arousal), 0, 1), Math.Clamp(R(e.Dominance), 0, 1), Math.Clamp(R(e.Curiosity), 0, 1)),
            ["avatar_emotion_semantics"] = new JsonArray([.. EmotionSemantics.Select(s => (JsonNode)s)]),
        };
        if (episodeId is { Length: > 0 and <= 128 })
            packet["episode_id"] = episodeId;
        if (intent.Face is { Length: > 0 and <= 128 } face)
            packet["animation_state_hint"] = face;
        if (morphTargets is { Count: > 0 })
        {
            var targets = new JsonObject();
            foreach (var (name, weight) in morphTargets)
            {
                if (!double.IsFinite(weight) || weight is < 0 or > 1)
                    throw new ArgumentOutOfRangeException(nameof(morphTargets), $"morph weight {name}={weight} outside 0…1");
                targets[name] = Math.Round(weight, 6);
            }
            packet["mmd_morph_targets"] = targets;
        }
        return packet;
    }

    /// <summary>The pose packet from the PEF posture and gaze channels (idle locomotion: the stage owns the root).</summary>
    public static JsonObject ControlOf(PerformanceIntent intent, string? episodeId = null)
    {
        var (pitchP, lean) = Postures.GetValueOrDefault(intent.Posture ?? "", (0, 0));
        var (yaw, pitchG, roll) = Gazes.GetValueOrDefault(intent.Gaze ?? "", (0, 0, 0));
        var packet = new JsonObject
        {
            ["packet_type"] = Control,
            ["trace_id"] = intent.Id,
            ["pose_params"] = new JsonArray(R(yaw), R(pitchP + pitchG), R(roll), R(lean)),
            ["pose_semantics"] = new JsonArray([.. PoseSemantics.Select(s => (JsonNode)s)]),
            ["locomotion_mode"] = "idle",
        };
        if (episodeId is { Length: > 0 and <= 128 })
            packet["episode_id"] = episodeId;
        return packet;
    }
}

/// <summary>Sends stamped packets to the renderer as UDP datagrams on the loopback interface.</summary>
public sealed class MosaicRendererLink : IDisposable
{
    public const int MaxDatagram = 8192;
    private readonly UdpClient udp = new();
    private readonly int port;

    public MosaicRendererLink(int port, string? runId = null, Func<double>? clock = null)
    {
        if (port is < 1 or > 65535)
            throw new ArgumentOutOfRangeException(nameof(port));
        this.port = port;
        Stamper = new AijadePacketStamper(runId ?? $"aijade-{DateTime.UtcNow:yyyyMMddTHHmmss}", clock);
    }

    public AijadePacketStamper Stamper { get; }

    public int Sent { get; private set; }

    /// <summary>Send the affect and pose packets of one intent; returns the stamped packets (for logging).</summary>
    public async Task<IReadOnlyList<JsonObject>> SendAsync(PerformanceIntent intent, string? episodeId = null, IReadOnlyDictionary<string, double>? morphTargets = null, CancellationToken ct = default)
    {
        JsonObject[] packets = [Stamper.Stamp(AijadeRendererPackets.AffectOf(intent, episodeId, morphTargets)), Stamper.Stamp(AijadeRendererPackets.ControlOf(intent, episodeId))];
        foreach (var p in packets)
        {
            var data = Encoding.UTF8.GetBytes(p.ToJsonString());
            if (data.Length > MaxDatagram)
                throw new InvalidOperationException($"packet of {data.Length} bytes exceeds the renderer's {MaxDatagram}-byte datagram limit");
            await udp.SendAsync(data, "127.0.0.1", port, ct).ConfigureAwait(false);
            Sent++;
        }
        return packets;
    }

    public void Dispose() => udp.Dispose();
}

/// <summary>What the renderer applied for one intent: the parameters (morph.* and bone.*) and the renderer's own hash.</summary>
public sealed record RenderedIntent(string IntentId, JsonObject AppliedParams, string RendererHash, double TSim);

/// <summary>Reads the renderer's RenderStatePacket rows back as per-intent receipts (the first frame that showed each intent).</summary>
public static class RenderStateReceipts
{
    public static IReadOnlyList<RenderedIntent> Read(string path, string? runId = null)
    {
        var seen = new Dictionary<string, RenderedIntent>(StringComparer.Ordinal);
        foreach (var line in File.ReadLines(path))
        {
            if (line.Length == 0)
                continue;
            var row = JsonNode.Parse(line)!.AsObject();
            if (row["packet_type"]?.GetValue<string>() != AijadeRendererPackets.RenderState)
                continue;
            if (runId is not null && row["run_id"]?.GetValue<string>() != runId)
                continue;
            var applied = new JsonObject();
            if (row["expressions_applied"] is JsonObject morphs)
            {
                foreach (var (k, v) in morphs)
                    applied[$"morph.{k}"] = v?.DeepClone();
            }
            if (row["avatar_state"]?["bones"] is JsonObject bones)
            {
                foreach (var (k, v) in bones)
                    applied[$"bone.{k}"] = v?.DeepClone();
            }
            var hash = row["applied_params_hash"]?.GetValue<string>() ?? "";
            var t = row["t_sim"]?.GetValue<double>() ?? 0;
            foreach (var consumed in row["consumed"]?.AsArray() ?? [])
            {
                if (consumed?["trace_id"]?.GetValue<string>() is { Length: > 0 } id && !seen.ContainsKey(id) && applied.Count > 0)
                    seen[id] = new RenderedIntent(id, (JsonObject)applied.DeepClone(), hash, t);
            }
        }
        return [.. seen.Values.OrderBy(r => r.TSim)];
    }

    /// <summary>The renderer's applied-params hash recomputed from a row's parameters (sorted keys, 6 decimals, SHA-256).</summary>
    public static string RendererHash(JsonObject applied) =>
        Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(Encoding.UTF8.GetBytes(string.Join("\n",
            applied.OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => p.Key + "=" + p.Value!.GetValue<double>().ToString("F6", CultureInfo.InvariantCulture)))))).ToLowerInvariant();
}
