using System.Net;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Server.Product;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

public sealed class StrictJsonReplyTests
{
    private const string PriorRequest = "仅输出这一行有效的 JSON：{\"total\":5}";

    [Theory]
    [InlineData(PriorRequest, true)]
    [InlineData("请只返回 JSON 数组：[1,2]", true)]
    [InlineData(" /json a Boolean indicating whether 2 is prime", true)]
    [InlineData("Please return only valid JSON.", true)]
    [InlineData("Output JSON only: return the total.", true)]
    [InlineData("JSON 是什么？", false)]
    [InlineData("解释为什么模型常说‘仅输出 JSON’", false)]
    [InlineData("What does JSON only mean?", false)]
    [InlineData("请只输出 JSONL", false)]
    [InlineData("/jsonize this conversation", false)]
    public void Only_explicit_JSON_directives_are_recognized(string text, bool expected) => Assert.Equal(expected, StrictJsonReply.IsRequested(text));

    [Theory]
    [InlineData("```json\n{\"total\":5}\n```", "{\"total\":5}")]
    [InlineData("```\r\nfalse\r\n```", "false")]
    [InlineData(" [\"[[emote:joy]]\",null] ", "[\"[[emote:joy]]\",null]")]
    [InlineData("null", "null")]
    public async Task Strict_turn_uses_one_bounded_completion_and_stores_only_the_literal_JSON(string modelOutput, string expected)
    {
        using var host = new ChatTransport(modelOutput);
        var events = await RunAsync(host, jsonOnly: true);
        var reply = Assert.IsType<JsonReplyCompleted>(Assert.Single(events)).Reply;
        Assert.Equal(expected, reply.Content);
        Assert.Equal("json", reply.Meta!["format"]!.GetValue<string>());
        Assert.Equal(PriorRequest, host.Posts[0]["content"]!.GetValue<string>());
        Assert.Equal(expected, host.Posts[1]["content"]!.GetValue<string>());
        Assert.Equal(2, host.Posts.Count);
        var request = Assert.Single(host.Completions);
        Assert.Null(request["stream"]);
        Assert.Equal(2048, request["max_tokens"]!.GetValue<int>());
        Assert.Null(request["tools"]);
        Assert.Contains("exactly one complete JSON value", request["messages"]![0]!["content"]!.GetValue<string>(), StringComparison.Ordinal);
        Assert.DoesNotContain("[[emote:", request["messages"]![0]!["content"]!.GetValue<string>(), StringComparison.Ordinal);
        Assert.Equal("Earlier context", request["messages"]![1]!["content"]!.GetValue<string>());
    }

    [Theory]
    [InlineData("Here is the answer: {\"total\":5}", "stop")]
    [InlineData("{} {}", "stop")]
    [InlineData("{\"total\":5,\"total\":1}", "stop")]
    [InlineData("{\"total\":5}", "length")]
    [InlineData("```json\n{\"total\":5}\n```\nThanks", "stop")]
    [InlineData("```json\n{\"total\":5}", "stop")]
    public async Task Failed_JSON_is_never_published_or_stored_as_an_assistant_reply(string modelOutput, string reason)
    {
        using var host = new ChatTransport(modelOutput, reason);
        var events = await RunAsync(host, jsonOnly: true);
        Assert.Equal("INVALID_JSON_REPLY", Assert.IsType<TurnFailed>(Assert.Single(events)).Code);
        Assert.Equal("user", Assert.Single(host.Posts)["role"]!.GetValue<string>());
        Assert.Single(host.Completions);
    }

    [Fact]
    public async Task Malformed_transport_envelope_or_oversized_body_leaves_only_the_user_message()
    {
        using var malformed = new ChatTransport("", malformedEnvelope: true);
        using var oversized = new ChatTransport(new string(' ', 32_768) + "{}");
        foreach (var host in new[] { malformed, oversized })
        {
            var events = await RunAsync(host, jsonOnly: true);
            Assert.Equal("INVALID_JSON_REPLY", Assert.IsType<TurnFailed>(Assert.Single(events)).Code);
            Assert.Equal("user", Assert.Single(host.Posts)["role"]!.GetValue<string>());
            Assert.Single(host.Completions);
        }
    }

    [Fact]
    public async Task Gateway_translates_malformed_success_envelope_and_the_chat_does_not_store_it()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: services => services.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => new MalformedModel()));
        var configured = await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", JsonNode.Parse("""
            {"models":{"aijade-chat":{"upstream":"https://llm.example/v1","model":"test","keys":["test"],"fluxPer1k":0}}}
            """), ServerTestHost.AdminToken);
        Assert.InRange(configured.Status, 200, 299);
        var tokens = new MemoryTokenStore();
        await tokens.SetAsync(ServerTestHost.Token);
        var api = new AijadeApi(host.Client, tokens);
        var chat = await api.CreateChatAsync(null, "structured output", ct);
        var runtime = CompanionRuntime.Create(api, [], new OrchestratorOptions());
        var events = new List<OrchestratorEvent>();
        await foreach (var e in runtime.SendAsync(chat.Id, null, [], new ChatInput(PriorRequest) { JsonOnly = true }, "snapshot", ct: ct))
            events.Add(e);
        Assert.Equal("INVALID_JSON_REPLY", Assert.IsType<TurnFailed>(Assert.Single(events)).Code);
        Assert.Equal("user", Assert.Single(await api.MessagesAsync(chat.Id, ct: ct)).Role);
    }

    [Fact]
    public async Task Ordinary_JSON_discussion_still_streams_text_and_performance_markers()
    {
        using var host = new ChatTransport("[[emote:joy]]JSON is a data format.");
        var events = await RunAsync(host, jsonOnly: false, request: "What is JSON?");
        Assert.Contains(events, e => e is ExpressionCue { Name: "joy" });
        Assert.Equal("JSON is a data format.", Assert.IsType<TurnCompleted>(events[^1]).Reply.Content);
        Assert.True(Assert.Single(host.Completions)["stream"]!.GetValue<bool>());
    }

    private static async Task<List<OrchestratorEvent>> RunAsync(ChatTransport host, bool jsonOnly, string request = PriorRequest)
    {
        using var http = new HttpClient(host, disposeHandler: false) { BaseAddress = new Uri("http://aijade.test/") };
        var options = new OrchestratorOptions { Tools = () => jsonOnly ? throw new InvalidOperationException("Tool mode was evaluated in a JSON turn.") : false };
        var runtime = CompanionRuntime.Create(new AijadeApi(http, new MemoryTokenStore()), [], options);
        StoredMessage[] history = [new("old", 1, "user", "Earlier context", DateTimeOffset.UnixEpoch)];
        var events = new List<OrchestratorEvent>();
        await foreach (var e in runtime.SendAsync("chat", null, history, new ChatInput(request) { JsonOnly = jsonOnly }, "snapshot",
            ct: TestContext.Current.CancellationToken))
            events.Add(e);
        return events;
    }

    private sealed class ChatTransport(string modelOutput, string reason = "stop", bool malformedEnvelope = false) : HttpMessageHandler
    {
        public List<JsonObject> Posts { get; } = [];
        public List<JsonObject> Completions { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Assert.Equal(HttpMethod.Post, request.Method);
            var body = JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!.AsObject();
            if (request.RequestUri!.AbsolutePath == "/api/v1/chats/chat/messages")
            {
                Posts.Add(body);
                var stored = (JsonObject)body.DeepClone();
                stored["id"] = $"fixture{Posts.Count}";
                stored["seq"] = Posts.Count;
                stored["createdAt"] = "2026-11-18T00:00:00Z";
                return Reply(stored.ToJsonString());
            }
            Assert.Equal("/api/v1/openai/v1/chat/completions", request.RequestUri.AbsolutePath);
            Completions.Add(body);
            if (malformedEnvelope)
                return Reply("{");
            var stream = body["stream"]?.GetValue<bool>() ?? false;
            var response = new JsonObject { ["choices"] = new JsonArray(new JsonObject
            {
                [stream ? "delta" : "message"] = new JsonObject { ["content"] = modelOutput }, ["finish_reason"] = reason,
            }) };
            return stream ? Reply("data: " + response.ToJsonString() + "\n\ndata: [DONE]\n\n", "text/event-stream") : Reply(response.ToJsonString());
        }

        private static HttpResponseMessage Reply(string body, string mediaType = "application/json") =>
            new(HttpStatusCode.OK) { Content = new StringContent(body, Encoding.UTF8, mediaType) };
    }

    private sealed class MalformedModel : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("{", Encoding.UTF8, "application/json") });
    }
}
