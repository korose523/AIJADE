using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Client.Companion;
using Aijade.Client.Settings;
using Aijade.Integrations;

namespace Aijade.Tests;

public sealed class CompanionExperienceTests
{
    private static readonly DateTimeOffset Now = new(2026, 11, 9, 6, 0, 0, TimeSpan.Zero);
    private const string Picture = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWQ0AAAAASUVORK5CYII=";
    private sealed class Clock : TimeProvider { public DateTimeOffset Now { get; set; } = CompanionExperienceTests.Now; public override DateTimeOffset GetUtcNow() => Now; }
    private sealed class WeatherHttp(Clock time) : HttpMessageHandler
    {
        public int Calls { get; private set; }
        public bool Fail { get; set; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            if (Fail) throw new HttpRequestException("offline");
            var json = request.RequestUri!.Host.StartsWith("geocoding", StringComparison.Ordinal)
                ? """{"results":[{"name":"Seoul","country":"South Korea","latitude":37.56,"longitude":126.97,"timezone":"Asia/Seoul"}]}"""
                : new JsonObject { ["current"] = new JsonObject { ["time"] = time.Now.ToUnixTimeSeconds(), ["temperature_2m"] = 12.5, ["weather_code"] = 3 } }.ToJsonString();
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(json, Encoding.UTF8, "application/json") });
        }
    }

    [Fact]
    public void Daily_life_obeys_the_chosen_timezone_season_and_identity_and_changes_with_time()
    {
        var p = new CompanionProfile { TimeZone = "Asia/Seoul", Latitude = 37.56 };
        CompanionAsset winter = new("w", "outfit", "winter", Picture, "coat", "winter");
        CompanionAsset autumn = new("a", "outfit", "autumn", Picture, "knitwear", "autumn");
        var snapshot = CompanionWorld.Now(p, [winter, autumn], Now, "person:a");
        Assert.Equal(15, snapshot.LocalTime.Hour);
        Assert.Equal("a", snapshot.Outfit!.Id);
        Assert.Equal(snapshot, CompanionWorld.Now(p, [autumn, winter], Now, "person:a"));
        Assert.NotEqual(snapshot.Activity, CompanionWorld.Now(p, [winter, autumn], Now.AddHours(10), "person:a").Activity);
        Assert.NotEqual(snapshot.Id, CompanionWorld.Now(p, [winter, autumn], Now.AddDays(1), "person:a").Id);
        Assert.Equal("w", CompanionWorld.Now(p with { Latitude = -37 }, [winter, autumn], Now.AddMonths(-5), "person:a").Outfit!.Id);
    }

    [Fact]
    public async Task Private_collections_survive_reopening_and_do_not_cross_people_or_characters()
    {
        var store = new InMemoryKeyValueStore();
        using var mine = new CompanionNotebook(store, "owner:aijade");
        await mine.AddAsync(new("a", "outfit", "围巾", Picture, "red scarf", "winter"), TestContext.Current.CancellationToken);
        using var reopened = new CompanionNotebook(store, "owner:aijade");
        using var another = new CompanionNotebook(store, "other:aijade");
        using var character = new CompanionNotebook(store, "owner:other");
        Assert.Single((await reopened.ReadAsync(ct: TestContext.Current.CancellationToken)).Assets);
        Assert.Empty((await another.ReadAsync(ct: TestContext.Current.CancellationToken)).Assets);
        Assert.Empty((await character.ReadAsync(ct: TestContext.Current.CancellationToken)).Assets);
        await reopened.RemoveAsync("a", TestContext.Current.CancellationToken);
        Assert.Empty((await mine.ReadAsync(ct: TestContext.Current.CancellationToken)).Assets);
    }

    [Fact]
    public void Relationship_updates_are_bounded_rate_limited_idempotent_and_do_not_punish_absence()
    {
        var first = CompanionRelationship.Observe(new(), "谢谢你", "one", Now);
        Assert.Equal(31, first.Affection);
        Assert.Equal(first, CompanionRelationship.Observe(first, "谢谢你", "one", Now));
        Assert.Equal(31, CompanionRelationship.Observe(first, "谢谢你", "two", Now.AddSeconds(1)).Affection);
        var later = CompanionRelationship.Observe(first, "我回来了", "later", Now.AddDays(30));
        Assert.True(later.Affection >= first.Affection);
        Assert.True(later.Mood < first.Mood);
        Assert.Equal(100, CompanionRelationship.Observe(first with { Affection = 100 }, "谢谢", "three", Now.AddHours(1)).Affection);
        Assert.Equal(0, CompanionRelationship.Observe(first with { Affection = 0 }, "讨厌你", "four", Now.AddHours(1)).Affection);
        Assert.True(CompanionRelationship.Observe(first, "有人骂我去死，我好难过", "distress", Now.AddHours(1)).Affection >= first.Affection);
    }

    [Fact]
    public async Task Weather_uses_configured_coordinates_caches_and_fails_without_fabrication()
    {
        var time = new Clock();
        var transport = new WeatherHttp(time);
        using var http = new HttpClient(transport);
        var weather = new CompanionWeather(http, time);
        Assert.Null(await weather.CurrentAsync(new(), TestContext.Current.CancellationToken));
        Assert.Equal(0, transport.Calls);
        var place = Assert.Single(await weather.FindAsync("Seoul", TestContext.Current.CancellationToken));
        var p = new CompanionProfile { City = place.Name, Latitude = place.Latitude, Longitude = place.Longitude, TimeZone = place.TimeZone, Weather = true };
        Assert.Equal(12.5, (await weather.CurrentAsync(p, TestContext.Current.CancellationToken))!.Temperature);
        Assert.NotNull(await weather.CurrentAsync(p, TestContext.Current.CancellationToken));
        Assert.Equal(2, transport.Calls);
        time.Now = Now.AddMinutes(21); transport.Fail = true;
        Assert.Null(await weather.CurrentAsync(p, TestContext.Current.CancellationToken));
        Assert.Null(await weather.CurrentAsync(p with { Latitude = double.NaN }, TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task Conversation_context_and_photos_use_the_same_life_and_clothes_without_changing_research_memory()
    {
        var time = new Clock();
        using var notebook = new CompanionNotebook(new InMemoryKeyValueStore(), "alice:aijade");
        await notebook.AddAsync(new("coat", "outfit", "蓝色外套", Picture, "blue coat", "autumn"), TestContext.Current.CancellationToken);
        var p = new CompanionProfile { TimeZone = "Asia/Seoul", Appearance = "silver hair, green eyes" };
        using var http = new HttpClient(new WeatherHttp(time));
        var experience = new CompanionExperience(notebook, () => p, new(http, time), "alice:aijade", time);
        var turn = new TurnContext("chat", null, [], "谢谢你");
        await experience.UserTurnAsync(turn, TestContext.Current.CancellationToken);
        var context = await experience.SupplyAsync(turn, TestContext.Current.CancellationToken);
        Assert.Contains("fictional", context, StringComparison.Ordinal);
        Assert.Contains("blue coat", context, StringComparison.Ordinal);
        var snapshot = await experience.SnapshotAsync(TestContext.Current.CancellationToken);
        var prompt = CompanionWorld.PhotoPrompt("selfie", p, snapshot.Moment, null);
        Assert.Contains("blue coat", prompt, StringComparison.Ordinal);
        Assert.Contains("silver hair, green eyes", prompt, StringComparison.Ordinal);
        Assert.Contains("Weather is unknown", prompt, StringComparison.Ordinal);
        p = p with { Enabled = false };
        Assert.Null(await experience.SupplyAsync(turn, TestContext.Current.CancellationToken));
    }

    [Fact]
    public void Unsupported_media_and_songs_without_permission_are_rejected_and_unknown_songs_are_not_claimed()
    {
        Assert.Throws<ArgumentException>(() => CompanionMedia.Validate(new("bad", "sticker", "x", "data:image/svg+xml;base64,PHN2Zy8+")));
        Assert.Throws<ArgumentException>(() => CompanionMedia.Validate(new("bad", "song", "x", "data:audio/wav;base64,UklGRg==")));
        var song = new CompanionAsset("song", "song", "自己的小曲", "data:audio/wav;base64,UklGRg==", Attribution: "my own voice and composition");
        CompanionMedia.Validate(song);
        Assert.Equal(song, CompanionMedia.Song([song], "自己的小曲"));
        Assert.Null(CompanionMedia.Song([song], "没有学过的歌"));
        Assert.Contains("没有可播放的录音", CompanionMedia.SongReply(null), StringComparison.Ordinal);
    }

    [Fact]
    public void Natural_pacing_preserves_graphemes_and_limits_total_artificial_wait()
    {
        var text = string.Concat(Enumerable.Repeat("👩🏽‍💻今天也很开心。e\u0301", 300));
        var parts = CompanionPacing.Plan(text, true);
        Assert.Equal(text, string.Concat(parts.Select(p => p.Text)));
        Assert.True(parts.Sum(p => p.Delay.TotalSeconds) <= 15.001);
        Assert.DoesNotContain(parts, p => char.IsLowSurrogate(p.Text[0]) || char.IsHighSurrogate(p.Text[^1]));
        Assert.Equal(TimeSpan.Zero, Assert.Single(CompanionPacing.Plan(text, false)).Delay);
        Assert.Equal("sad", CompanionMedia.Emotion("难过"));
        Assert.Equal("winter", CompanionMedia.Season("冬天"));
    }

    [Fact]
    public async Task A_corrupt_optional_notebook_is_reported_without_being_overwritten_or_blocking_context()
    {
        var store = new InMemoryKeyValueStore();
        await store.SetAsync("aijade.companion.owner", "{broken");
        using var notebook = new CompanionNotebook(store, "owner");
        using var http = new HttpClient();
        var experience = new CompanionExperience(notebook, () => new(), new(http), "owner");
        var context = await experience.SupplyAsync(new("chat", null, [], "hello"), TestContext.Current.CancellationToken);
        Assert.Contains("unavailable", context, StringComparison.Ordinal);
        Assert.Equal("{broken", await store.GetAsync("aijade.companion.owner"));
    }

    private sealed class NapCat : HttpMessageHandler
    {
        public List<JsonNode> Sent { get; } = [];
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Sent.Add(JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!);
            return new(HttpStatusCode.OK) { Content = new StringContent("""{"status":"ok","retcode":0,"data":{"message_id":1}}""", Encoding.UTF8, "application/json") };
        }
    }

    [Fact]
    public async Task QQ_replies_deliver_actual_image_and_audio_segments_and_reject_other_recipients()
    {
        var transport = new NapCat();
        using var http = new HttpClient(transport);
        var connector = new OneBotConnector(8795, new("http://127.0.0.1:3000"), "token-01234567890", "secret-01234567890", "12345", http);
        await connector.SendReplyAsync(new ChannelReply("给你听", []) { Attachments = [new("image", Picture), new("record", "data:audio/wav;base64,UklGRg==")] }, 0, TestContext.Current.CancellationToken);
        Assert.Equal(["text", "image", "record"], transport.Sent.Select(n => n["message"]![0]!["type"]!.GetValue<string>()));
        Assert.StartsWith("base64://", transport.Sent[1]["message"]![0]!["data"]!["file"]!.GetValue<string>(), StringComparison.Ordinal);
        Assert.All(transport.Sent, n => Assert.Equal(12345, n["user_id"]!.GetValue<long>()));
        await Assert.ThrowsAsync<InvalidOperationException>(() => connector.SendAsync("9999", "no", TestContext.Current.CancellationToken));
    }
}
