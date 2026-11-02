using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Chat;
using Aijade.Server.Product;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

/// <summary>
/// The gateway's local voice (ADR-003, migration batch 1): speech and recognition through the loopback services of the author's
/// MOSAIC project, in the request formats of its tools/tts_neural.py and tools/asr_server.py (r601).
/// </summary>
public class LocalVoiceTests
{
    private static readonly string Root = RqcReanalysisTests.RepoRoot();

    /// <summary>A stand-in for the local services (or another upstream) that records each JSON request.</summary>
    private sealed class FakeService(Func<string, JsonObject, HttpResponseMessage> respond) : HttpMessageHandler
    {
        public List<(string Path, JsonObject Body)> Requests { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var body = (JsonObject)JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!;
            lock (Requests)
                Requests.Add((request.RequestUri!.AbsolutePath, body));
            return respond(request.RequestUri!.AbsolutePath, body);
        }
    }

    /// <summary>A silent 16 kHz mono 16-bit WAV of the given number of samples.</summary>
    private static byte[] Wav(int samples)
    {
        var bytes = new byte[44 + samples * 2];
        Encoding.ASCII.GetBytes("RIFF").CopyTo(bytes, 0);
        BitConverter.GetBytes(36 + samples * 2).CopyTo(bytes, 4);
        Encoding.ASCII.GetBytes("WAVEfmt ").CopyTo(bytes, 8);
        BitConverter.GetBytes(16).CopyTo(bytes, 16);
        BitConverter.GetBytes((short)1).CopyTo(bytes, 20);
        BitConverter.GetBytes((short)1).CopyTo(bytes, 22);
        BitConverter.GetBytes(16000).CopyTo(bytes, 24);
        BitConverter.GetBytes(32000).CopyTo(bytes, 28);
        BitConverter.GetBytes((short)2).CopyTo(bytes, 32);
        BitConverter.GetBytes((short)16).CopyTo(bytes, 34);
        Encoding.ASCII.GetBytes("data").CopyTo(bytes, 36);
        BitConverter.GetBytes(samples * 2).CopyTo(bytes, 40);
        return bytes;
    }

    private static HttpResponseMessage Json(HttpStatusCode code, string json) => new(code) { Content = new StringContent(json, Encoding.UTF8, "application/json") };

    private static async Task<HttpResponseMessage> SpeakAsync(ServerTestHost host, string json, CancellationToken ct)
    {
        using var req = new HttpRequestMessage(HttpMethod.Post, "/api/v1/openai/v1/audio/speech") { Content = new StringContent(json, Encoding.UTF8, "application/json") };
        req.Headers.Authorization = new("Bearer", ServerTestHost.Token);
        return await host.Client.SendAsync(req, ct);
    }

    private static async Task<HttpResponseMessage> TranscribeAsync(ServerTestHost host, byte[] audio, string mime, string? language, CancellationToken ct)
    {
        using var form = new MultipartFormDataContent();
        var file = new ByteArrayContent(audio);
        file.Headers.ContentType = new(mime);
        form.Add(file, "file", mime == "audio/wav" ? "speech.wav" : "speech.webm");
        if (language is not null)
            form.Add(new StringContent(language), "language");
        using var req = new HttpRequestMessage(HttpMethod.Post, "/api/v1/openai/v1/audio/transcriptions") { Content = form };
        req.Headers.Authorization = new("Bearer", ServerTestHost.Token);
        return await host.Client.SendAsync(req, ct);
    }

    [Fact]
    public void The_emotions_are_the_contract_mapping_of_the_stage_expressions()
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "configs", "companion", "contract.json")));
        var expressions = doc.RootElement.GetProperty("expressions");
        var contract = expressions.GetProperty("aijadeToMosaic").EnumerateObject().ToDictionary(p => p.Name, p => p.Value.GetString()!, StringComparer.Ordinal);
        Assert.Equal(contract.OrderBy(p => p.Key, StringComparer.Ordinal), LocalVoice.Emotions.OrderBy(p => p.Key, StringComparer.Ordinal));
        Assert.Equal(Expressions.Table.Keys.Order(StringComparer.Ordinal), LocalVoice.Emotions.Keys.Order(StringComparer.Ordinal));
        var mosaic = expressions.GetProperty("mosaic").GetProperty("emotions").EnumerateArray().Select(e => e.GetString()).ToHashSet();
        Assert.All(LocalVoice.Emotions.Values, e => Assert.Contains(e, mosaic));
        Assert.Equal("neutral", LocalVoice.Emotion(null));
        Assert.Equal("neutral", LocalVoice.Emotion("no-such-expression"));
    }

    [Theory]
    [InlineData("zh-CN", "Chinese")]
    [InlineData("zh", "Chinese")]
    [InlineData("zh-TW", "Chinese")]
    [InlineData("zh-HK", "Cantonese")]
    [InlineData("yue", "Cantonese")]
    [InlineData("en-US", "English")]
    [InlineData("ja-JP", "Japanese")]
    [InlineData("ko", "Korean")]
    [InlineData("fr-FR", "auto")]
    [InlineData("", "auto")]
    [InlineData(null, "auto")]
    public void A_language_tag_becomes_one_of_the_recognizer_names(string? tag, string expected) => Assert.Equal(expected, LocalVoice.Language(tag));

    [Fact]
    public async Task Speech_and_recognition_go_to_the_local_services_in_their_own_formats()
    {
        var ct = TestContext.Current.CancellationToken;
        var spoken = Wav(800);
        var service = new FakeService((path, body) => path switch
        {
            "/tts" when body["text"]!.GetValue<string>() == "……" => Json(HttpStatusCode.BadRequest, "{\"error\":\"nothing to say aloud (only asides or symbols)\"}"),
            "/tts" => new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(spoken) { Headers = { ContentType = new("audio/wav") } } },
            "/transcribe" => Json(HttpStatusCode.OK, "{\"text\":\"你好\",\"language\":\"Chinese\",\"audio_s\":0.1}"),
            _ => new HttpResponseMessage(HttpStatusCode.NotFound),
        });
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => service));
        var routes = new JsonObject
        {
            ["speech"] = new JsonObject { ["upstream"] = "http://127.0.0.1:8791", ["kind"] = LocalVoice.Kind },
            ["transcription"] = new JsonObject { ["upstream"] = "http://127.0.0.1:8793", ["kind"] = LocalVoice.Kind },
        };
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", routes, ServerTestHost.AdminToken)).Status);

        // Speech: exactly text and emotion, the stage expression mapped through the contract; the WAV comes back unchanged.
        using (var res = await SpeakAsync(host, "{\"input\":\"你好呀\",\"voice\":\"alloy\",\"emotion\":\"joy\"}", ct))
        {
            Assert.Equal(HttpStatusCode.OK, res.StatusCode);
            Assert.Equal("audio/wav", res.Content.Headers.ContentType!.MediaType);
            Assert.Equal(spoken, await res.Content.ReadAsByteArrayAsync(ct));
        }
        var (path, body) = service.Requests[^1];
        Assert.Equal("/tts", path);
        Assert.Equal(["emotion", "text"], body.Select(p => p.Key).Order(StringComparer.Ordinal));
        Assert.Equal("你好呀", body["text"]!.GetValue<string>());
        Assert.Equal("happy", body["emotion"]!.GetValue<string>());
        foreach (var json in new[] { "{\"input\":\"嗯\",\"emotion\":\"sad\"}", "{\"input\":\"嗯\"}" })
        {
            using var res = await SpeakAsync(host, json, ct);
            Assert.Equal(HttpStatusCode.OK, res.StatusCode);
            Assert.Equal("neutral", service.Requests[^1].Body["emotion"]!.GetValue<string>());
        }
        // The service's refusal is a 400 that carries its reason; a text over its limit is refused without calling it.
        using (var res = await SpeakAsync(host, "{\"input\":\"……\"}", ct))
        {
            Assert.Equal(HttpStatusCode.BadRequest, res.StatusCode);
            Assert.Contains("nothing to say aloud", await res.Content.ReadAsStringAsync(ct), StringComparison.Ordinal);
        }
        var calls = service.Requests.Count;
        using (var res = await SpeakAsync(host, new JsonObject { ["input"] = new string('啊', LocalVoice.MaxChars + 1) }.ToJsonString(), ct))
            Assert.Equal(HttpStatusCode.BadRequest, res.StatusCode);
        Assert.Equal(calls, service.Requests.Count);

        // Recognition: the WAV as base64 with the recognizer's name for the language.
        var heard = Wav(1600);
        using (var res = await TranscribeAsync(host, heard, "audio/wav", "zh-CN", ct))
        {
            Assert.Equal(HttpStatusCode.OK, res.StatusCode);
            Assert.Equal("你好", JsonNode.Parse(await res.Content.ReadAsStringAsync(ct))!["text"]!.GetValue<string>());
        }
        (path, body) = service.Requests[^1];
        Assert.Equal("/transcribe", path);
        Assert.Equal(["language", "wav_b64"], body.Select(p => p.Key).Order(StringComparer.Ordinal));
        Assert.Equal(heard, Convert.FromBase64String(body["wav_b64"]!.GetValue<string>()));
        Assert.Equal("Chinese", body["language"]!.GetValue<string>());
        using (var res = await TranscribeAsync(host, heard, "audio/wav", null, ct))
            Assert.Equal(HttpStatusCode.OK, res.StatusCode);
        Assert.Equal("auto", service.Requests[^1].Body["language"]!.GetValue<string>());
        // Anything but a WAV is refused before the service is called.
        calls = service.Requests.Count;
        using (var res = await TranscribeAsync(host, [0x1a, 0x45, 0xdf, 0xa3, 1, 2, 3, 4, 5, 6, 7, 8], "audio/webm", "zh-CN", ct))
            Assert.Equal(HttpStatusCode.BadRequest, res.StatusCode);
        Assert.Equal(calls, service.Requests.Count);
    }

    [Fact]
    public async Task A_spoken_reply_is_timed_by_the_local_aligner_in_its_own_format()
    {
        var ct = TestContext.Current.CancellationToken;
        var service = new FakeService((path, body) => path switch
        {
            "/align" when body["text"]!.GetValue<string>() == "……" => Json(HttpStatusCode.BadRequest, "{\"error\":\"text of 1-2000 characters required\"}"),
            "/align" => Json(HttpStatusCode.OK, "{\"engine\":\"fake\",\"duration_s\":0.5,\"characters\":[" +
                "{\"char\":\"你\",\"start_s\":0.0,\"end_s\":0.25,\"initial\":\"n\",\"final\":\"i\"}," +
                "{\"char\":\"好\",\"start_s\":0.25,\"end_s\":0.5,\"initial\":\"h\",\"final\":\"ao\"}," +
                "{\"char\":\"呀\",\"start_s\":null,\"end_s\":0.5,\"initial\":\"\",\"final\":\"ia\"}]}"),
            _ => new HttpResponseMessage(HttpStatusCode.NotFound),
        });
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => service));
        var tokens = new Aijade.Client.Api.MemoryTokenStore();
        await tokens.SetAsync(ServerTestHost.Token);
        var api = new Aijade.Client.Api.AijadeApi(host.Client, tokens);
        Assert.False((await api.CapabilitiesAsync(ct)).Alignment);
        var unconfigured = await Assert.ThrowsAsync<Aijade.Client.Api.AijadeApiException>(() => api.AlignAsync("你好", Wav(8000), ct));
        Assert.Equal(503, unconfigured.Status);

        // Only the local aligner times a reply: no other provider has this service.
        var routes = new JsonObject { ["alignment"] = new JsonObject { ["upstream"] = "https://aligner.example/v1", ["kind"] = "openai" } };
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", routes, ServerTestHost.AdminToken)).Status);
        Assert.Equal(503, (await Assert.ThrowsAsync<Aijade.Client.Api.AijadeApiException>(() => api.AlignAsync("你好", Wav(8000), ct))).Status);
        Assert.Empty(service.Requests);
        routes = new JsonObject { ["alignment"] = new JsonObject { ["upstream"] = "http://127.0.0.1:8792", ["kind"] = LocalVoice.Kind } };
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", routes, ServerTestHost.AdminToken)).Status);
        Assert.True((await api.CapabilitiesAsync(ct)).Alignment);

        // Exactly text and the WAV as base64; the rows come back in AIJADE's names, a row without a time left out.
        var audio = Wav(8000);
        var aligned = await api.AlignAsync("你好呀", audio, ct);
        var (path, body) = Assert.Single(service.Requests);
        Assert.Equal("/align", path);
        Assert.Equal(["text", "wav_b64"], body.Select(p => p.Key).Order(StringComparer.Ordinal));
        Assert.Equal("你好呀", body["text"]!.GetValue<string>());
        Assert.Equal(audio, Convert.FromBase64String(body["wav_b64"]!.GetValue<string>()));
        Assert.Equal(0.5, aligned.DurationS);
        Assert.Equal([new Aijade.Client.Companion.AlignedCharacter("你", 0, .25, "n", "i"), new Aijade.Client.Companion.AlignedCharacter("好", .25, .5, "h", "ao")], aligned.Characters);
        Assert.Equal(30, Aijade.Client.Companion.LipSync.Plan(aligned).Vowels.Count);

        // The service's refusal carries its reason; anything but a WAV is refused before the service is called.
        var refused = await Assert.ThrowsAsync<Aijade.Client.Api.AijadeApiException>(() => api.AlignAsync("……", audio, ct));
        Assert.Equal(400, refused.Status);
        Assert.Contains("text of 1-2000 characters required", refused.Message, StringComparison.Ordinal);
        var calls = service.Requests.Count;
        Assert.Equal(400, (await Assert.ThrowsAsync<Aijade.Client.Api.AijadeApiException>(() => api.AlignAsync("你好", [0x1a, 0x45, 0xdf, 0xa3, 1, 2, 3, 4, 5, 6, 7, 8], ct))).Status);
        Assert.Equal(400, (await Assert.ThrowsAsync<Aijade.Client.Api.AijadeApiException>(() => api.AlignAsync(new string('啊', LocalVoice.MaxChars + 1), audio, ct))).Status);
        Assert.Equal(calls, service.Requests.Count);
    }

    [Fact]
    public async Task Other_speech_providers_are_not_given_the_emotion()
    {
        var ct = TestContext.Current.CancellationToken;
        var upstream = new FakeService((_, _) => new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent([1, 2, 3]) { Headers = { ContentType = new("audio/mpeg") } } });
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => upstream));
        var routes = new JsonObject { ["speech"] = new JsonObject { ["upstream"] = "https://tts.example/v1", ["model"] = "tts-1", ["keys"] = new JsonArray("sk-x") } };
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", routes, ServerTestHost.AdminToken)).Status);
        using (var res = await SpeakAsync(host, "{\"input\":\"hello\",\"voice\":\"alloy\",\"emotion\":\"joy\"}", ct))
            Assert.Equal(HttpStatusCode.OK, res.StatusCode);
        var (path, body) = upstream.Requests[^1];
        Assert.EndsWith("/audio/speech", path, StringComparison.Ordinal);
        Assert.False(body.ContainsKey("emotion"));
        Assert.Equal("hello", body["input"]!.GetValue<string>());
    }
}
