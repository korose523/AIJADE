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

    private sealed class FakeWorkbench : HttpMessageHandler
    {
        public List<(string Path, string? Body)> Requests { get; } = [];

        public JsonObject State { get; set; } = new()
        {
            ["running"] = true, ["where"] = "在客厅，沙发，坐着", ["posture"] = "sit",
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
