using System.Net;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Companion;
using Aijade.Client.Settings;
using Aijade.Server.Product;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

public sealed class CompanionConfigurationTests
{
    private sealed class LocalService : HttpMessageHandler
    {
        public List<(Uri Url, HttpMethod Method, JsonObject Body)> Requests { get; } = [];
        public bool BadAudio { get; set; }
        public static byte[] Wave(int samples)
        {
            var b = new byte[44 + samples * 2];
            "RIFF"u8.CopyTo(b); BitConverter.GetBytes(b.Length - 8).CopyTo(b, 4); "WAVEfmt "u8.CopyTo(b.AsSpan(8));
            BitConverter.GetBytes(16).CopyTo(b, 16); BitConverter.GetBytes((short)1).CopyTo(b, 20); BitConverter.GetBytes((short)1).CopyTo(b, 22);
            BitConverter.GetBytes(8000).CopyTo(b, 24); BitConverter.GetBytes(16000).CopyTo(b, 28); BitConverter.GetBytes((short)2).CopyTo(b, 32);
            BitConverter.GetBytes((short)16).CopyTo(b, 34); "data"u8.CopyTo(b.AsSpan(36)); BitConverter.GetBytes(samples * 2).CopyTo(b, 40);
            return b;
        }
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var body = request.Content is null ? new JsonObject() : JsonNode.Parse(await request.Content.ReadAsStringAsync(cancellationToken))!.AsObject();
            Requests.Add((request.RequestUri!, request.Method, body));
            if (request.Method == HttpMethod.Get)
                return new(HttpStatusCode.OK) { Content = new StringContent("ready") };
            if (body["song"]?.GetValue<string>() == "unknown")
                return new(HttpStatusCode.NotFound);
            return new(HttpStatusCode.OK) { Content = new ByteArrayContent(BadAudio ? "not audio"u8.ToArray() : Wave(request.RequestUri!.Host == "first.local" ? 16 : 32)) };
        }
    }

    private static async Task<AijadeApi> ApiAsync(ServerTestHost host)
    {
        var tokens = new MemoryTokenStore(); await tokens.SetAsync(ServerTestHost.Token);
        return new(host.Client, tokens);
    }

    [Fact]
    public async Task Location_can_be_left_empty_changed_and_restored_without_an_online_lookup()
    {
        new CompanionProfile().ValidateLocation();
        var store = new InMemoryKeyValueStore();
        var settings = new SettingsService(store);
        var next = new CompanionProfile { City = "My city", TimeZone = "Asia/Seoul", Latitude = 37.566, Longitude = 126.9784, Weather = true };
        next.ValidateLocation();
        await settings.SaveAsync(new() { Companion = next });
        Assert.Equal(next, (await new SettingsService(store).LoadAsync()).Companion);
        var cleared = next with { City = "", TimeZone = "", Latitude = null, Longitude = null, Weather = false };
        cleared.ValidateLocation(); await settings.UpdateAsync(s => s with { Companion = cleared });
        Assert.Equal(cleared, (await new SettingsService(store).LoadAsync()).Companion);
    }

    [Theory]
    [InlineData(91d, 0d)]
    [InlineData(0d, 181d)]
    [InlineData(double.NaN, 0d)]
    [InlineData(10d, null)]
    public void Invalid_or_half_locations_are_rejected(double latitude, double? longitude) =>
        Assert.Throws<ArgumentException>(() => new CompanionProfile { Latitude = latitude, Longitude = longitude }.ValidateLocation());

    [Fact]
    public async Task Local_service_forms_preserve_other_routes_and_saved_keys_and_require_an_admin()
    {
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var routes = new JsonObject { ["models"] = new JsonObject { ["chat"] = new JsonObject { ["upstream"] = "https://example.test/v1", ["keys"] = new JsonArray("fixture-chat-key-1234") } } };
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", routes, ServerTestHost.AdminToken)).Status);
        var patch = new JsonObject { ["singing"] = new JsonObject { ["enabled"] = false, ["upstream"] = "", ["modelPath"] = "/not-loaded/model", ["datasetPath"] = "/not-opened/samples" } };
        Assert.Equal(403, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/local-services", patch, ServerTestHost.Token)).Status);
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/local-services", patch, ServerTestHost.AdminToken)).Status);
        var (_, saved) = await host.SendAsync(HttpMethod.Get, "/api/v1/admin/gateway/routes", token: ServerTestHost.AdminToken);
        Assert.Equal("https://example.test/v1", saved!["models"]!["chat"]!["upstream"]!.GetValue<string>());
        Assert.Equal("…1234", saved["models"]!["chat"]!["keys"]![0]!.GetValue<string>());
        Assert.Equal("/not-loaded/model", saved["singing"]!["modelPath"]!.GetValue<string>());
        var api = await ApiAsync(host);
        Assert.Equal("GATEWAY_UNCONFIGURED", (await Assert.ThrowsAsync<AijadeApiException>(() => api.SingAsync("song", TestContext.Current.CancellationToken))).Code);
    }

    [Fact]
    public async Task Connection_check_only_reads_health_and_does_not_claim_a_trained_voice()
    {
        var service = new LocalService();
        await using var host = await ServerTestHost.StartAsync(worker: false, services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => service));
        var input = new JsonObject { ["upstream"] = "http://first.local", ["healthPath"] = "/health" };
        Assert.Equal(403, (await host.SendAsync(HttpMethod.Post, "/api/v1/admin/gateway/local-services/check", input, ServerTestHost.Token)).Status);
        Assert.Empty(service.Requests);
        var (status, result) = await host.SendAsync(HttpMethod.Post, "/api/v1/admin/gateway/local-services/check", input, ServerTestHost.AdminToken);
        Assert.Equal(200, status); Assert.Equal("reachable", result!["status"]!.GetValue<string>());
        Assert.False(result["trainingVerified"]!.GetValue<bool>());
        Assert.Equal(HttpMethod.Get, Assert.Single(service.Requests).Method);
        Assert.Equal("/health", service.Requests[0].Url.AbsolutePath);
    }

    [Fact]
    public async Task Singing_uses_new_settings_without_a_restart_and_returns_actual_audio_or_an_explicit_failure()
    {
        var ct = TestContext.Current.CancellationToken;
        var service = new LocalService();
        await using var host = await ServerTestHost.StartAsync(worker: false, services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => service));
        var api = await ApiAsync(host);
        async Task SaveAsync(string upstream, string voice, bool enabled = true)
        {
            var patch = new JsonObject { ["singing"] = new JsonObject { ["enabled"] = enabled, ["upstream"] = upstream, ["voice"] = voice, ["modelPath"] = "/only-a-note" } };
            Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/local-services", patch, ServerTestHost.AdminToken)).Status);
        }
        await SaveAsync("http://first.local", "A");
        Assert.Equal(LocalService.Wave(16), await api.SingAsync("tune", ct));
        await SaveAsync("http://second.local", "B");
        Assert.Equal(LocalService.Wave(32), await api.SingAsync("tune", ct));
        Assert.Equal("B", service.Requests[^1].Body["voice"]!.GetValue<string>());
        Assert.Equal(["song", "voice"], service.Requests[^1].Body.Select(p => p.Key).Order(StringComparer.Ordinal));
        Assert.Equal("SONG_UNAVAILABLE", (await Assert.ThrowsAsync<AijadeApiException>(() => api.SingAsync("unknown", ct))).Code);
        service.BadAudio = true;
        Assert.Equal("INVALID_SINGING_AUDIO", (await Assert.ThrowsAsync<AijadeApiException>(() => api.SingAsync("tune", ct))).Code);
        await SaveAsync("http://second.local", "B", false);
        var count = service.Requests.Count;
        Assert.Equal("GATEWAY_UNCONFIGURED", (await Assert.ThrowsAsync<AijadeApiException>(() => api.SingAsync("tune", ct))).Code);
        Assert.Equal(count, service.Requests.Count);
    }
}
