using System.Net;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Agent;
using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Client.I18n;
using Aijade.Client.Settings;
using Aijade.Learning.Continuous;
using Aijade.Memory.Development;
using Aijade.Providers.Llm;
using Aijade.Server.Product;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

public class ClientTests
{
    [Fact]
    public void Without_a_character_the_default_companion_is_aijade_9()
    {
        var prompt = ChatOrchestrator.SystemPrompt(null, ["extra context"]);
        Assert.StartsWith("You are 艾娅德 (Aijade-9)", prompt, StringComparison.Ordinal);
        Assert.Contains("extra context", prompt, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Sse_parser_yields_text_and_usage_and_stops_at_done()
    {
        const string sse = "data: {\"choices\":[{\"delta\":{\"content\":\"He\"}}]}\n\n: comment\n\ndata: {\"choices\":[{\"delta\":{\"content\":\"y\"}}]}\n\n" +
                           "data: {\"choices\":[],\"usage\":{\"prompt_tokens\":3,\"completion_tokens\":2}}\n\ndata: [DONE]\n\ndata: {\"choices\":[{\"delta\":{\"content\":\"late\"}}]}\n\n";
        var deltas = new List<CompletionDelta>();
        await foreach (var d in Sse.ParseCompletionAsync(new MemoryStream(Encoding.UTF8.GetBytes(sse)), TestContext.Current.CancellationToken))
            deltas.Add(d);
        Assert.Equal("Hey", string.Concat(deltas.Select(d => d.Text)));
        Assert.Equal((3, 2), (deltas[^1].PromptTokens, deltas[^1].CompletionTokens));
    }

    [Fact]
    public void Expression_markers_are_lifted_out_even_when_split_across_chunks()
    {
        var p = new ExpressionMarkerParser();
        var outText = new StringBuilder();
        var markers = new List<string>();
        foreach (var chunk in new[] { "Hello [", "[emo", "te:Joy]", "] there [[not a marker]] ok [[emote:sad", "]]!", " [" })
        {
            var (t, m) = p.Feed(chunk);
            outText.Append(t);
            markers.AddRange(m);
        }
        outText.Append(p.Flush());
        Assert.Equal("Hello  there [[not a marker]] ok ! [", outText.ToString());
        Assert.Equal(["joy", "sad"], markers);
    }

    [Fact]
    public void Draw_markers_keep_their_case_and_only_listed_kinds_are_lifted()
    {
        var p = new MarkerParser("emote", "draw");
        var text = new StringBuilder();
        var markers = new List<Marker>();
        foreach (var chunk in new[] { "Here [[dr", "aw: A Cat on a windowsill]] and [[emote:JOY]] [[note:keep]]", " [[d" })
        {
            var (t, m) = p.Feed(chunk);
            text.Append(t);
            markers.AddRange(m);
        }
        text.Append(p.Flush());
        Assert.Equal("Here  and  [[note:keep]] [[d", text.ToString());
        Assert.Equal([new Marker("draw", "A Cat on a windowsill"), new Marker("emote", "joy")], markers);
        Assert.DoesNotContain("[[draw:", ChatOrchestrator.SystemPrompt(null, []), StringComparison.Ordinal);
        Assert.Contains("[[draw:", ChatOrchestrator.SystemPrompt(null, [], drawing: true), StringComparison.Ordinal);
    }

    [Fact]
    public void Dialogue_acts_and_expressions_drive_the_performance_intent()
    {
        Assert.Equal(DialogueAct.Question, Expressions.InferAct("How are you?"));
        Assert.Equal(DialogueAct.Celebrate, Expressions.InferAct("We did it!"));
        Assert.Equal(DialogueAct.Apologise, Expressions.InferAct("对不起，我记错了。"));
        Assert.Equal(DialogueAct.Inform, Expressions.InferAct("The sky is blue."));
        var happy = Pef.MapPersonaToExpression(Expressions.Persona("Great.", ["joy"]));
        var sad = Pef.MapPersonaToExpression(Expressions.Persona("Great.", ["sad"]));
        Assert.True(happy.Valence > sad.Valence);
        Assert.Contains("joy", Expressions.Instruction, StringComparison.Ordinal);
    }

    [Fact]
    public void Every_locale_has_every_key_and_resolution_falls_back_sensibly()
    {
        var keys = Strings.Keys("en");
        Assert.True(keys.Count > 80);
        foreach (var (code, _) in Strings.Locales)
            Assert.Empty(keys.Except(Strings.Keys(code)));
        Assert.Equal(9, Strings.Locales.Count);
        Assert.Equal("zh-Hant", Strings.Resolve("zh-TW"));
        Assert.Equal("zh-Hans", Strings.Resolve("zh-CN"));
        Assert.Equal("ja", Strings.Resolve("ja-JP"));
        Assert.Equal("en", Strings.Resolve("de-DE"));
        var s = new Strings();
        s.SetLocale("ko");
        Assert.Equal("설정", s["nav.settings"]);
        Assert.Equal("missing.key", s["missing.key"]);
        Assert.Equal("Sign-in failed: x", new Strings().Format("auth.failed", "x"));
    }

    [Fact]
    public async Task Settings_round_trip_survive_corruption_and_import_only_aijade_exports()
    {
        var store = new InMemoryKeyValueStore();
        var settings = new SettingsService(store);
        Assert.Equal("en", (await settings.LoadAsync()).Locale);
        var changed = 0;
        settings.Changed += _ => changed++;
        await settings.UpdateAsync(s => s with { Locale = "fr", Voice = s.Voice with { VadEnabled = false } });
        Assert.Equal("fr", (await new SettingsService(store).LoadAsync()).Locale);
        Assert.False((await new SettingsService(store).LoadAsync()).Voice.VadEnabled);
        var export = settings.Export();
        await store.SetAsync(AppSettings.StorageKey, "{ not json");
        Assert.Equal("en", (await new SettingsService(store).LoadAsync()).Locale);
        await settings.ImportAsync(export);
        Assert.Equal("fr", settings.Current.Locale);
        await Assert.ThrowsAsync<FormatException>(() => settings.ImportAsync(new JsonObject { ["format"] = "other" }));
        await settings.ResetAsync();
        Assert.Equal("en", settings.Current.Locale);
        Assert.Equal(3, changed);
    }

    [Fact]
    public async Task Stage_scenes_are_saved_with_the_settings_and_restore_the_arrangement()
    {
        var store = new InMemoryKeyValueStore();
        var settings = new SettingsService(store);
        await settings.LoadAsync();
        var night = new StageSettings { Background = "#000010", BackgroundImage = "data:image/jpeg;base64,AAAA", BackgroundFit = "contain", Scale = 1.4 };
        await settings.UpdateAsync(s => s with { Stage = s.Stage with { Scenes = [StageScene.From("Night", night)] } });

        var loaded = await new SettingsService(store).LoadAsync();
        var scene = Assert.Single(loaded.Stage.Scenes);
        Assert.Equal("Night", scene.Name);
        var applied = scene.ApplyTo(loaded.Stage);
        Assert.Equal(("#000010", "data:image/jpeg;base64,AAAA", "contain", 1.4), (applied.Background, applied.BackgroundImage, applied.BackgroundFit, applied.Scale));
        Assert.Equal(loaded.Stage.ModelUrl, applied.ModelUrl); // a scene dresses the stage; it does not change the model
    }

    private sealed class FakeLlm : HttpMessageHandler
    {
        public string? LastBody { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            LastBody = await request.Content!.ReadAsStringAsync(cancellationToken);
            const string sse = "data: {\"choices\":[{\"delta\":{\"content\":\"[[emote:jo\"}}]}\n\n" +
                               "data: {\"choices\":[{\"delta\":{\"content\":\"y]]Nice to meet you!\"}}]}\n\n" +
                               "data: {\"choices\":[],\"usage\":{\"prompt_tokens\":10,\"completion_tokens\":5}}\n\ndata: [DONE]\n\n";
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(sse, Encoding.UTF8, "text/event-stream") };
        }
    }

    private sealed class StaticContext(string text) : IContextProvider
    {
        public Task<string?> SupplyAsync(TurnContext turn, CancellationToken ct) => Task.FromResult<string?>(text);
    }

    private sealed class RecordingObserver : ITurnObserver
    {
        public List<string> Calls { get; } = [];

        public Task UserTurnAsync(TurnContext turn, CancellationToken ct)
        {
            Calls.Add($"user:{turn.UserText}");
            return Task.CompletedTask;
        }

        public Task AssistantTurnAsync(TurnContext turn, string reply, CancellationToken ct)
        {
            Calls.Add($"assistant:{reply}");
            return Task.CompletedTask;
        }
    }

    private sealed class ThrowingObserver : ITurnObserver
    {
        public Task UserTurnAsync(TurnContext turn, CancellationToken ct) => throw new InvalidOperationException("observer down");

        public Task AssistantTurnAsync(TurnContext turn, string reply, CancellationToken ct) => throw new InvalidOperationException("observer down");
    }

    /// <summary>Answers JSON prompts from a script, in order; an exhausted script throws like an unreachable model.</summary>
    private sealed class ScriptedLlm(params string[] replies) : IChatClient
    {
        private int i;

        public List<string> Prompts { get; } = [];

        public string Model => "scripted";

        public Task<ChatCompletion> CompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default)
        {
            Prompts.Add(messages[^1].Content);
            return i < replies.Length
                ? Task.FromResult(new ChatCompletion("c", Model, replies[i++], "stop", null, null))
                : throw new LlmRequestException("model unreachable");
        }

        public async Task<JsonNode?> JsonCompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default) =>
            ChatParsing.ParseJsonContent((await CompleteAsync(messages, options, cancellationToken)).Text);
    }

    private static string GoldenSkill() =>
        System.Text.Json.JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "skill-forge-golden.json"))).RootElement.GetProperty("cases")[0].GetRawText();

    [Fact]
    public async Task Agent_capabilities_learn_from_turns_supply_context_and_forge_skills_in_the_background()
    {
        var ct = TestContext.Current.CancellationToken;
        var time = new ManualTime(1_000_000);
        var llm = new ScriptedLlm(
            """{"shouldCreate":true,"rationale":"repeatable","draft":{"proposedName":"git-rebase-recipe","title":"Git Rebase","summary":"Rebases.","whenToUse":["behind main"]}}""",
            GoldenSkill(),
            """{"ok":true,"warnings":[],"score":0.9}""");
        var updates = new List<PersonaUpdateEvent>();
        var enabled = true;
        var bridge = new AgentCapabilities(llm, new AgentCapabilitiesOptions { Enabled = () => enabled, OnPersonaUpdate = updates.Add, Time = time });
        var turn = new TurnContext("chat-1", null, [], "Thank you so much, that was wonderful!");

        await bridge.UserTurnAsync(turn, ct);
        Assert.Contains(updates, u => u.Cause == PersonaUpdateCause.Interaction && u.Role == ChatRole.User);
        time.Advance(TimeSpan.FromMinutes(5));
        await bridge.AssistantTurnAsync(turn, "To rebase: git fetch, then git rebase origin/main.", ct);
        Assert.Contains(updates, u => u.Cause == PersonaUpdateCause.Drift);
        await bridge.Background.WaitAsync(ct);
        Assert.Null(bridge.LastBackgroundError);

        // The exchange was judged teachable, so a skill now exists and is announced to the model with the persona context.
        var skill = Assert.Single(bridge.SkillForge.Registry.List());
        var supplement = await bridge.SupplyAsync(turn, ct);
        Assert.Contains("warmth:", supplement, StringComparison.Ordinal);
        Assert.Contains($"- {skill.Frontmatter.Name}: {skill.Frontmatter.Description}", supplement, StringComparison.Ordinal);
        Assert.Contains("user: Thank you so much", llm.Prompts[0], StringComparison.Ordinal);

        // A model failure in the background is recorded, never thrown into the turn.
        await bridge.AssistantTurnAsync(turn, "Another reply.", ct);
        await bridge.Background.WaitAsync(ct);
        Assert.Equal("model unreachable", bridge.LastBackgroundError);

        // Switched off (the Learning module), it neither learns nor adds context.
        enabled = false;
        var before = updates.Count;
        await bridge.UserTurnAsync(turn, ct);
        Assert.Equal(before, updates.Count);
        Assert.Null(await bridge.SupplyAsync(turn, ct));
    }

    [Fact]
    public async Task Orchestrator_streams_stores_and_reports_a_verifiable_render_through_the_real_server()
    {
        var ct = TestContext.Current.CancellationToken;
        var llm = new FakeLlm();
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => llm));
        await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject
        {
            ["models"] = new JsonObject { ["aijade-chat"] = new JsonObject { ["upstream"] = "https://llm.example/v1", ["model"] = "m", ["keys"] = new JsonArray("k"), ["fluxPer1k"] = 0 } },
        }, ServerTestHost.AdminToken);

        var tokens = new MemoryTokenStore();
        await tokens.SetAsync(ServerTestHost.Token);
        var api = new AijadeApi(host.Client, tokens);
        var character = await api.CreateCharacterAsync(new { name = "艾娅德", persona = "A gentle, careful companion in a maid outfit." }, ct);
        var chat = await api.CreateChatAsync(character.Id, "hello", ct);
        var seen = new RecordingObserver();
        var orchestrator = new ChatOrchestrator(api, [new StaticContext("The user likes tea.")], new OrchestratorOptions(), observers: [new ThrowingObserver(), seen]);
        var observerFailures = 0;
        orchestrator.ObserverFailed += (_, _) => observerFailures++;

        var events = new List<OrchestratorEvent>();
        await foreach (var e in orchestrator.SendAsync(chat.Id, character, [], "Hi!", "snap-1", ct))
            events.Add(e);
        Assert.DoesNotContain(events, e => e is TurnFailed);
        Assert.Equal("Nice to meet you!", string.Concat(events.OfType<TextDelta>().Select(d => d.Text)));
        Assert.Equal(["joy"], events.OfType<ExpressionCue>().Select(c => c.Name));
        var done = Assert.IsType<TurnCompleted>(events[^1]);
        Assert.Equal("snap-1", done.Intent.PersonaSnapshotRef);
        Assert.Contains("You are 艾娅德.", JsonNode.Parse(llm.LastBody!)!["messages"]![0]!["content"]!.GetValue<string>(), StringComparison.Ordinal);
        Assert.Contains("The user likes tea.", llm.LastBody!, StringComparison.Ordinal);
        Assert.Equal(["Hi!", "Nice to meet you!"], (await api.MessagesAsync(chat.Id, ct: ct)).Select(m => m.Content));
        // Observers saw both sides; the throwing one was skipped twice without touching the turn.
        Assert.Equal(["user:Hi!", "assistant:Nice to meet you!"], seen.Calls);
        Assert.Equal(2, observerFailures);

        var reporter = new RenderReporter(api, "stage-session", "test-browser");
        var applied = new JsonObject { ["expression.happy"] = 0.8, ["motion"] = "wave" };
        var renderRef = await reporter.ReportAsync(done.Intent, applied, "asset-v1", ct);
        Assert.Equal("paired", await host.ScalarAsync("SELECT projection_status FROM render_traces WHERE render_ref = $1", renderRef));
        Assert.Equal(RenderReporter.AppliedParamsHash(applied), await host.ScalarAsync("SELECT applied_params_hash FROM render_traces WHERE render_ref = $1", renderRef));
        Assert.Equal(done.Intent.Id, await host.ScalarAsync("SELECT intent_ref FROM render_traces WHERE render_ref = $1", renderRef));
        await Assert.ThrowsAsync<ArgumentException>(() => reporter.ReportAsync(done.Intent, [], null, ct));

        await tokens.SetAsync("bogus");
        Assert.Null(await api.SessionAsync(ct));
        var failed = new List<OrchestratorEvent>();
        await foreach (var e in orchestrator.SendAsync(chat.Id, character, [], "Hi again", "snap-1", ct))
            failed.Add(e);
        Assert.Equal("UNAUTHORIZED", Assert.IsType<TurnFailed>(Assert.Single(failed)).Code);
    }

    private sealed class DrawingLlm : HttpMessageHandler
    {
        public string? LastChatBody { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var body = await request.Content!.ReadAsStringAsync(cancellationToken);
            if (request.RequestUri!.AbsolutePath.EndsWith("/images/generations", StringComparison.Ordinal))
            {
                var png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
                return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent($$"""{"data":[{"b64_json":"{{png}}"}]}""", Encoding.UTF8, "application/json") };
            }
            LastChatBody = body;
            const string sse = "data: {\"choices\":[{\"delta\":{\"content\":\"Here you go! [[draw: a calico cat\"}}]}\n\n" +
                               "data: {\"choices\":[{\"delta\":{\"content\":\" asleep on a windowsill]] [[draw: a second one]]\"}}]}\n\ndata: [DONE]\n\n";
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(sse, Encoding.UTF8, "text/event-stream") };
        }
    }

    [Fact]
    public async Task A_draw_marker_becomes_one_picture_in_the_chat_only_when_drawing_is_enabled()
    {
        var ct = TestContext.Current.CancellationToken;
        var llm = new DrawingLlm();
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => llm));
        await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject
        {
            ["models"] = new JsonObject { ["aijade-chat"] = new JsonObject { ["upstream"] = "https://llm.example/v1", ["model"] = "m", ["keys"] = new JsonArray("k") } },
            ["images"] = new JsonObject { ["kind"] = "openai", ["upstream"] = "https://llm.example/v1", ["model"] = "img", ["keys"] = new JsonArray("k") },
        }, ServerTestHost.AdminToken);
        var tokens = new MemoryTokenStore();
        await tokens.SetAsync(ServerTestHost.Token);
        var api = new AijadeApi(host.Client, tokens);
        Assert.True((await api.CapabilitiesAsync(ct)).Images);
        var chat = await api.CreateChatAsync(null, "draw", ct);

        async Task<List<OrchestratorEvent>> Turn(bool drawing, string text)
        {
            var o = new ChatOrchestrator(api, [], new OrchestratorOptions { Drawing = () => drawing });
            var events = new List<OrchestratorEvent>();
            await foreach (var e in o.SendAsync(chat.Id, null, await api.MessagesAsync(chat.Id, ct: ct), text, "snap", ct))
                events.Add(e);
            return events;
        }

        // Off: the model is not told, and a stray marker is hidden but ignored.
        var off = await Turn(false, "Show me a cat");
        Assert.Empty(off.OfType<DrawRequest>());
        Assert.Equal("Here you go!", Assert.IsType<TurnCompleted>(off[^1]).Reply.Content);
        Assert.DoesNotContain("[[draw:", llm.LastChatBody!, StringComparison.Ordinal);

        // On: one picture per reply, drawn by the server and added to the chat as an image message.
        var on = await Turn(true, "Show me a cat");
        Assert.Contains("[[draw:", llm.LastChatBody!, StringComparison.Ordinal);
        var request = Assert.Single(on.OfType<DrawRequest>());
        Assert.Equal("a calico cat asleep on a windowsill", request.Prompt);
        var picture = await Artistry.DrawIntoChatAsync(api, chat.Id, request.Prompt, ct);
        var image = Artistry.ImageOf(picture)!;
        Assert.Equal("image/png", image.Mime);
        Assert.Equal("image/png", (await api.ImageBytesAsync(image.Id, ct)).Mime);

        // Later turns tell the model it drew the picture rather than replaying the prompt as its own words.
        await Turn(true, "Nice!");
        Assert.Contains("[I drew a picture: a calico cat asleep on a windowsill]", llm.LastChatBody!, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Vision_context_keeps_the_live_view_while_fresh_and_an_attachment_for_one_turn()
    {
        var ct = TestContext.Current.CancellationToken;
        var time = new ManualTime(1_000_000);
        var enabled = true;
        var vision = new VisionContext(() => enabled, time);
        var turn = new TurnContext("c", null, [], "what do you see?");
        Assert.Null(await vision.SupplyAsync(turn, ct));

        vision.Observe(VisionSource.Screen, "A code editor with a failing test.");
        vision.Observe(VisionSource.Attachment, "A photo of a cat.");
        time.Advance(TimeSpan.FromSeconds(12));
        var first = await vision.SupplyAsync(turn, ct);
        Assert.Contains("The user attached an image to this message. It shows: A photo of a cat.", first, StringComparison.Ordinal);
        Assert.Contains("What you can see on the user's screen (12 s ago): A code editor with a failing test.", first, StringComparison.Ordinal);
        // The attachment belonged to that turn only; the live view stays until it goes stale.
        Assert.DoesNotContain("attached", await vision.SupplyAsync(turn, ct), StringComparison.Ordinal);
        time.Advance(VisionContext.Freshness);
        Assert.Null(await vision.SupplyAsync(turn, ct));

        vision.Observe(VisionSource.Camera, "Someone smiling at a desk.");
        enabled = false;
        Assert.Null(await vision.SupplyAsync(turn, ct));
        enabled = true;
        Assert.Contains("user's camera", await vision.SupplyAsync(turn, ct), StringComparison.Ordinal);
        vision.ClearLive();
        Assert.Null(await vision.SupplyAsync(turn, ct));
    }

    private sealed class VisionLlm : HttpMessageHandler
    {
        public string? LastBody { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            LastBody = await request.Content!.ReadAsStringAsync(cancellationToken);
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("""{"id":"v","model":"vlm","choices":[{"message":{"role":"assistant","content":"  A cat asleep on a windowsill.  "}}]}""", Encoding.UTF8, "application/json"),
            };
        }
    }

    [Fact]
    public async Task Vision_interpreter_sends_the_frame_as_multimodal_content_through_the_gateway()
    {
        var ct = TestContext.Current.CancellationToken;
        var llm = new VisionLlm();
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => llm));
        await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject
        {
            ["models"] = new JsonObject { ["aijade-vision"] = new JsonObject { ["upstream"] = "https://vlm.example/v1", ["model"] = "vlm", ["keys"] = new JsonArray("k") } },
        }, ServerTestHost.AdminToken);
        var tokens = new MemoryTokenStore();
        await tokens.SetAsync(ServerTestHost.Token);
        var interpreter = new VisionInterpreter(new AijadeApi(host.Client, tokens), () => "aijade-vision");

        const string frame = "data:image/jpeg;base64,/9j/4AAQSkZJRg==";
        Assert.Equal("A cat asleep on a windowsill.", await interpreter.DescribeAsync(frame, VisionSource.Screen, ct));
        var sent = JsonNode.Parse(llm.LastBody!)!;
        Assert.Equal("vlm", sent["model"]!.GetValue<string>());
        var content = sent["messages"]![0]!["content"]!.AsArray();
        Assert.Equal(VisionInterpreter.Instruction(VisionSource.Screen), content[0]!["text"]!.GetValue<string>());
        Assert.Equal(frame, content[1]!["image_url"]!["url"]!.GetValue<string>());
        Assert.Equal(VisionInterpreter.MaxTokens, sent["max_tokens"]!.GetValue<int>());
        await Assert.ThrowsAsync<ArgumentException>(() => interpreter.DescribeAsync("https://example.com/x.png", VisionSource.Attachment, ct));
    }

    /// <summary>Low-band energy of a 4/4 track: a kick every beat (decaying over ~120 ms) on a noisy bass bed.</summary>
    private static IEnumerable<(double At, double Energy)> Track(double bpm, double seconds, int seed, double kick = 200, double frameMs = 1000.0 / 60)
    {
        var random = new Random(seed);
        var period = 60000 / bpm;
        for (var t = 0.0; t < seconds * 1000; t += frameMs)
        {
            var sinceKick = t % period;
            var energy = 60 + (random.NextDouble() * 20) + (kick * Math.Exp(-sinceKick / 40));
            yield return (t, energy);
        }
    }

    [Theory]
    [InlineData(90)]
    [InlineData(120)]
    [InlineData(150)]
    public void Beat_detector_finds_each_kick_and_the_tempo(double bpm)
    {
        var detector = new BeatDetector();
        var beats = Track(bpm, 20, seed: (int)bpm).Select(f => detector.Feed(f.At, f.Energy)).OfType<Beat>().ToList();
        var expected = 20 * bpm / 60;
        Assert.InRange(beats.Count, expected - 3, expected + 1);
        Assert.InRange(detector.Bpm!.Value, bpm * 0.97, bpm * 1.03);
        Assert.True(detector.Confidence > 0.9, $"confidence {detector.Confidence}");
        Assert.All(beats, b => Assert.InRange(b.Strength, 0, 1));
        // Beats land on the kicks (within two frames).
        var period = 60000 / bpm;
        Assert.All(beats, b => Assert.True(b.AtMs % period < 40, $"beat at {b.AtMs}"));
    }

    [Fact]
    public void Beat_detector_stays_quiet_on_silence_and_steady_noise_and_respects_the_refractory_time()
    {
        var detector = new BeatDetector();
        var random = new Random(7);
        for (var t = 0.0; t < 10_000; t += 1000.0 / 60)
            Assert.Null(detector.Feed(t, 10 + (random.NextDouble() * 10))); // below MinEnergy
        Assert.Equal(0, detector.BeatCount);

        // 480 BPM "kicks" are faster than the 250 ms refractory time allows: at most every other one counts.
        var fast = new BeatDetector();
        var count = Track(480, 10, seed: 3).Count(f => fast.Feed(f.At, f.Energy) is not null);
        Assert.InRange(count, 30, 41);
        Assert.InRange(fast.Bpm!.Value, 60, 200);
        fast.Reset();
        Assert.Equal((0, (double?)null), (fast.BeatCount, fast.Bpm));
    }

    [Fact]
    public async Task Live_context_from_the_browser_extension_reaches_the_companion_only_when_fresh_and_enabled()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var page = new JsonObject { ["site"] = "YouTube", ["kind"] = "video", ["title"] = "How bees build combs", ["url"] = "https://www.youtube.com/watch?v=x", ["text"] = "The wax is warm.", ["position"] = "3:07" };
        Assert.Equal(400, (await host.SendAsync(HttpMethod.Put, "/api/v1/context/clipboard", page)).Status);
        Assert.Equal(204, (await host.SendAsync(HttpMethod.Put, "/api/v1/context/browser", page)).Status);
        Assert.Equal(204, (await host.SendAsync(HttpMethod.Get, "/api/v1/context/browser", token: ServerTestHost.AdminToken)).Status); // per account

        var tokens = new MemoryTokenStore();
        await tokens.SetAsync(ServerTestHost.Token);
        var api = new AijadeApi(host.Client, tokens);
        var turn = new TurnContext("c", null, [], "what do you think?");
        var enabled = true;
        var supplied = await new LiveContextProvider(api, () => enabled).SupplyAsync(turn, ct);
        Assert.Equal("The user is watching: \"How bees build combs\" on YouTube, at 3:07. Current subtitles: The wax is warm.", supplied);
        enabled = false;
        Assert.Null(await new LiveContextProvider(api, () => enabled).SupplyAsync(turn, ct));
        var later = new ManualTime(DateTimeOffset.UtcNow.Add(LiveContextProvider.Freshness).AddMinutes(1).ToUnixTimeMilliseconds());
        Assert.Null(await new LiveContextProvider(api, () => true, time: later).SupplyAsync(turn, ct)); // stale

        page["text"] = new string('x', 5000);
        await host.SendAsync(HttpMethod.Put, "/api/v1/context/browser", page);
        var (_, stored) = await host.SendAsync(HttpMethod.Get, "/api/v1/context/browser");
        Assert.Equal(LiveContextEndpoints.MaxText, stored!["context"]!["text"]!.GetValue<string>().Length);
        Assert.Equal(204, (await host.SendAsync(HttpMethod.Delete, "/api/v1/context/browser")).Status);
        Assert.Null(await new LiveContextProvider(api, () => true).SupplyAsync(turn, ct));
    }
}
