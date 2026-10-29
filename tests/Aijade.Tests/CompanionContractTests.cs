using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Client.Companion;
using Aijade.Memory.Development;

namespace Aijade.Tests;

/// <summary>
/// The companion contract shared with MOSAIC's companion (configs/companion/contract.json, docs/COMPANION-CONTRACT.md,
/// ADR-002): the product code must hold the contract's persona, expression names and initiative rule, and the initiative rule
/// must give the decisions MOSAIC's implementation gave on the vectors it generated. Non-research line only.
/// </summary>
public class CompanionContractTests
{
    private static readonly string Root = RqcReanalysisTests.RepoRoot();

    private static JsonElement Load(string name)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "configs", "companion", name)));
        return doc.RootElement.Clone();
    }

    [Fact]
    public void The_default_persona_is_the_contract_persona()
    {
        var persona = Load("contract.json").GetProperty("persona");
        Assert.Equal(ChatOrchestrator.DefaultPersona, persona.GetProperty("prompt").GetString());
        Assert.StartsWith("You are " + persona.GetProperty("names")[0].GetString(), ChatOrchestrator.DefaultPersona, StringComparison.Ordinal);
    }

    [Fact]
    public void The_expression_names_and_their_mapping_cover_the_stage_vocabulary()
    {
        var expressions = Load("contract.json").GetProperty("expressions");
        var table = expressions.GetProperty("aijade").GetProperty("table").EnumerateObject().ToList();
        Assert.Equal(Expressions.Table.Keys.Order(StringComparer.Ordinal), table.Select(p => p.Name).Order(StringComparer.Ordinal));
        foreach (var e in table)
        {
            var axes = e.Value.EnumerateObject().ToDictionary(a => a.Name, a => a.Value.GetDouble(), StringComparer.Ordinal);
            Assert.All(axes.Keys, a => Assert.NotNull(typeof(PartialExpression).GetProperty(char.ToUpperInvariant(a[0]) + a[1..])));
            foreach (var property in typeof(PartialExpression).GetProperties().Where(x => x.PropertyType == typeof(double?)))
            {
                var key = char.ToLowerInvariant(property.Name[0]) + property.Name[1..];
                Assert.Equal(axes.TryGetValue(key, out var v) ? v : null, (double?)property.GetValue(Expressions.Table[e.Name]));
            }
        }
        var mosaic = expressions.GetProperty("mosaic").GetProperty("emotions").EnumerateArray().Select(x => x.GetString()).ToHashSet();
        var toMosaic = expressions.GetProperty("aijadeToMosaic").EnumerateObject().ToList();
        Assert.Equal(Expressions.Table.Keys.Order(StringComparer.Ordinal), toMosaic.Select(p => p.Name).Order(StringComparer.Ordinal));
        Assert.All(toMosaic, p => Assert.Contains(p.Value.GetString(), mosaic));
        Assert.All(expressions.GetProperty("mosaicToAijade").EnumerateObject(), p =>
        {
            Assert.Contains(p.Name, mosaic);
            if (p.Value.ValueKind != JsonValueKind.Null)
                Assert.Contains(p.Value.GetString()!, Expressions.Table.Keys);
        });
    }

    [Fact]
    public void The_initiative_parameters_and_words_are_the_contract_values()
    {
        var c = Load("contract.json").GetProperty("initiative").GetProperty("params");
        var w = c.GetProperty("weights");
        var expected = new InitiativeParams(c.GetProperty("quiet_min_s").GetDouble(), c.GetProperty("quiet_full_s").GetDouble(),
            c.GetProperty("cooldown_s").GetDouble(), c.GetProperty("per_hour").GetInt32(), c.GetProperty("hush_s").GetDouble(),
            c.GetProperty("recent_s").GetDouble(), c.GetProperty("night")[0].GetInt32(), c.GetProperty("night")[1].GetInt32(),
            c.GetProperty("threshold").GetDouble(), new InitiativeWeights(w.GetProperty("relevance").GetDouble(),
                w.GetProperty("novelty").GetDouble(), w.GetProperty("social").GetDouble(), w.GetProperty("context").GetDouble(),
                w.GetProperty("interrupt").GetDouble(), w.GetProperty("frequency").GetDouble()));
        Assert.Equal(expected, InitiativeParams.Default);

        var vectors = Load("initiative-vectors.json");
        Assert.True(JsonNode.DeepEquals(JsonNode.Parse(c.GetRawText()), JsonNode.Parse(vectors.GetProperty("params").GetRawText())),
            "the contract's initiative parameters differ from those the vectors were generated with");
        Assert.Equal(vectors.GetProperty("leaving").EnumerateArray().Select(x => x.GetString()), Initiative.Leaving);
        Assert.Equal(vectors.GetProperty("hush").EnumerateArray().Select(x => x.GetString()), Initiative.Hush);
    }

    [Fact]
    public void The_initiative_rule_decides_as_mosaic_did_on_every_vector()
    {
        var vectors = Load("initiative-vectors.json").GetProperty("vectors").EnumerateArray().ToList();
        Assert.NotEmpty(vectors);
        foreach (var v in vectors)
        {
            var name = v.GetProperty("name").GetString();
            var turns = v.GetProperty("turns").EnumerateArray().Select(t => new InitiativeTurn(t.GetProperty("created").GetDouble(),
                t.GetProperty("input").GetString(), t.GetProperty("kind").GetString() == "proactive")).ToList();
            var got = Initiative.Decide(turns, v.GetProperty("now").GetDouble(), v.GetProperty("hour").GetInt32());
            var e = v.GetProperty("expected");
            Assert.True(e.GetProperty("speak").GetBoolean() == got.Speak, $"{name}: speak");
            Assert.True(e.GetProperty("reason").GetString() == got.Reason, $"{name}: reason {got.Reason}");
            Assert.True(e.GetProperty("followUp").ValueKind == JsonValueKind.Null ? got.FollowUp is null
                : e.GetProperty("followUp").GetString() == got.FollowUp, $"{name}: follow-up");
            if (e.GetProperty("score").ValueKind == JsonValueKind.Null)
                Assert.Null(got.Score);
            else
                Assert.True(Math.Abs(e.GetProperty("score").GetDouble() - got.Score!.Value) <= 5e-4, $"{name}: score {got.Score}");
            foreach (var part in e.GetProperty("parts").EnumerateObject())
                Assert.True(Math.Abs(part.Value.GetDouble() - got.Parts[part.Name]) <= 5e-4, $"{name}: {part.Name}");
        }
    }

    [Fact]
    public void The_note_and_silence_of_a_first_line_are_mosaics_word_for_word()
    {
        var notes = Load("initiative-vectors.json").GetProperty("notes").EnumerateArray().ToList();
        Assert.NotEmpty(notes);
        foreach (var n in notes)
        {
            var quiet = n.GetProperty("quietS").GetDouble();
            var followUp = n.GetProperty("followUp").ValueKind == JsonValueKind.Null ? null : n.GetProperty("followUp").GetString();
            Assert.Equal(n.GetProperty("note").GetString(), Initiative.Note(quiet, followUp, n.GetProperty("lastReply").GetString()!));
            Assert.Equal(n.GetProperty("silence").GetString(), Initiative.Silence(quiet));
        }
    }

    [Fact]
    public void A_chat_becomes_exchanges_and_turns_as_mosaic_counts_them()
    {
        var t0 = new DateTimeOffset(2026, 10, 28, 14, 0, 0, TimeSpan.Zero);
        StoredMessage M(string role, string text, int s, bool proactive = false) =>
            new($"m{s}", s, role, text, t0.AddSeconds(s), proactive ? new JsonObject { [Initiative.ProactiveMeta] = true } : null);
        var history = new[]
        {
            M("assistant", "你好", 0),               // no user message before it: not an exchange
            M("user", "今天面试，有点紧张", 10),
            M("assistant", "祝你面试顺利！", 15),
            M("assistant", "[picture]", 40),         // a picture after the reply dates that exchange
            M("assistant", "面试结束了吗？", 400, proactive: true),
            M("user", "还没回复", 500),              // not answered: left out
        };
        var exchanges = Initiative.Exchanges(history);
        Assert.Equal(2, exchanges.Count);
        Assert.Equal(("今天面试，有点紧张", "祝你面试顺利！", t0.AddSeconds(40)), (exchanges[0].User?.Content, exchanges[0].Reply.Content, exchanges[0].Last));
        Assert.Null(exchanges[1].User);
        var turns = Initiative.Turns(exchanges);
        Assert.Equal([true, false], turns.Select(t => t.Proactive));
        Assert.Equal(t0.AddSeconds(400).ToUnixTimeMilliseconds() / 1000.0, turns[0].Created);
        Assert.Equal("今天面试，有点紧张", turns[1].Input);
    }

    [Fact]
    public async Task Speaking_first_asks_no_model_when_a_gate_holds_her_back()
    {
        var ct = TestContext.Current.CancellationToken;
        var api = new AijadeApi(new HttpClient(new NoCalls()) { BaseAddress = new Uri("http://localhost/") }, new MemoryTokenStore());
        var now = DateTimeOffset.UtcNow;
        var history = new List<StoredMessage>
        {
            new("u", 1, "user", "我去洗澡了，待会聊", now.AddSeconds(-900)),
            new("a", 2, "assistant", "好的，待会见。", now.AddSeconds(-895)),
        };
        var orchestrator = new ChatOrchestrator(api, [], new OrchestratorOptions());
        await foreach (var e in orchestrator.SpeakFirstAsync("chat", null, history, "snap", 14, ct))
            Assert.Fail($"no line expected, got {e}");
        history[0] = history[0] with { Content = "今天面试，有点紧张" };
        await foreach (var e in orchestrator.SpeakFirstAsync("chat", null, history, "snap", 2, ct))
            Assert.Fail($"no line expected at night, got {e}");
    }

    [Fact]
    public void The_text_channel_rules_are_mosaics_word_for_word()
    {
        var v = Load("text-channel-vectors.json");
        var mosaic = v.GetProperty("mosaic");
        Assert.Equal(mosaic.GetProperty("channelNote").GetString(), TextChannel.ChannelNote(mosaic.GetProperty("medium").GetString()!));
        Assert.Equal(mosaic.GetProperty("movementNote").GetString(), TextChannel.MovementNote(mosaic.GetProperty("channel").GetString()!));
        Assert.Equal(v.GetProperty("movementWords").EnumerateArray().Select(x => x.GetString()), TextChannel.MovementWords);
        Assert.Equal(v.GetProperty("putOff").EnumerateArray().Select(x => x.GetString()), TextChannel.PutOffWords);
        Assert.Equal(TextChannel.Later, v.GetProperty("later").GetString());
        foreach (var c in v.GetProperty("cases").EnumerateArray())
            Assert.Equal(c.GetProperty("sent").GetString(), TextChannel.PutOff(c.GetProperty("text").GetString()!, c.GetProperty("reply").GetString()!));

        var contract = Load("contract.json").GetProperty("textChannels");
        Assert.Equal(TextChannel.ChannelNoteTemplate, contract.GetProperty("channelNote").GetString());
        Assert.Equal(TextChannel.MovementNoteTemplate, contract.GetProperty("movementNote").GetString());
    }

    [Fact]
    public void Text_channel_rules_apply_only_where_she_has_no_body()
    {
        Assert.Equal(("Telegram", "Discord", "X", "QQ", "Kook2"), (TextChannel.BodilessChannel("telegram"), TextChannel.BodilessChannel("discord"),
            TextChannel.BodilessChannel("x"), TextChannel.BodilessChannel("satori-qq"), TextChannel.BodilessChannel("satori-kook2")));
        Assert.Null(TextChannel.BodilessChannel("minecraft"));
        Assert.Null(TextChannel.BodilessChannel("bilibili"));
        Assert.Single(TextChannel.Notes("Telegram", "今天好累"));
        Assert.Equal(2, TextChannel.Notes("Telegram", "跳个舞吧").Count);
        Assert.StartsWith("This conversation is Telegram text messages, not the live scene", TextChannel.Notes("Telegram", "hi")[0], StringComparison.Ordinal);
    }

    private static string[] Strings(JsonElement array) => [.. array.EnumerateArray().Select(x => x.GetString()!)];

    private static string Keyed(IEnumerable<(string[] Keywords, string Value)> table) => string.Join(" | ", table.Select(t => string.Join(",", t.Keywords) + "=" + t.Value));

    [Fact]
    public void The_stage_words_and_spots_are_mosaics()
    {
        var v = Load("stage-vectors.json");
        var w = v.GetProperty("words");
        Assert.Equal(Strings(w.GetProperty("negations")), Stage.Negations);
        Assert.Equal(Strings(w.GetProperty("selfGoing")), Stage.SelfGoing);
        Assert.Equal(Strings(w.GetProperty("goWords")), Stage.GoWords);
        Assert.Equal(Strings(w.GetProperty("invitations")), Stage.Invitations);
        Assert.Equal(Strings(w.GetProperty("standUpWords")), Stage.StandUpWords);
        Assert.Equal(Strings(w.GetProperty("danceKeywords")), Stage.DanceKeywords);
        Assert.Equal(Stage.StandUp, w.GetProperty("standUp").GetString());
        string Table(string name, string value) => Keyed(w.GetProperty(name).EnumerateArray().Select(m => (Strings(m.GetProperty("keywords")), m.GetProperty(value).GetString()!)));
        Assert.Equal(Table("movements", "script"), Keyed(Stage.Movements));
        Assert.Equal(Table("gestures", "gesture"), Keyed(Stage.Gestures));
        Assert.Equal(Table("situationalGestures", "gesture"), Keyed(Stage.SituationalGestures));
        Assert.Equal(w.GetProperty("greeting").GetProperty("pattern").GetString(), Stage.Greeting.ToString());
        Assert.Equal(w.GetProperty("greeting").GetProperty("options").GetString(), Stage.Greeting.Options.ToString());

        var spots = v.GetProperty("spots").EnumerateArray().Select(s => new StageSpot(s.GetProperty("name").GetString()!, s.GetProperty("label").GetString()!,
            s.GetProperty("activity").GetString()!, s.GetProperty("room").GetString()!, Strings(s.GetProperty("aliases")))).ToList();
        Assert.Equal(spots.Select(s => (s.Name, s.Label, s.Activity, s.Room, string.Join(",", s.Aliases))),
            Stage.Spots.Select(s => (s.Name, s.Label, s.Activity, s.Room, string.Join(",", s.Aliases))));
        Assert.Equal(Strings(v.GetProperty("places")), Stage.PlaceWords);
        foreach (var d in v.GetProperty("doing").EnumerateObject())
            Assert.Equal(d.Value.GetString(), Stage.PlaceDoing(d.Name));
        Assert.All(Stage.Movements.Select(m => m.Script).Concat(Stage.Gestures.Concat(Stage.SituationalGestures).Select(g => g.Gesture)).Append("dance"),
            k => Assert.True(Stage.Doings.ContainsKey(k), k));
    }

    [Fact]
    public void The_stage_decides_as_mosaic_did_on_every_sentence()
    {
        static string? Str(JsonElement e, string name) => e.GetProperty(name).ValueKind == JsonValueKind.Null ? null : e.GetProperty(name).GetString();
        static string? Decision(JsonElement e) => e.ValueKind == JsonValueKind.Null ? null : $"{e.GetProperty("kind").GetString()}:{Str(e, "argument")}";
        static string? Of(StageAction? a) => a is null ? null : $"{a.Kind.ToString().ToLowerInvariant()}:{a.Argument}";
        var cases = Load("stage-vectors.json").GetProperty("cases").EnumerateArray().ToList();
        Assert.NotEmpty(cases);
        foreach (var c in cases)
        {
            var text = c.GetProperty("text").GetString()!;
            Assert.True(Str(c, "place") == Stage.Place(text), $"{text}: place {Stage.Place(text)}");
            Assert.True(Str(c, "movement") == Stage.Movement(text), $"{text}: movement {Stage.Movement(text)}");
            Assert.True(c.GetProperty("dance").GetBoolean() == Stage.Dance(text), $"{text}: dance");
            Assert.True(Str(c, "gesture") == Stage.Gesture(text), $"{text}: gesture {Stage.Gesture(text)}");
            Assert.True(Str(c, "gestureAsked") == Stage.Gesture(text, situational: false), $"{text}: asked gesture");
            Assert.True(Decision(c.GetProperty("decision")) == Of(Stage.Decide(text, seated: false)), $"{text}: decision {Of(Stage.Decide(text, false))}");
            Assert.True(Decision(c.GetProperty("decisionSeated")) == Of(Stage.Decide(text, seated: true)), $"{text}: seated decision");
        }
    }

    [Fact]
    public void The_stage_notes_are_the_contract_notes()
    {
        var notes = Load("contract.json").GetProperty("stage").GetProperty("notes");
        Assert.Equal(Stage.ActionNoteTemplate, notes.GetProperty("action").GetString());
        Assert.Equal(Stage.NoActionNote, notes.GetProperty("noAction").GetString());
        Assert.Equal(Stage.WhereNoteTemplate, notes.GetProperty("where").GetString());

        Assert.Equal([Stage.NoActionNote], Stage.Notes(Stage.Decide("今天好累", seated: false), null));
        var sofa = Stage.Notes(Stage.Decide("去沙发坐会儿吧", seated: false), "在客厅");
        Assert.Equal(2, sofa.Count);
        Assert.Contains("do this, because they asked: 去沙发坐下.", sofa[0], StringComparison.Ordinal);
        Assert.Contains("from the app: 在客厅.", sofa[1], StringComparison.Ordinal);
        Assert.Null(Stage.Decide("起来吧", seated: false));
        Assert.Equal("站起来", Stage.Decide("起来吧", seated: true)!.Doing);
    }

    [Fact]
    public void The_learned_note_is_the_contracts_and_leaves_out_third_party_content()
    {
        var learned = Load("contract.json").GetProperty("stage").GetProperty("learned");
        Assert.Equal(Stage.LearnedShared, learned.GetProperty("shared").GetString());
        Assert.Equal(Stage.LearnedFields, learned.GetProperty("fields").GetProperty("aijade").GetString());

        Assert.Null(Stage.LearnedNote([]));
        Assert.Equal([Stage.NoActionNote], Stage.Notes(null, null, []));
        LearnedMotion walk = new("2026-10-29", "walk", "走路", 42.5, null, "走路 全身 固定机位 练习", "某UP主", "bilibili");
        LearnedMotion turn = new("2026-10-28", "turn", "转身", 12, 3.4, "转身教学", "另一位作者", "bilibili");
        var notes = Stage.Notes(null, "在客厅", [walk, turn]);
        Assert.Equal(3, notes.Count);
        Assert.Equal($"{Stage.LearnedShared} {Stage.LearnedFields} learned_recently: 2026-10-29 走路 (42.5 s); 2026-10-28 转身 (12.0 s).", notes[2]);
        foreach (var thirdParty in new[] { "固定机位", "某UP主", "转身教学", "另一位作者" })
            Assert.DoesNotContain(thirdParty, notes[2], StringComparison.Ordinal);
    }

    private sealed class NoCalls : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("no call expected");
    }
}
