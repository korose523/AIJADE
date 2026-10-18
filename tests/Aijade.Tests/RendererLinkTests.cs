using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Integrations.Renderer;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;

namespace Aijade.Tests;

/// <summary>The AIJADE renderer contract as the MOSAIC native MMD client implements it, from the sending side.</summary>
public class RendererLinkTests
{
    private static PerformanceIntent Intent(string id, DialogueAct act, PartialExpression? state = null) =>
        Pef.BuildPerformanceIntent(new PersonaInput(act, ExpressiveState: state), new PerformanceIds(id, "aijade", "user:1", "persona:default"), 0, 2);

    [Fact]
    public void Intents_become_whitelisted_packets_with_bounded_values()
    {
        var intent = Intent("pi_1", DialogueAct.Celebrate, new PartialExpression(Valence: 0.9, Arousal: 0.8, Curiosity: 0.7));
        var affect = AijadeRendererPackets.AffectOf(intent, "chat:42", new Dictionary<string, double> { ["笑い"] = 0.74 });
        Assert.Equal("AffectToAvatarPacket", affect["packet_type"]!.GetValue<string>());
        Assert.Equal("pi_1", affect["trace_id"]!.GetValue<string>());
        Assert.Equal(["valence", "arousal", "dominance", "curiosity"], affect["avatar_emotion_semantics"]!.AsArray().Select(x => x!.GetValue<string>()));
        var v = affect["avatar_emotion_vector"]!.AsArray().Select(x => x!.GetValue<double>()).ToArray();
        Assert.InRange(v[0], -1, 1);
        Assert.All(v.Skip(1), x => Assert.InRange(x, 0, 1));
        Assert.Equal(0.74, affect["mmd_morph_targets"]!["笑い"]!.GetValue<double>());
        Assert.Throws<ArgumentOutOfRangeException>(() => AijadeRendererPackets.AffectOf(intent, morphTargets: new Dictionary<string, double> { ["笑い"] = 74 }));

        var thinking = Intent("pi_2", DialogueAct.Inform, new PartialExpression(Reflection: 1, Intimacy: 0, Dominance: 0.4));
        Assert.Equal("briefly_averted_thinking", thinking.Gaze);
        var control = AijadeRendererPackets.ControlOf(thinking);
        Assert.Equal(["head_yaw", "head_pitch", "head_roll", "lean"], control["pose_semantics"]!.AsArray().Select(x => x!.GetValue<string>()));
        Assert.All(control["pose_params"]!.AsArray(), x => Assert.InRange(x!.GetValue<double>(), -1, 1));
        Assert.True(control["pose_params"]![0]!.GetValue<double>() > 0, "thinking looks briefly away");
        Assert.Equal("idle", control["locomotion_mode"]!.GetValue<string>());
        // fields the contract does not know are never added
        string[] baseFields = ["packet_type", "run_id", "episode_id", "t_sim", "seq", "schema_version", "dt_ms", "trace_id"];
        Assert.All(affect.Select(p => p.Key), k => Assert.Contains(k, baseFields.Concat(["mmd_morph_targets", "avatar_emotion_vector", "avatar_emotion_semantics", "animation_state_hint"])));
        Assert.All(control.Select(p => p.Key), k => Assert.Contains(k, baseFields.Concat(["pose_params", "pose_semantics", "locomotion_mode"])));
    }

    [Fact]
    public void The_stamper_keeps_one_strictly_increasing_stream_per_packet_type_and_never_turns_time_back()
    {
        var t = new Queue<double>([0.5, 0.4, 1.25, 1.25]);
        var stamper = new AijadePacketStamper("run-1", () => t.Dequeue());
        var a0 = stamper.Stamp(new JsonObject { ["packet_type"] = "AffectToAvatarPacket" });
        var c0 = stamper.Stamp(new JsonObject { ["packet_type"] = "ControlToAvatarPosePacket" });
        var a1 = stamper.Stamp(new JsonObject { ["packet_type"] = "AffectToAvatarPacket" });
        var c1 = stamper.Stamp(new JsonObject { ["packet_type"] = "ControlToAvatarPosePacket" });
        Assert.Equal([0L, 0L, 1L, 1L], new[] { a0, c0, a1, c1 }.Select(p => p["seq"]!.GetValue<long>()));
        Assert.Equal([0.5, 0.5, 1.25, 1.25], new[] { a0, c0, a1, c1 }.Select(p => p["t_sim"]!.GetValue<double>())); // the clock's 0.4 is held at 0.5
        Assert.All(new[] { a0, c0, a1, c1 }, p => Assert.Equal(("run-1", "v1.0"), (p["run_id"]!.GetValue<string>(), p["schema_version"]!.GetValue<string>())));
    }

    [Fact]
    public async Task Packets_arrive_as_one_json_object_per_loopback_datagram()
    {
        var ct = TestContext.Current.CancellationToken;
        using var listener = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0));
        var port = ((IPEndPoint)listener.Client.LocalEndPoint!).Port;
        using var link = new MosaicRendererLink(port, "run-udp");
        var sent = await link.SendAsync(Intent("pi_3", DialogueAct.Comfort), "chat:1", ct: ct);
        var got = new List<JsonObject>();
        for (var i = 0; i < 2; i++)
            got.Add(JsonNode.Parse(Encoding.UTF8.GetString((await listener.ReceiveAsync(ct)).Buffer))!.AsObject());
        Assert.Equal(sent.Select(p => p.ToJsonString()), got.Select(p => p.ToJsonString()));
        Assert.Equal(["AffectToAvatarPacket", "ControlToAvatarPosePacket"], got.Select(p => p["packet_type"]!.GetValue<string>()));
        Assert.Equal(2, link.Sent);
    }

    [Fact]
    public void Render_states_become_one_receipt_per_intent_with_the_renderers_own_hash()
    {
        var path = Path.Combine(Path.GetTempPath(), $"render-state-{Guid.NewGuid():N}.jsonl");
        try
        {
            // rows as the MOSAIC client writes them: consumed packets, applied morphs and bones, and its hash over morph.*/bone.*
            var applied = new JsonObject { ["morph.笑い"] = 0.738, ["bone.頭"] = 0.12 };
            var hash = RenderStateReceipts.RendererHash(applied);
            JsonObject Row(long seq, string trace, double t) => new()
            {
                ["packet_type"] = "RenderStatePacket", ["run_id"] = "run-1", ["t_sim"] = t, ["seq"] = seq, ["schema_version"] = "v1.0",
                ["consumed"] = new JsonArray(new JsonObject { ["packet_type"] = "AffectToAvatarPacket", ["seq"] = seq, ["trace_id"] = trace }),
                ["expressions_applied"] = new JsonObject { ["笑い"] = 0.738 },
                ["avatar_state"] = new JsonObject { ["bones"] = new JsonObject { ["頭"] = 0.12 }, ["hints"] = new JsonObject() },
                ["missing_keys"] = new JsonArray(), ["unmapped"] = new JsonArray(), ["applied_params_hash"] = hash,
            };
            File.WriteAllLines(path, [Row(0, "pi_a", 0.1).ToJsonString(), Row(1, "pi_a", 0.2).ToJsonString(), Row(2, "pi_b", 0.3).ToJsonString()]);
            var receipts = RenderStateReceipts.Read(path, "run-1");
            Assert.Equal(["pi_a", "pi_b"], receipts.Select(r => r.IntentId));
            Assert.Equal(0.1, receipts[0].TSim);
            Assert.Equal(hash, receipts[0].RendererHash);
            Assert.Equal(hash, RenderStateReceipts.RendererHash(receipts[0].AppliedParams));
            Assert.Empty(RenderStateReceipts.Read(path, "another-run"));
        }
        finally
        {
            File.Delete(path);
        }
    }

    /// <summary>
    /// Against the renderer's own parser: opt-in with AIJADE_MOSAIC_CORE_DLL pointing at a built Mosaic.Scene.Core.dll of the
    /// MOSAIC project (loaded read-only from a temporary copy). Every packet must translate without rejection, map every
    /// field it carries (nothing reported as unmapped), and pass the per-stream sequence check.
    /// </summary>
    [Fact]
    public void The_mosaic_renderer_accepts_every_packet_and_maps_every_field()
    {
        if (Environment.GetEnvironmentVariable("AIJADE_MOSAIC_CORE_DLL") is not { Length: > 0 } dll || !File.Exists(dll))
        {
            Assert.Skip("AIJADE_MOSAIC_CORE_DLL is not set; MOSAIC renderer conformance test skipped");
            return;
        }
        var copy = Path.Combine(Path.GetTempPath(), $"mosaic-core-{Guid.NewGuid():N}.dll");
        File.Copy(dll, copy);
        var asm = Assembly.LoadFile(copy);
        var packets = asm.GetType("Mosaic.Scene.Core.AijadePackets", true)!;
        var translate = packets.GetMethod("Translate", [typeof(JsonElement)])!;
        var sequence = Activator.CreateInstance(asm.GetType("Mosaic.Scene.Core.AijadeSequence", true)!)!;
        var accept = sequence.GetType().GetMethod("Accept")!;
        var clock = 0.0;
        var stamper = new AijadePacketStamper("run-conformance", () => clock += 0.25);
        var morphs = new Dictionary<string, double> { ["笑い"] = 0.6, ["まばたき"] = 0.1 };
        var acts = Enum.GetValues<DialogueAct>();
        var n = 0;
        foreach (var (act, i) in acts.Select((a, i) => (a, i)))
        {
            var intent = Intent($"pi_{i}", act, new PartialExpression(Valence: (i % 5 / 2.0) - 1, Arousal: i % 3 / 2.0, Reflection: i % 2, Intimacy: (i + 1) % 2));
            foreach (var packet in new[] { AijadeRendererPackets.AffectOf(intent, "conformance", i % 2 == 0 ? morphs : null), AijadeRendererPackets.ControlOf(intent, "conformance") })
            {
                using var doc = JsonDocument.Parse(stamper.Stamp(packet).ToJsonString());
                object translation;
                try
                {
                    translation = translate.Invoke(null, [doc.RootElement])!;
                }
                catch (TargetInvocationException e)
                {
                    throw new Xunit.Sdk.XunitException($"MOSAIC refused {packet["packet_type"]} for {act}: {e.InnerException!.Message}");
                }
                var unmapped = (string[])translation.GetType().GetProperty("Unmapped")!.GetValue(translation)!;
                Assert.True(unmapped.Length == 0, $"{packet["packet_type"]} for {act}: unmapped {string.Join(", ", unmapped)}");
                var events = (Array)translation.GetType().GetProperty("Events")!.GetValue(translation)!;
                Assert.NotEmpty(events.Cast<object>());
                Assert.True((bool)accept.Invoke(sequence, [translation.GetType().GetProperty("Header")!.GetValue(translation)])!, "sequence check refused a packet");
                n++;
            }
        }
        Assert.Equal(acts.Length * 2, n);
    }
}
