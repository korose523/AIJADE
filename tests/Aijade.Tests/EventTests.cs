using System.Text.Json.Nodes;

using Aijade.Memory.Kernel;

namespace Aijade.Tests;

/// <summary>Behaviour of the kernel event schemas.</summary>
public class EventTests
{
    private static readonly string[] Required =
    [
        "event_id", "trace_id", "correlation_id", "timestamp", "producer", "origin_device", "privacy_level", "evidence_refs",
        "causal_context_refs", "risk_score", "idempotency_key", "replay_mode", "risk_level",
    ];

    private static JsonObject Envelope() => new()
    {
        ["event_id"] = "evt_1", ["trace_id"] = "tr_1", ["correlation_id"] = "cor_1", ["timestamp"] = 1_700_000_000_000,
        ["producer"] = "memory-tx", ["origin_device"] = "test-device", ["privacy_level"] = 1, ["evidence_refs"] = new JsonArray(),
        ["causal_context_refs"] = new JsonArray("tr_1"), ["risk_score"] = 0, ["idempotency_key"] = "idem_1", ["replay_mode"] = "live",
        ["risk_level"] = "low",
    };

    private static JsonObject Event(string topic, JsonObject payload)
    {
        var e = Envelope();
        e["topic"] = topic;
        e["payload"] = payload;
        return e;
    }

    private static JsonObject Committed() => new()
    {
        ["tx_id"] = "tx", ["trace_id"] = "tr_1", ["committed_count"] = 1, ["rejected_count"] = 0, ["throttled_count"] = 0,
    };

    [Fact]
    public void Envelope_has_exactly_13_required_and_3_optional_fields()
    {
        Assert.Equal(16, AijadeEvents.EnvelopeFields.Count);
        Assert.Equal(Required.Order(), AijadeEvents.EnvelopeFields.Where(f => !f.Value.IsOptional).Select(f => f.Key).Order());
        Assert.Empty(AijadeEvents.Envelope.Validate(Envelope()));
    }

    [Fact]
    public void Each_required_envelope_field_is_really_required()
    {
        foreach (var name in Required)
        {
            var e = Envelope();
            e.Remove(name);
            Assert.NotEmpty(AijadeEvents.Envelope.Validate(e));
        }
        var withOptional = Envelope();
        withOptional["tick"] = 3;
        withOptional["causality"] = new JsonObject { ["inputHash"] = "h" };
        withOptional["core_state_node"] = "S8";
        Assert.Empty(AijadeEvents.Envelope.Validate(withOptional));
    }

    [Theory]
    [InlineData("origin_device", "")]
    [InlineData("risk_score", 1.5)]
    [InlineData("privacy_level", 4)]
    [InlineData("risk_level", "extreme")]
    [InlineData("replay_mode", "rewind")]
    [InlineData("timestamp", -1)]
    [InlineData("timestamp", 1.5)]
    public void Envelope_values_are_checked_not_just_present(string field, object value)
    {
        var e = Envelope();
        e[field] = JsonValue.Create(value);
        Assert.NotEmpty(AijadeEvents.Envelope.Validate(e));
    }

    [Fact]
    public void Envelope_and_events_are_strict_objects()
    {
        var e = Envelope();
        e["extra"] = 1;
        Assert.NotEmpty(AijadeEvents.Envelope.Validate(e));
        var evt = Event(AijadeEvents.MemoryTxCommitted, Committed());
        Assert.True(AijadeEvents.IsValid(evt));
        evt["extra"] = 1;
        Assert.False(AijadeEvents.IsValid(evt));
        var tick = Event(AijadeEvents.MemoryTxCommitted, Committed());
        tick["tick"] = 2_147_483_648;
        Assert.False(AijadeEvents.IsValid(tick));
    }

    [Fact]
    public void Unknown_topics_and_malformed_payloads_are_rejected()
    {
        Assert.False(AijadeEvents.IsValid(Event("aijade.unknown", new JsonObject())));
        var payload = Committed();
        payload.Remove("tx_id");
        Assert.False(AijadeEvents.IsValid(Event(AijadeEvents.MemoryTxCommitted, payload)));
        Assert.Equal(12, AijadeEvents.Topics.Count);
    }

    private static JsonObject LearningRequest() => new()
    {
        ["session_id"] = "s", ["trace_id"] = "t", ["requested_at"] = 1, ["quest_ref"] = "q1",
        ["resource_budget"] = new JsonObject { ["allocated"] = 10, ["spent"] = 2, ["unit"] = "queries" },
        ["stop_conditions"] = new JsonArray("info gain < 0.05"),
    };

    [Fact]
    public void Learning_requests_must_be_bounded_before_they_start()
    {
        Assert.True(AijadeEvents.IsValid(Event(AijadeEvents.ActiveLearningRequested, LearningRequest())));
        var noStop = LearningRequest();
        noStop["stop_conditions"] = new JsonArray();
        Assert.False(AijadeEvents.IsValid(Event(AijadeEvents.ActiveLearningRequested, noStop)));
        var noBudget = LearningRequest();
        noBudget.Remove("resource_budget");
        Assert.False(AijadeEvents.IsValid(Event(AijadeEvents.ActiveLearningRequested, noBudget)));
        var overspent = LearningRequest();
        overspent["resource_budget"] = new JsonObject { ["allocated"] = 1, ["spent"] = 2, ["unit"] = "queries" };
        Assert.False(AijadeEvents.IsValid(Event(AijadeEvents.ActiveLearningRequested, overspent)));
        var noQuest = LearningRequest();
        noQuest.Remove("quest_ref");
        Assert.False(AijadeEvents.IsValid(Event(AijadeEvents.ActiveLearningRequested, noQuest)));
    }

    [Fact]
    public void Render_request_and_receipt_are_pairable_and_honest()
    {
        var req = new JsonObject { ["session_id"] = "s", ["persona_snapshot_ref"] = "p@3", ["intent_ref"] = "i1" };
        Assert.True(AijadeEvents.IsValid(Event(AijadeEvents.PersonaRenderRequested, req)));
        Assert.False(AijadeEvents.IsValid(Event(AijadeEvents.PersonaRenderRequested, new JsonObject { ["session_id"] = "s", ["persona_ref"] = "p", ["intent_ref"] = "i" })));
        var ack = new JsonObject { ["session_id"] = "s", ["render_ref"] = "i1", ["applied_params_hash"] = "mouth=0.400" };
        Assert.True(AijadeEvents.IsValid(Event(AijadeEvents.LpmRenderReady, ack)));
        var empty = (JsonObject)ack.DeepClone();
        empty["applied_params_hash"] = "";
        Assert.False(AijadeEvents.IsValid(Event(AijadeEvents.LpmRenderReady, empty)));
        var blankAsset = (JsonObject)ack.DeepClone();
        blankAsset["asset_version_hash"] = "";
        Assert.False(AijadeEvents.IsValid(Event(AijadeEvents.LpmRenderReady, blankAsset)));
    }

    [Fact]
    public void Video_and_learning_events_need_tick_and_causality()
    {
        var payload = new JsonObject
        {
            ["session_id"] = "install-1", ["source_url"] = "https://x", ["content_hash"] = "h",
            ["spans"] = new JsonArray(new JsonObject { ["start_offset"] = 0, ["end_offset"] = 5 }), ["observation_text"] = "hello",
        };
        Assert.Throws<EventValidationException>(() => AijadeEvents.Build(AijadeEvents.WebpageTextObservation, Envelope(), payload));
        var env = Envelope();
        env["tick"] = 7;
        env["causality"] = new JsonObject { ["inputHash"] = "abc" };
        var evt = AijadeEvents.Build(AijadeEvents.WebpageTextObservation, env, payload);
        Assert.Equal(AijadeEvents.WebpageTextObservation, evt["topic"]!.GetValue<string>());
        var noSession = (JsonObject)payload.DeepClone();
        noSession.Remove("session_id");
        Assert.Throws<EventValidationException>(() => AijadeEvents.Build(AijadeEvents.WebpageTextObservation, env, noSession));
    }
}
