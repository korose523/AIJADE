using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;
using Aijade.Memory.Kernel;

namespace Aijade.Tests;

/// <summary>PEF must equal the recorded golden data on 60 randomized persona stacks.</summary>
public class PefTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "pef-golden.json"))).RootElement;

    private static T ParseEnum<T>(string snake) where T : struct, System.Enum => System.Enum.Parse<T>(snake.Replace("_", "", StringComparison.Ordinal), ignoreCase: true);

    private static double? D(JsonElement o, string name) => o.TryGetProperty(name, out var v) ? v.GetDouble() : null;

    private static PartialExpression? Partial(JsonElement x, string name) => x.TryGetProperty(name, out var o)
        ? new PartialExpression(D(o, "valence"), D(o, "arousal"), D(o, "dominance"), D(o, "intimacy"), D(o, "certainty"), D(o, "curiosity"), D(o, "playfulness"), D(o, "reflection"), D(o, "urgency"))
        : null;

    private static List<string>? Strings(JsonElement o, string name) => o.TryGetProperty(name, out var a) ? a.EnumerateArray().Select(s => s.GetString()!).ToList() : null;

    private static PersonaInput Input(JsonElement x) => new(
        ParseEnum<DialogueAct>(x.GetProperty("dialogueAct").GetString()!),
        Character: Partial(x, "character"),
        ExpressiveState: Partial(x, "expressiveState"),
        Relationship: x.TryGetProperty("relationship", out var r) ? new RelationshipModel(D(r, "intimacy"), D(r, "formality")) : null,
        Developmental: x.TryGetProperty("developmental", out var dev) ? new DevelopmentalSelf(Strings(dev, "interests"), Strings(dev, "milestones")) : null,
        SceneContext: x.TryGetProperty("sceneContext", out var s) ? s.GetString() : null);

    private static void AssertExpression(JsonElement e, ExpressionVector v)
    {
        Assert.Equal(e.GetProperty("valence").GetDouble(), v.Valence);
        Assert.Equal(e.GetProperty("arousal").GetDouble(), v.Arousal);
        Assert.Equal(e.GetProperty("dominance").GetDouble(), v.Dominance);
        Assert.Equal(e.GetProperty("intimacy").GetDouble(), v.Intimacy);
        Assert.Equal(e.GetProperty("certainty").GetDouble(), v.Certainty);
        Assert.Equal(e.GetProperty("curiosity").GetDouble(), v.Curiosity);
        Assert.Equal(e.GetProperty("playfulness").GetDouble(), v.Playfulness);
        Assert.Equal(e.GetProperty("reflection").GetDouble(), v.Reflection);
        Assert.Equal(e.GetProperty("urgency").GetDouble(), v.Urgency);
    }

    [Fact]
    public void Expression_and_channels_match_the_original()
    {
        foreach (var (x, o) in Golden.GetProperty("inputs").EnumerateArray().Zip(Golden.GetProperty("outputs").EnumerateArray()))
        {
            var input = Input(x);
            var e = Pef.MapPersonaToExpression(input);
            AssertExpression(o.GetProperty("e"), e);
            var ch = Pef.DeriveChannels(e, input.DialogueAct);
            var g = o.GetProperty("ch");
            Assert.Equal<IEnumerable<string?>>(
                [g.GetProperty("textStyle").GetString(), g.GetProperty("face").GetString(), g.GetProperty("gaze").GetString(), g.GetProperty("gesture").GetString(),
                    g.GetProperty("posture").GetString(), g.GetProperty("turnTaking").GetString(), g.GetProperty("cameraBehavior").GetString()],
                [ch.TextStyle, ch.Face, ch.Gaze, ch.Gesture, ch.Posture, ch.TurnTaking, ch.CameraBehavior]);
            var p = g.GetProperty("voiceProsody");
            Assert.Equal(new VoiceProsody(p.GetProperty("rate").GetDouble(), p.GetProperty("pitch").GetDouble(), p.GetProperty("energy").GetDouble()), ch.VoiceProsody);
        }
    }

    [Fact]
    public void Consistency_verdicts_match_the_original()
    {
        foreach (var (o, v) in Golden.GetProperty("obs").EnumerateArray().Zip(Golden.GetProperty("verdicts").EnumerateArray()))
        {
            var obs = new ConsistencyObservation(D(o, "faceIdentityDrift"), D(o, "clothingDrift"), D(o, "voiceprintDrift"), D(o, "prosodyDrift"),
                Strings(o, "forbiddenActions"), D(o, "emotionSemanticConflict"), D(o, "lipSyncDeviationMs"),
                o.TryGetProperty("sceneContinuityBreak", out var b) ? b.GetBoolean() : null, Strings(o, "boundaryViolations"));
            var actual = Pef.IdentityConsistencyCheck(obs);
            Assert.Equal(v.GetProperty("ok").GetBoolean(), actual.Ok);
            Assert.Equal(ParseEnum<DegradeMode>(v.GetProperty("degrade").GetString()!), actual.Degrade);
            Assert.Equal(v.GetProperty("failures").EnumerateArray().Select(f => (ParseEnum<ConsistencyFailureKind>(f.GetProperty("kind").GetString()!), f.GetProperty("detail").GetString())),
                actual.Failures.Select(f => (f.Kind, (string?)f.Detail)));
        }
    }

    private static JsonObject Envelope() => new()
    {
        ["event_id"] = "evt_1",
        ["trace_id"] = "tr_1",
        ["correlation_id"] = "cor_1",
        ["timestamp"] = 1_700_000_000_000,
        ["producer"] = "pef",
        ["origin_device"] = "dev",
        ["privacy_level"] = 2,
        ["evidence_refs"] = new JsonArray("e"),
        ["causal_context_refs"] = new JsonArray(),
        ["risk_score"] = 0.25,
        ["idempotency_key"] = "idem_1",
        ["replay_mode"] = "replay",
        ["risk_level"] = "medium",
        ["tick"] = 3,
    };

    private static readonly PerformanceIds Ids = new("pi-1", "a", "u", "ps-1");

    [Fact]
    public void Intent_and_render_events_are_byte_identical_to_the_original()
    {
        var intent = Pef.BuildPerformanceIntent(new PersonaInput(DialogueAct.Greet, SceneContext: "cafe"), Ids, 12.5, 800);
        AssertExpression(Golden.GetProperty("intent").GetProperty("expression"), intent.Expression);
        Assert.True(ContractValidationV8.Validate(intent).Ok);
        Assert.Equal("cafe", intent.SceneContext);
        Assert.Equal(12.5, intent.TimeMarked);
        Assert.Equal(Golden.GetProperty("requested").GetString(), JsFormat.Stringify(Pef.BuildPersonaRenderRequestedEvent(intent, "s-1", Envelope())));
        Assert.Equal(Golden.GetProperty("ready").GetString(),
            JsFormat.Stringify(Pef.BuildLpmRenderReadyEvent(new LpmRenderReceipt("s-1", "pi-1", "face=smile;gaze=soft", "av-9"), Envelope())));
    }

    [Fact]
    public void Render_events_refuse_empty_identities_and_lying_receipts()
    {
        var intent = Pef.BuildPerformanceIntent(new PersonaInput(DialogueAct.Inform), Ids, 0, 100);
        Assert.Throws<EventValidationException>(() => Pef.BuildPersonaRenderRequestedEvent(intent with { PersonaSnapshotRef = "" }, "s", Envelope()));
        var payload = (JsonObject)Pef.BuildPersonaRenderRequestedEvent(intent, "s", Envelope())["payload"]!;
        Assert.Equal(["session_id", "persona_snapshot_ref", "intent_ref"], payload.Select(kv => kv.Key));
        Assert.Contains("没有渲染发生", Assert.Throws<ArgumentException>(() => Pef.BuildLpmRenderReadyEvent(new LpmRenderReceipt("s", "r", ""), Envelope())).Message, StringComparison.Ordinal);
        foreach (var asset in new[] { null, "" })
        {
            var p = (JsonObject)Pef.BuildLpmRenderReadyEvent(new LpmRenderReceipt("s", "r", "h", asset), Envelope())["payload"]!;
            Assert.False(p.ContainsKey("asset_version_hash"));
        }
        Assert.Throws<EventValidationException>(() => Pef.BuildLpmRenderReadyEvent(new LpmRenderReceipt("", "r", "h"), Envelope()));
        Assert.Throws<EventValidationException>(() => Pef.BuildLpmRenderReadyEvent(new LpmRenderReceipt("s", "", "h"), Envelope()));
    }

    [Fact]
    public void Persona_mapping_follows_the_declared_modulations()
    {
        var inform = Pef.MapPersonaToExpression(new PersonaInput(DialogueAct.Inform));
        var comfort = Pef.MapPersonaToExpression(new PersonaInput(DialogueAct.Comfort));
        Assert.True(comfort.Intimacy > inform.Intimacy && comfort.Arousal < inform.Arousal);
        Assert.True(Pef.MapPersonaToExpression(new PersonaInput(DialogueAct.Question)).Curiosity > inform.Curiosity);
        var formal = Pef.MapPersonaToExpression(new PersonaInput(DialogueAct.Inform, Relationship: new RelationshipModel(Formality: 1)));
        Assert.True(formal.Playfulness < inform.Playfulness);
        var curious = Pef.MapPersonaToExpression(new PersonaInput(DialogueAct.Inform, Developmental: new DevelopmentalSelf(["a", "b", "c"])));
        Assert.True(curious.Curiosity > inform.Curiosity);
        var extreme = Pef.MapPersonaToExpression(new PersonaInput(DialogueAct.Celebrate, Character: new PartialExpression(9, 9, 9, 9, 9, 9, 9, 9, 9),
            ExpressiveState: new PartialExpression(double.NaN, -9), Relationship: new RelationshipModel(99, -99)));
        Assert.InRange(extreme.Valence, -1, 1);
        Assert.InRange(extreme.Arousal, 0, 1);
        Assert.Equal(0, extreme.Valence);
    }

    [Fact]
    public void Clamp_and_channels_respect_ranges()
    {
        var c = Pef.Clamp(new ExpressionVector(-3, 2, -1, 0.5, double.PositiveInfinity, 0.2, 0.3, 0.4, 0.5));
        Assert.Equal(new ExpressionVector(-1, 1, 0, 0.5, 0, 0.2, 0.3, 0.4, 0.5), c);
        Assert.Equal(Pef.Neutral, Pef.Clamp(Pef.Neutral));
        Assert.Equal("backchannel", Pef.DeriveChannels(Pef.Neutral, DialogueAct.Backchannel).TurnTaking);
        Assert.Equal("yield", Pef.DeriveChannels(Pef.Neutral, DialogueAct.Question).TurnTaking);
        Assert.Equal("bright_smile", Pef.DeriveChannels(Pef.Neutral with { Valence = 0.8, Arousal = 0.8 }, DialogueAct.Celebrate).Face);
        var fast = Pef.DeriveChannels(Pef.Neutral with { Urgency = 1 }, DialogueAct.Inform).VoiceProsody.Rate;
        Assert.True(fast > Pef.DeriveChannels(Pef.Neutral, DialogueAct.Inform).VoiceProsody.Rate);
    }

    [Fact]
    public void Duplex_scheduling_and_degrade_policy()
    {
        Assert.Equal("backchannel", Pef.ScheduleDuplex(DuplexEvent.ListenSignal).TurnTaking);
        Assert.Equal(new DuplexDecision("yield", "listen_pose", true, true), Pef.ScheduleDuplex(DuplexEvent.UserInterruption));
        Assert.Equal(DegradeMode.None, Pef.IdentityConsistencyCheck(new ConsistencyObservation(0.1, 0.1, 0.1, 0.1)).Degrade);
        Assert.Equal(DegradeMode.Voice, Pef.IdentityConsistencyCheck(new ConsistencyObservation(FaceIdentityDrift: 0.5, ClothingDrift: 0.9)).Degrade);
        Assert.Equal(DegradeMode.Avatar, Pef.IdentityConsistencyCheck(new ConsistencyObservation(ClothingDrift: 0.9)).Degrade);
        Assert.True(Pef.IdentityConsistencyCheck(new ConsistencyObservation(FaceIdentityDrift: 0.3), new ConsistencyThresholds(FaceIdentityDrift: 0.5)).Ok);
    }
}
