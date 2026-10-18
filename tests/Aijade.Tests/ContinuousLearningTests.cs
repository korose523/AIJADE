using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Random;
using Aijade.Learning.Continuous;
using Aijade.Learning.Forge;
using Aijade.Providers.Llm;
using Aijade.Research.Telemetry;

namespace Aijade.Tests;

/// <summary>Continuous learning must equal the recorded golden data (signals, dynamics fingerprint, persona trajectory) and keep its behaviour.</summary>
public class ContinuousLearningTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "continuous-golden.json"))).RootElement;

    private static Dictionary<string, double> Map(JsonElement o) => o.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.GetDouble());

    [Fact]
    public void Signals_fingerprints_and_trajectory_match_the_original()
    {
        var texts = Golden.GetProperty("texts").EnumerateArray().Select(t => t.GetString()!).ToList();
        var signals = texts.Select(t => AffectSignal.Extract(t)).ToList();
        foreach (var (e, a) in Golden.GetProperty("signals").EnumerateArray().Zip(signals))
            Assert.Equal((e.GetProperty("valence").GetDouble(), e.GetProperty("arousal").GetDouble(), e.GetProperty("event").GetString()), (a.Valence, a.Arousal, a.Event));
        var c = Golden.GetProperty("custom");
        var custom = AffectSignal.Extract("foo bar baz qux", new SignalOptions(0.1, 2, 0.5, ["foo"], ["bar", "baz"], ["qux"]));
        Assert.Equal((c.GetProperty("valence").GetDouble(), c.GetProperty("arousal").GetDouble()), (custom.Valence, custom.Arousal));

        Assert.Equal(Golden.GetProperty("fpDefault").GetString(), PersonaDynamics.Fingerprint(PersonaDynamics.Resolve()));
        var dyn = PersonaDynamics.Resolve((JsonObject)JsonNode.Parse(Golden.GetProperty("override").GetRawText())!);
        Assert.Equal(Golden.GetProperty("fpOverride").GetString(), PersonaDynamics.Fingerprint(dyn));

        var rng = new Mulberry32(99).AsFunc();
        var state = new PersonaState(
            new Dictionary<string, double> { ["openness"] = 0.52, ["warmth"] = 0.48, ["curiosity"] = 0.5, ["patience"] = 0.51, ["formality"] = 0.49, ["playfulness"] = 0.47, ["caution"] = 0.53,
                ["confidence"] = 0.5, ["empathy"] = 0.5, ["spontaneity"] = 0.46, ["diligence"] = 0.54, ["assertiveness"] = 0.5, ["stability"] = 0.5 },
            new Dictionary<string, double> { ["dopamine"] = 0.5, ["serotonin"] = 0.5, ["cortisol"] = 0.2, ["oxytocin"] = 0.4, ["adrenaline"] = 0.2 },
            Persona.DefaultIntimacy(), 0);
        var traj = Golden.GetProperty("traj").EnumerateArray().ToArray();
        for (var i = 0; i < signals.Count; i++)
        {
            state = Persona.ApplyInteraction(state, signals[i], dyn, 0);
            state = Persona.Drift(state, (i + 1) * 45000, dyn, rng, 0);
            var t = traj[i];
            foreach (var (k, v) in Map(t.GetProperty("vector")))
                Assert.Equal(v, state.Vector[k], 12);
            foreach (var (k, v) in Map(t.GetProperty("endocrine")))
                Assert.Equal(v, state.Endocrine[k], 12);
            foreach (var (k, v) in Map(t.GetProperty("intimacy")))
                Assert.Equal(v, state.Intimacy[k], 12);
            var pad = Persona.ToPad(state);
            Assert.Equal(t.GetProperty("pad").GetProperty("pleasure").GetDouble(), pad.Pleasure, 12);
            Assert.Equal(t.GetProperty("big5").GetProperty("N").GetDouble(), Persona.ToBigFive(state.Vector).N, 12);
            Assert.Equal(t.GetProperty("force").GetProperty("social").GetDouble(), Persona.ToThreeForce(state).Social, 12);
            var mood = Persona.ToMoodProfile(state);
            Assert.Equal((t.GetProperty("mood").GetProperty("label").GetString(), t.GetProperty("mood").GetProperty("style").GetString()), (mood.Label, mood.Style));
            Assert.Equal(t.GetProperty("mood").GetProperty("voiceRate").GetDouble(), mood.VoiceRate, 12);
            Assert.Equal(t.GetProperty("ctx").GetString(), Persona.ToContext(state));
        }
    }

    private sealed class FakeChat(Func<IReadOnlyList<ChatMessage>, string> complete, Func<string, string>? json = null) : IChatClient
    {
        public List<string> Calls { get; } = [];

        public string Model => "fake";

        public Task<ChatCompletion> CompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default)
        {
            Calls.Add(messages[^1].Content);
            return Task.FromResult(new ChatCompletion("", "fake", complete(messages), "stop", null, null));
        }

        public Task<JsonNode?> JsonCompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default) =>
            Task.FromResult(ChatParsing.ParseJsonContent((json ?? (_ => "{}"))(messages[^1].Content)));
    }

    [Fact]
    public async Task Discourse_memory_compacts_overflow_into_sinks()
    {
        var chat = new FakeChat(m => "  The user likes tea.  ");
        var memory = new DiscourseMemory(chat, window: 4, maxChunks: 2);
        for (var i = 0; i < 7; i++)
            memory.Ingest(i % 2 == 0 ? ChatRole.User : ChatRole.Assistant, $"m{i}");
        await memory.PendingCompaction;
        Assert.Equal((4, 1), memory.Stats);
        Assert.Equal("user: m0\nassistant: m1\nuser: m2", chat.Calls[0]);
        Assert.Equal("[long-term sink]\nThe user likes tea.\n\n[recent discourse]\nassistant: m3\nuser: m4\nassistant: m5\nuser: m6", memory.Context());
        for (var i = 0; i < 6; i++)
            memory.Ingest(ChatRole.User, $"n{i}");
        await memory.PendingCompaction;
        await memory.CompactAsync(TestContext.Current.CancellationToken);
        Assert.Equal(2, memory.Stats.Chunks);
    }

    private sealed class RecordingMemory : IMemoryPort
    {
        public List<string> Log { get; } = [];

        public Task IngestUserAsync(string text, CancellationToken cancellationToken = default) { Log.Add($"u:{text}"); return Task.CompletedTask; }

        public Task IngestAssistantAsync(string text, CancellationToken cancellationToken = default) { Log.Add($"a:{text}"); return Task.CompletedTask; }

        public Task MaybeCompactAsync(CancellationToken cancellationToken = default) { Log.Add("compact"); return Task.CompletedTask; }
    }

    [Fact]
    public async Task Learning_loop_moves_persona_feeds_memory_and_evolves_skills()
    {
        var ct = TestContext.Current.CancellationToken;
        var skill = Skills.Define("tea-brewing", "Brews tea at the right temperature.", new SkillBody("Tea", ["user wants tea"], ["boil water", "steep"]), now: 1);
        var evolvedJson = SkillSchema.ToJson(skill.Frontmatter, skill.Body with { Procedure = ["boil water", "cool to 80C", "steep"] }).ToJsonString();
        var chat = new FakeChat(_ => "sink", _ => evolvedJson);
        var forge = new SkillForge(chat);
        forge.Register(skill);
        var memory = new RecordingMemory();
        var events = new List<PersonaUpdateEvent>();
        double clock = 1000;
        var learning = new ContinuousLearning(chat, memory, forge, onPersonaUpdate: events.Add, now: () => clock, jitter: () => 0.5);
        var before = learning.Persona.Endocrine["dopamine"];
        await learning.IngestTurnAsync(ChatRole.User, "I love this, thank you!!", ct: ct);
        await learning.IngestTurnAsync(ChatRole.Assistant, "glad to help", new InteractionSignal(0.2, 0.3), ct);
        Assert.True(learning.Persona.Endocrine["dopamine"] > before);
        Assert.Equal(["u:I love this, thank you!!", "a:glad to help"], memory.Log);
        Assert.Equal([PersonaUpdateCause.Interaction, PersonaUpdateCause.Interaction], events.Select(e => e.Cause));
        clock = 61_000;
        Assert.Equal(60_000, learning.IdleMs);
        learning.Tick(60_000);
        Assert.Equal(PersonaUpdateCause.Drift, events[^1].Cause);
        Assert.StartsWith("Persona[", learning.ContextSupplement(), StringComparison.Ordinal);
        Assert.Contains("[recent discourse]\nuser: I love this, thank you!!", learning.ContextSupplement(), StringComparison.Ordinal);

        var evolved = await learning.CaptureFeedbackAsync("the tea-brewing skill should cool the water first", ct: ct);
        Assert.Equal("0.1.1", evolved!.Frontmatter.Version);
        Assert.Equal(3, forge.Registry.Find("tea-brewing")!.Body.Procedure.Count);
        Assert.Null(await learning.CaptureFeedbackAsync("unrelated words here", ct: ct));
        await learning.CompactAsync(ct);
        Assert.Equal("compact", memory.Log[^1]);

        var silent = new ContinuousLearning(chat, disableSignalExtraction: true, jitter: () => 0.5);
        var p = silent.Persona;
        await silent.IngestTurnAsync(ChatRole.User, "I love this!", ct: ct);
        Assert.Same(p, silent.Persona);
    }

    [Fact]
    public async Task Llm_signal_falls_back_to_the_lexicon()
    {
        var ct = TestContext.Current.CancellationToken;
        var good = await AffectSignal.ExtractWithLlmAsync(new FakeChat(_ => "", _ => """{"valence":-3,"arousal":0.4}"""), "whatever", ChatRole.User, ct: ct);
        Assert.Equal((-1.0, 0.4, "negative"), (good.Valence, good.Arousal, good.Event));
        var fallback = await AffectSignal.ExtractWithLlmAsync(new FakeChat(_ => "", _ => """{"valence":"high"}"""), "I love it", ChatRole.User, ct: ct);
        Assert.Equal(AffectSignal.Extract("I love it"), fallback);
        Assert.Equal("empty", (await AffectSignal.ExtractWithLlmAsync(new FakeChat(_ => ""), " ", ChatRole.User, ct: ct)).Event);
    }

    [Fact]
    public async Task Telemetry_records_only_with_consent_and_purges_on_withdrawal()
    {
        var consent = true;
        var storage = new MemoryTelemetryStorage();
        using var recorder = new PersonaTelemetryRecorder(() => consent, storage, sessionId: "s1", now: () => 1);
        var state = Persona.Create(jitter: () => 0.5, now: 0);
        await recorder.RecordAsync(new PersonaUpdateEvent(state, PersonaUpdateCause.Interaction, 0, ChatRole.User));
        await recorder.RecordAsync(new PersonaUpdateEvent(state, PersonaUpdateCause.Drift, 0));
        Assert.Equal(2, recorder.TurnsRecorded);
        var turns = await storage.ReadTurnsAsync("s1", TestContext.Current.CancellationToken);
        Assert.Equal(PersonaSnapshots.From(state), turns[0].Persona);
        consent = false;
        await recorder.RecordAsync(new PersonaUpdateEvent(state, PersonaUpdateCause.Drift, 0));
        Assert.Empty(await storage.ReadTurnsAsync("s1", TestContext.Current.CancellationToken));
        Assert.False(recorder.Recording);

        using var noStorage = new PersonaTelemetryRecorder(() => true);
        await noStorage.RecordAsync(new PersonaUpdateEvent(state, PersonaUpdateCause.Drift, 0));
        Assert.Contains("no durable storage", noStorage.LastError, StringComparison.Ordinal);
    }
}
