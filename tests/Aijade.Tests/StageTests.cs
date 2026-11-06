using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Companion;
using Aijade.Memory.Contracts;
using Aijade.Server.Product;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

/// <summary>
/// MOSAIC's home as her stage (docs/STAGE-MOSAIC.md, plan A step 2): the command line the chat sends after a reply, the
/// server's relay to the workbench (admins only, loopback only, the chat's commands only), and the client's view of it.
/// Non-research line only.
/// </summary>
public class StageTests
{
    private static readonly ExpressionVector Calm = new(0.2, 0.3, 0.5, 0, 0, 0.4, 0, 0, 0);

    private static JsonElement Vectors()
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(RqcReanalysisTests.RepoRoot(), "configs", "companion", "stage-vectors.json")));
        return doc.RootElement.Clone();
    }

    [Fact]
    public void A_reply_becomes_expression_speech_and_the_decided_action()
    {
        Assert.Equal("表情 0.2 0.3 0.5 0.4; 说 好呀，我去沙发上坐会儿。; 去 沙发",
            Stage.CommandLine(Calm, "好呀，我去沙发上坐会儿。", Stage.Decide("去沙发坐会儿吧", seated: false)));
        Assert.Equal("表情 0.2 0.3 0.5 0.4; 说 好的，起来啦。; 起来", Stage.CommandLine(Calm, "好的，起来啦。", Stage.Decide("起来吧", seated: true)));
        Assert.Equal("表情 0.2 0.3 0.5 0.4; 说 来啦。; 走路 @approach", Stage.CommandLine(Calm, "来啦。", Stage.Decide("过来一下好吗", seated: false)));
        Assert.Equal("表情 0.2 0.3 0.5 0.4; 说 好。; 跳舞", Stage.CommandLine(Calm, "好。", Stage.Decide("跳个舞吧", seated: false)));
        Assert.Equal("表情 0.2 0.3 0.5 0.4; 说 再见。; 手势 拜拜", Stage.CommandLine(Calm, "再见。", Stage.Decide("谢谢，再见", seated: false)));
        Assert.Equal("表情 0.2 0.3 0.5 0.4; 说 辛苦了，早点休息。", Stage.CommandLine(Calm, "辛苦了；早点休息。", Stage.Decide("今天好累", seated: false)));
        Assert.Equal("表情 -1 1 0 0", Stage.CommandLine(new(-3, 2, -1, 0, 0, double.NaN, 0, 0, 0), "", null)); // clamped; nothing to say
    }

    [Fact]
    public void Every_command_the_chat_can_send_is_one_the_workbench_and_the_relay_take()
    {
        var words = Vectors().GetProperty("words");
        var gestureNames = words.GetProperty("gestureNames").EnumerateObject().ToDictionary(p => p.Name, p => p.Value.GetString());
        var goalWalks = words.GetProperty("goalWalks").EnumerateObject().Select(p => p.Name).ToHashSet();
        foreach (var (_, gesture) in Stage.Gestures.Concat(Stage.SituationalGestures).Append(([], "bye")))
            Assert.Equal(gesture, gestureNames[Stage.GestureCommandNames[gesture]]); // 手势 <name> names that gesture
        foreach (var (_, script) in Stage.Movements)
            Assert.True(goalWalks.Contains(script) || !script.StartsWith('@'), script); // a goal token the walk command knows, or a script

        foreach (var c in Vectors().GetProperty("cases").EnumerateArray())
        {
            var text = c.GetProperty("text").GetString()!;
            foreach (var seated in new[] { false, true })
            {
                var line = Stage.CommandLine(Calm, "嗯；好的。", Stage.Decide(text, seated));
                Assert.Null(StageEndpoints.Refused(line));
            }
        }
    }

    [Fact]
    public void Speech_is_cut_into_pieces_the_workbench_takes()
    {
        Assert.Equal(["一，二，三"], Stage.SpeechPieces("一；二;\n三"));
        var sentence = new string('好', 120) + "。";
        var pieces = Stage.SpeechPieces(sentence + sentence + sentence);
        Assert.Equal([sentence + sentence, sentence], pieces); // cut after a sentence end
        var emoji = string.Concat(Enumerable.Repeat("😀", 200));
        var cut = Stage.SpeechPieces(emoji);
        Assert.All(cut, p => Assert.True(p.Length <= Stage.MaxSpeech));
        Assert.Equal(emoji, string.Concat(cut)); // no surrogate pair split
        Assert.Empty(Stage.SpeechPieces(" ；\n"));
    }

    [Fact]
    public void The_relay_reaches_only_a_workbench_on_this_machine_and_only_with_the_chats_commands()
    {
        Assert.Null(StageEndpoints.Workbench(null));
        Assert.Null(StageEndpoints.Workbench(" "));
        Assert.Equal(5002, StageEndpoints.Workbench("http://localhost:5002")!.Port);
        Assert.NotNull(StageEndpoints.Workbench("http://127.0.0.1:5002"));
        Assert.NotNull(StageEndpoints.Workbench("http://[::1]:5002"));
        foreach (var bad in new[] { "http://192.168.1.20:5002", "http://100.115.181.90:5002", "https://example.com", "ftp://localhost/", "localhost:5002" })
            Assert.Throws<InvalidOperationException>(() => StageEndpoints.Workbench(bad));

        Assert.Null(StageEndpoints.Refused("表情 0 0.4 0.5 0.5; 说 你好；去 沙发\n起来"));
        Assert.Equal("聊天 你好", StageEndpoints.Refused("说 好; 聊天 你好"));
        Assert.Equal("播放", StageEndpoints.Refused("播放"));
        Assert.Equal("说你好", StageEndpoints.Refused("说你好"));
    }

    [Fact]
    public void The_relay_passes_only_the_contracts_fields_of_at_most_five_learned_motions()
    {
        var items = new JsonArray();
        for (var i = 0; i < 7; i++)
        {
            items.Add(new JsonObject
            {
                ["day"] = $"2026-10-2{i}", ["skill"] = "walk", ["skill_words"] = "走路", ["kept_seconds"] = 1.5 + i, ["novel_seconds"] = null,
                ["video_title"] = "标题", ["uploader"] = "UP", ["source"] = "bilibili", ["at"] = "2026-10-29T08:00:00+09:00", ["file"] = "/home/learned.json",
            });
        }
        var relayed = StageEndpoints.Learned(items);
        Assert.Equal(StageEndpoints.MaxLearned, relayed.Count);
        Assert.Equal(StageEndpoints.LearnedFields, ((JsonObject)relayed[0]!).Select(p => p.Key));
        Assert.Null(relayed[0]!["novel_seconds"]);
        Assert.Equal("2026-10-20", relayed[0]!["day"]!.GetValue<string>()); // the workbench's order: newest first
        Assert.Empty(StageEndpoints.Learned(null));
        Assert.Empty(StageEndpoints.Learned(JsonValue.Create("not a list")));
    }

    private static readonly StageAction Sofa = new(StageActionKind.Place, "沙发", "去沙发坐下");
    private static readonly StageAction Up = new(StageActionKind.Stand, null, "站起来");
    private static readonly StageAction Walk = new(StageActionKind.Walk, "@approach", "走过来");
    private static readonly StageAction Dance = new(StageActionKind.Dance, null, "跳一支舞");
    private static readonly StageAction Wave = new(StageActionKind.Gesture, "bye", "挥手");

    public static TheoryData<string, string, StageOutcome> Notices => new()
    {
        // Worded as in MOSAIC's LiveSceneService.cs r683; the live run's own notices are in the next test.
        { "place", "她在沙发坐下了", StageOutcome.Done },
        { "place", "她在床上躺下了", StageOutcome.Done },
        { "place", "她到了篮球场", StageOutcome.Done },
        { "place", "去不了沙发：规划去处失败", StageOutcome.Failed },
        { "place", "走不到沙发", StageOutcome.Failed },
        { "place", "到了沙发，但还没有坐下、躺下的片段：先运行 tools/build_home_poses.py。", StageOutcome.Failed },
        { "place", "去沙发（3.1 m）", StageOutcome.Failed }, // the walk began and the session ended before she arrived
        { "place", "不知道「沙发」在哪里", StageOutcome.Failed }, // free text from its planner
        { "place", "去沙发", StageOutcome.Unknown }, // the realtime controller accepted it; where she ends up is its own
        { "place", "语音服务没开：合成。回复会改用系统语音", StageOutcome.Unknown },
        { "stand", "她站起来了", StageOutcome.Done },
        { "stand", "她起床了", StageOutcome.Done },
        { "stand", "她没有坐着或躺着。", StageOutcome.Done },
        { "stand", "起来", StageOutcome.Unknown },
        { "stand", "指令序列中止：动作库（LiveScene:MotionLibrary）不在了，她站不起来。", StageOutcome.Failed },
        { "walk", "走路播完：停在走到的位置（路程 1.49 m，转过 114.6°），已在场景内切回 idle.vmd", StageOutcome.Done },
        { "walk", "走路片段已生成并重启播放：路程 1.49 m，最终朝向 114.6°（a.vmd）", StageOutcome.Done },
        { "walk", "走路播完切回原片段在她现在的位置播不了（这个片段绑在原点），没有重启场景。", StageOutcome.Done },
        { "walk", "走路在她现在的位置播不了（这个片段绑在原点），没有重启场景。", StageOutcome.Failed },
        { "walk", "走路（规则转向）：已在场景内切换播放（路程 1.49 m，最终朝向 114.6°，a.vmd）", StageOutcome.Failed }, // the session ended mid-way
        { "walk", "她到了沙发", StageOutcome.Failed },
        { "dance", "舞蹈「check-plie」播完，已在场景内切回 idle.vmd", StageOutcome.Done },
        { "dance", "指令序列中止：还没有舞蹈库：先运行 tools/build_dance_library.py。", StageOutcome.Failed },
        { "gesture", "手势「bye」播完，已在场景内切回 idle.vmd", StageOutcome.Done },
        { "gesture", "手势「bye」在她现在的位置播不了（这个片段绑在原点），没有重启场景。", StageOutcome.Failed },
        { "gesture", "提醒：该喝水了", StageOutcome.Unknown },
    };

    private static StageAction ActionOf(string kind) => kind switch
    {
        "place" => Sofa, "stand" => Up, "walk" => Walk, "dance" => Dance, "gesture" => Wave, _ => throw new ArgumentOutOfRangeException(nameof(kind)),
    };

    [Theory]
    [MemberData(nameof(Notices))]
    public void What_is_left_in_the_notice_says_whether_her_body_did_it(string kind, string notice, StageOutcome expected) =>
        Assert.Equal(expected, Stage.Outcome(ActionOf(kind), "以前的提示", notice));

    [Fact]
    public void The_notices_of_the_live_run_are_judged_as_expected_before_it()
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(RqcReanalysisTests.RepoRoot(), "configs", "companion", "stage-notices.json")));
        var cases = doc.RootElement.GetProperty("cases").EnumerateArray().ToList();
        Assert.NotEmpty(cases);
        foreach (var c in cases)
        {
            var action = c.GetProperty("kind").GetString() is { Length: > 0 } kind ? ActionOf(kind) : null;
            var expected = Enum.Parse<StageOutcome>(c.GetProperty("expected").GetString()!);
            Assert.Equal(expected, Stage.Outcome(action, c.GetProperty("before").GetString(), c.GetProperty("notice").GetString()));
        }
    }

    [Fact]
    public void Without_an_action_only_a_newly_stopped_line_counts_and_a_missing_notice_says_nothing()
    {
        const string stopped = Stage.StoppedNotice + "说话失败";
        Assert.Equal(StageOutcome.Failed, Stage.Outcome(null, null, stopped));
        Assert.Equal(StageOutcome.Unknown, Stage.Outcome(null, stopped, stopped)); // left over from an earlier line
        Assert.Equal(StageOutcome.Unknown, Stage.Outcome(null, null, "她站起来了"));
        Assert.Equal(StageOutcome.Unknown, Stage.Outcome(Sofa, null, null));
        Assert.Equal(StageOutcome.Unknown, Stage.Outcome(Sofa, null, " "));
    }

    [Fact]
    public void The_model_is_told_which_action_did_not_happen_and_not_the_workbenchs_words()
    {
        var notes = Stage.Notes(null, "在客厅", null, Dance);
        Assert.Equal(3, notes.Count);
        Assert.Equal(Stage.UndoneNoteTemplate.Replace("{doing}", "跳一支舞", StringComparison.Ordinal), notes[2]);
        Assert.Equal(2, Stage.Notes(null, "在客厅").Count);
    }

    [Fact]
    public void The_relay_cuts_the_notice_and_takes_only_a_string()
    {
        Assert.Equal("她到了床上", StageEndpoints.Notice(JsonValue.Create("她到了床上")));
        Assert.Equal(StageEndpoints.MaxNotice, StageEndpoints.Notice(JsonValue.Create(new string('字', 400)))!.Length);
        Assert.Null(StageEndpoints.Notice(null));
        Assert.Null(StageEndpoints.Notice(JsonValue.Create("")));
        Assert.Null(StageEndpoints.Notice(JsonValue.Create(3)));
    }

    /// <summary>Answers GET /api/v1/stage with the given states in turn, keeping the last; null is a refused connection.</summary>
    private sealed class StageReplies(params JsonObject?[] replies) : HttpMessageHandler
    {
        private int asked;

        public int Asked => asked;

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var reply = replies[Math.Min(asked++, replies.Length - 1)];
            return reply is null
                ? throw new HttpRequestException("connection refused")
                : Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(reply.ToJsonString(), Encoding.UTF8, "application/json") });
        }
    }

    private static JsonObject Scene(bool? busy, string? notice) => new() { ["running"] = true, ["reachable"] = true, ["sequenceRunning"] = busy, ["notice"] = notice };

    private static MosaicStage StageOver(StageReplies replies) =>
        new(new AijadeApi(new HttpClient(replies) { BaseAddress = new Uri("http://localhost/") }, new MemoryTokenStore()));

    [Fact]
    public async Task Following_a_line_waits_until_it_has_finished_and_keeps_asking_through_a_restart()
    {
        var ct = TestContext.Current.CancellationToken;
        var every = TimeSpan.FromMilliseconds(1);
        var failing = new StageReplies(
            Scene(true, "去沙发（3.1 m）"),
            null, // the scene restarting or the server away
            new JsonObject { ["running"] = false },
            Scene(false, Stage.StoppedNotice + "场景没有接受走路片段。"));
        Assert.Equal(new StageReport(StageOutcome.Failed, Stage.StoppedNotice + "场景没有接受走路片段。"), await StageOver(failing).FollowAsync(Sofa, null, every, TimeSpan.FromMinutes(1), ct));
        Assert.Equal(4, failing.Asked);

        Assert.Equal(StageOutcome.Done, (await StageOver(new StageReplies(Scene(true, null), Scene(false, "她在沙发坐下了"))).FollowAsync(Sofa, null, every, TimeSpan.FromMinutes(1), ct)).Outcome);
    }

    [Fact]
    public async Task A_line_that_never_finishes_or_a_workbench_that_does_not_say_is_not_called_a_failure()
    {
        var ct = TestContext.Current.CancellationToken;
        var every = TimeSpan.FromMilliseconds(1);
        var limit = TimeSpan.FromMilliseconds(30);
        Assert.Equal(new StageReport(StageOutcome.Unknown, null), await StageOver(new StageReplies(Scene(true, "去不了沙发"))).FollowAsync(Sofa, null, every, limit, ct));
        Assert.Equal(new StageReport(StageOutcome.Unknown, null), await StageOver(new StageReplies(Scene(null, "去不了沙发"))).FollowAsync(Sofa, null, every, limit, ct));
        using var cancelled = new CancellationTokenSource();
        await cancelled.CancelAsync();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => StageOver(new StageReplies(Scene(true, null))).FollowAsync(Sofa, null, every, limit, cancelled.Token));
    }

    private sealed class FakeWorkbench : HttpMessageHandler
    {
        public List<(string Path, string? Body)> Requests { get; } = [];

        public JsonObject State { get; set; } = new()
        {
            ["running"] = true, ["where"] = "在客厅，沙发，坐着", ["posture"] = "sit", ["sequenceRunning"] = false, ["notice"] = "她在沙发坐下了", ["logTail"] = "not relayed",
            ["learned"] = new JsonArray(new JsonObject
            {
                ["day"] = "2026-10-29", ["skill"] = "walk", ["skill_words"] = "走路", ["kept_seconds"] = 42.5, ["novel_seconds"] = null,
                ["video_title"] = "走路 全身 固定机位 练习", ["uploader"] = "某UP主", ["source"] = "bilibili",
            }),
        };

        public bool Down { get; set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (Down)
                throw new HttpRequestException("connection refused");
            var body = request.Content is null ? null : await request.Content.ReadAsStringAsync(cancellationToken);
            Requests.Add((request.RequestUri!.AbsolutePath, body));
            if (request.Method == HttpMethod.Get)
                return Json(HttpStatusCode.OK, State);
            var text = JsonNode.Parse(body!)!["text"]!.GetValue<string>();
            return text.Contains("去 月球", StringComparison.Ordinal)
                ? Json(HttpStatusCode.BadRequest, new JsonObject { ["error"] = "「去 月球」：家里没有这个地方。" })
                : Json(HttpStatusCode.OK, new JsonObject { ["sent"] = new JsonArray() });
        }

        private static HttpResponseMessage Json(HttpStatusCode status, JsonNode body) =>
            new(status) { Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json") };
    }

    [Fact]
    public async Task The_server_relays_the_stage_for_admins_only()
    {
        var ct = TestContext.Current.CancellationToken;
        var workbench = new FakeWorkbench();
        await using var host = await ServerTestHost.StartAsync(new Dictionary<string, string?> { [StageEndpoints.ConfigKey] = "http://127.0.0.1:5002" }, worker: false,
            services: s => s.AddHttpClient(StageEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => workbench));

        Assert.Equal(403, (await host.SendAsync(HttpMethod.Get, "/api/v1/stage")).Status); // a user account may not drive the owner's device
        var (status, state) = await host.SendAsync(HttpMethod.Get, "/api/v1/stage", token: ServerTestHost.AdminToken);
        Assert.Equal(200, status);
        Assert.Equal(("在客厅，沙发，坐着", "sit", true), (state!["where"]!.GetValue<string>(), state["posture"]!.GetValue<string>(), state["running"]!.GetValue<bool>()));
        Assert.Equal("走路", state["learned"]![0]!["skill_words"]!.GetValue<string>());
        Assert.Equal(("她在沙发坐下了", false), (state["notice"]!.GetValue<string>(), state["sequenceRunning"]!.GetValue<bool>()));
        Assert.Null(state["logTail"]);

        var line = Stage.CommandLine(Calm, "好呀。", Stage.Decide("去床上躺着吧", seated: true));
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Post, "/api/v1/stage/command", new JsonObject { ["text"] = line }, ServerTestHost.AdminToken)).Status);
        Assert.Equal(("/api/v1/live-scene/command", line), (workbench.Requests[^1].Path, JsonNode.Parse(workbench.Requests[^1].Body!)!["text"]!.GetValue<string>()));

        var sent = workbench.Requests.Count;
        var (refusedStatus, refused) = await host.SendAsync(HttpMethod.Post, "/api/v1/stage/command", new JsonObject { ["text"] = "说 好; 聊天 你好" }, ServerTestHost.AdminToken);
        Assert.Equal((400, "STAGE_COMMAND_REFUSED"), (refusedStatus, refused!["error"]!.GetValue<string>()));
        Assert.Equal(sent, workbench.Requests.Count); // not relayed
        var (badStatus, bad) = await host.SendAsync(HttpMethod.Post, "/api/v1/stage/command", new JsonObject { ["text"] = "去 月球" }, ServerTestHost.AdminToken);
        Assert.Equal(400, badStatus);
        Assert.Contains("家里没有这个地方", bad!["message"]!.GetValue<string>(), StringComparison.Ordinal);

        var tokens = new MemoryTokenStore();
        await tokens.SetAsync(ServerTestHost.AdminToken);
        var stage = new MosaicStage(new AijadeApi(host.Client, tokens));
        var home = await stage.StateAsync(ct);
        Assert.Equal(("在客厅，沙发，坐着", "sit", true), (home!.Where, home.Posture, home.Running));
        Assert.Equal(("她在沙发坐下了", false), (home.Notice, home.SequenceRunning));
        Assert.Equal([new LearnedMotion("2026-10-29", "walk", "走路", 42.5, null, "走路 全身 固定机位 练习", "某UP主", "bilibili")], home.Learned!);
        Assert.DoesNotContain("某UP主", Stage.LearnedNote(home.Learned)!, StringComparison.Ordinal); // third-party content stays out of the prompt
        workbench.State = new JsonObject { ["running"] = false, ["where"] = null, ["posture"] = null };
        Assert.Null(await stage.StateAsync(ct)); // no scene: the chat goes on as usual
        workbench.Down = true;
        Assert.Null(await stage.StateAsync(ct));
        await Assert.ThrowsAsync<AijadeApiException>(() => stage.SendAsync("说 你好", ct));
        await tokens.SetAsync(ServerTestHost.Token);
        workbench.Down = false;
        Assert.Null(await stage.StateAsync(ct)); // a user account sees no stage
    }

    [Fact]
    public async Task Without_a_workbench_address_there_is_no_stage()
    {
        await using var host = await ServerTestHost.StartAsync(worker: false);
        Assert.Equal(404, (await host.SendAsync(HttpMethod.Get, "/api/v1/stage", token: ServerTestHost.AdminToken)).Status);
        Assert.Equal(404, (await host.SendAsync(HttpMethod.Post, "/api/v1/stage/command", new JsonObject { ["text"] = "说 你好" }, ServerTestHost.AdminToken)).Status);
    }
}
