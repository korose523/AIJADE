using System.Net;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Client.Companion;
using Aijade.Client.Settings;
using Aijade.Server.Product;

using Jint;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

/// <summary>
/// Her selfies now and then (ADR-003, migration batch 2): when (the port of MOSAIC's share.due, against vectors its own module
/// made), where her phone is (tools/mmd-bundle/selfie-shot.js in Jint, against MOSAIC's SelfieShot), and how a picture is kept
/// and put in the chat as her line.
/// </summary>
public class SelfiesTests
{
    private static readonly string Root = RqcReanalysisTests.RepoRoot();
    private static readonly string[] ShotConstants = ["Arm", "Above", "Aside", "FovDegrees", "FaceDrop", "UprightDegrees", "Width", "Height"];
    private static readonly string[] ShotFields = ["camera", "look", "facing", "up"];

    private static JsonElement Vectors()
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "configs", "companion", "selfie-vectors.json")));
        return doc.RootElement.Clone();
    }

    [Fact]
    public void She_takes_a_picture_when_MOSAICs_rules_would()
    {
        var v = Vectors();
        var zone = TimeZoneInfo.FindSystemTimeZoneById(v.GetProperty("timeZone").GetString()!);
        var rules = v.GetProperty("rules");
        Assert.Equal(new SelfieRules(rules.GetProperty("perDay").GetInt32(), rules.GetProperty("fromHour").GetDouble(), rules.GetProperty("toHour").GetDouble(),
            rules.GetProperty("minGapHours").GetDouble(), rules.GetProperty("ownerAwayMin").GetDouble(), rules.GetProperty("chancePerMinute").GetDouble()), SelfieRules.Default);
        Assert.Equal((rules.GetProperty("night")[0].GetInt32(), rules.GetProperty("night")[1].GetInt32()), (Selfies.NightFrom, Selfies.NightTo));
        var now0 = v.GetProperty("now").GetProperty("epoch").GetDouble();
        var checkedCases = 0;
        foreach (var c in v.GetProperty("due").EnumerateArray())
        {
            if (!c.GetProperty("settled").GetBoolean())
                continue; // MOSAIC waits until she has settled in her home; AIJADE's stage has no home
            var now = now0 + c.GetProperty("nowS").GetDouble();
            var taken = c.GetProperty("takenS").EnumerateArray().Select(t => now0 + t.GetDouble()).ToList();
            double? ownerAgo = c.GetProperty("ownerAgoS").ValueKind == JsonValueKind.Null ? null : c.GetProperty("ownerAgoS").GetDouble();
            var (due, why) = Selfies.Due(c.GetProperty("on").GetBoolean() ? SelfieRules.Default : null, Selfies.Today(taken, now, zone), now, ownerAgo,
                c.GetProperty("random").GetDouble(), zone);
            Assert.True((c.GetProperty("due").GetBoolean(), c.GetProperty("why").GetString()) == (due, why),
                $"{c.GetProperty("name").GetString()}: MOSAIC {c.GetProperty("due").GetBoolean()} ({c.GetProperty("why").GetString()}), port {due} ({why})");
            checkedCases++;
        }
        Assert.Equal(15, checkedCases);
    }

    [Fact]
    public void Her_phone_is_where_MOSAICs_SelfieShot_puts_it()
    {
        var v = Vectors().GetProperty("frame");
        var constants = v.GetProperty("constants");
        var engine = new Engine();
        engine.Modules.Add("selfie-shot", File.ReadAllText(Path.Combine(Root, "tools", "mmd-bundle", "selfie-shot.js")));
        engine.Modules.Add("runner", """
            import { frame, ARM, ABOVE, ASIDE, FOV_DEGREES, FACE_DROP, UPRIGHT_DEGREES, WIDTH, HEIGHT } from 'selfie-shot';
            export function constants() { return JSON.stringify([ARM, ABOVE, ASIDE, FOV_DEGREES, FACE_DROP, UPRIGHT_DEGREES, WIDTH, HEIGHT]); }
            export function run(json) {
              const v = (a) => a && ({ x: a[0], y: a[1], z: a[2] });
              return JSON.stringify(JSON.parse(json).map(c => {
                try {
                  const s = frame(v(c.head), v(c.left), v(c.right), v(c.body), v(c.neck));
                  return { camera: [s.camera.x, s.camera.y, s.camera.z], look: [s.look.x, s.look.y, s.look.z],
                           facing: [s.facing.x, s.facing.y, s.facing.z], up: [s.up.x, s.up.y, s.up.z], error: null };
                } catch (e) { return { error: e.message }; }
              }));
            }
            """);
        var runner = engine.Modules.Import("runner");
        var mine = JsonSerializer.Deserialize<double[]>(engine.Invoke(runner.Get("constants")).AsString())!;
        Assert.Equal(ShotConstants.Select(k => Math.Round(constants.GetProperty(k).GetDouble(), 6)),
            mine.Select(x => Math.Round(x, 6)));
        var cases = v.GetProperty("cases");
        using var ported = JsonDocument.Parse(engine.Invoke(runner.Get("run"), cases.GetRawText()).AsString());
        foreach (var (c, got) in cases.EnumerateArray().Zip(ported.RootElement.EnumerateArray()))
        {
            var name = c.GetProperty("name").GetString();
            var expected = c.GetProperty("expected");
            Assert.Equal(expected.GetProperty("error").GetString(), got.GetProperty("error").GetString());
            if (expected.GetProperty("error").ValueKind != JsonValueKind.Null)
                continue;
            foreach (var field in ShotFields)
            {
                var a = expected.GetProperty(field).EnumerateArray().Select(x => x.GetDouble()).ToArray();
                var b = got.GetProperty(field).EnumerateArray().Select(x => x.GetDouble()).ToArray();
                Assert.True(a.Zip(b).All(p => Math.Abs(p.First - p.Second) < 1e-4), $"{name}, {field}: MOSAIC {string.Join(',', a)}, port {string.Join(',', b)}");
            }
        }
    }

    [Fact]
    public async Task Only_todays_pictures_count_and_two_days_are_kept()
    {
        var zone = TimeZoneInfo.FindSystemTimeZoneById("Asia/Seoul");
        var now = new DateTimeOffset(2026, 11, 3, 15, 0, 0, TimeSpan.FromHours(9)).ToUnixTimeSeconds();
        Assert.Equal([now - 3 * 3600.0, now - 60], Selfies.Today([now - 60, now - 16 * 3600, now - 3 * 3600], now, zone)); // 23:00 yesterday is not today
        var store = new SelfieStore(new InMemoryKeyValueStore(), () => "account-1");
        await store.RecordAsync(now - 3 * 86400);
        await store.RecordAsync(now - 3600);
        await store.RecordAsync(now);
        Assert.Equal([now - 3600.0, now], await store.LoadAsync());
        Assert.Empty(await new SelfieStore(new InMemoryKeyValueStore(), () => "account-2").LoadAsync());
    }

    [Fact]
    public async Task A_selfie_is_kept_for_the_account_and_put_in_the_chat_as_her_line()
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
        var chat = await api.CreateChatAsync(null, "selfie", ct);
        byte[] jpeg = [0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, .. "JFIF"u8, 0x00, 1, 2, 3, 4, 5, 0xFF, 0xD9];

        var line = await Selfies.ShareAsync(api, chat.Id, jpeg, "拍一张给你。", "mmd", ct);
        Assert.Equal(("assistant", "拍一张给你。"), (line.Role, line.Content));
        Assert.True(Initiative.IsProactive(line)); // a line she began: speaking first counts it
        Assert.True(Selfies.IsSelfie(line));
        var image = Artistry.ImageOf(line)!;
        Assert.Equal(("image/jpeg", "拍一张给你。"), (image.Mime, image.Prompt));
        var (bytes, mime) = await api.ImageBytesAsync(image.Id, ct);
        Assert.Equal(jpeg, bytes);
        Assert.Equal("image/jpeg", mime);

        // Told to the model as a selfie, not as a drawing.
        await foreach (var _ in new ChatOrchestrator(api, [], new OrchestratorOptions()).SendAsync(chat.Id, null, await api.MessagesAsync(chat.Id, ct: ct), "好看！", "snap", null, ct))
        {
        }
        var sent = JsonNode.Parse(llm.LastBody!)!["messages"]!.AsArray().Select(m => m!["content"]!.GetValue<string>()).ToList();
        Assert.Contains("[I sent them a selfie from the stage: 拍一张给你。]", sent);

        // Only a JPEG or PNG of at most 2 MB, with a caption and the stage that took it.
        async Task<HttpStatusCode> PostAsync(byte[] picture, string caption, string renderer)
        {
            using var form = new MultipartFormDataContent();
            form.Add(new ByteArrayContent(picture), "file", "selfie.jpg");
            form.Add(new StringContent(caption), "caption");
            form.Add(new StringContent(renderer), "renderer");
            using var req = new HttpRequestMessage(HttpMethod.Post, "/api/v1/images/selfie") { Content = form };
            req.Headers.Authorization = new("Bearer", ServerTestHost.Token);
            using var res = await host.Client.SendAsync(req, ct);
            return res.StatusCode;
        }
        Assert.Equal(HttpStatusCode.Created, await PostAsync([0x89, .. "PNG"u8, 0x0D, 0x0A, 0x1A, 0x0A, 0, 0], "拍一张给你。", "avatar"));
        Assert.Equal(HttpStatusCode.BadRequest, await PostAsync("GIF89a"u8.ToArray(), "拍一张给你。", "mmd"));
        Assert.Equal(HttpStatusCode.BadRequest, await PostAsync(jpeg, "", "mmd"));
        Assert.Equal(HttpStatusCode.BadRequest, await PostAsync(jpeg, new string('拍', ImageEndpoints.MaxCaptionLength + 1), "mmd"));
        Assert.Equal(HttpStatusCode.BadRequest, await PostAsync(jpeg, "拍一张给你。", "comfyui"));
        Assert.Equal(HttpStatusCode.BadRequest, await PostAsync([0xFF, 0xD8, 0xFF, .. new byte[ImageEndpoints.MaxSelfieBytes]], "拍一张给你。", "mmd"));
    }

    private sealed class FakeLlm : HttpMessageHandler
    {
        public string? LastBody { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            LastBody = await request.Content!.ReadAsStringAsync(cancellationToken);
            const string sse = "data: {\"choices\":[{\"delta\":{\"content\":\"谢谢！\"}}]}\n\ndata: [DONE]\n\n";
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(sse, System.Text.Encoding.UTF8, "text/event-stream") };
        }
    }
}
