using System.Text.Json.Nodes;

using Aijade.Learning.Forge;
using Aijade.Providers.Llm;

using Meai = Microsoft.Extensions.AI;

namespace Aijade.Tests;

public class MeaiAdapterTests
{
    private sealed class EchoChat : IChatClient
    {
        public List<(IReadOnlyList<ChatMessage> Messages, ChatRequestOptions? Options)> Calls { get; } = [];

        public string Model => "echo-1";

        public Task<ChatCompletion> CompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default)
        {
            Calls.Add((messages, options));
            var reply = messages[^1].Content.Contains("teachable", StringComparison.OrdinalIgnoreCase) || messages[^1].Content.Contains("reusable", StringComparison.OrdinalIgnoreCase)
                ? """{"shouldCreate":false,"rationale":"chit-chat"}"""
                : $"echo: {messages[^1].Content}";
            return Task.FromResult(new ChatCompletion("r1", Model, reply, "stop", new TokenUsage(3, 4, 7), null));
        }

        public async Task<JsonNode?> JsonCompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default) =>
            ChatParsing.ParseJsonContent((await CompleteAsync(messages, options, cancellationToken)).Text);
    }

    [Fact]
    public async Task Aijade_and_Microsoft_Extensions_AI_clients_wrap_each_other_without_losing_roles_options_or_usage()
    {
        var ct = TestContext.Current.CancellationToken;
        var echo = new EchoChat();
        using var meai = new AijadeChatClientAsMeai(echo);
        Assert.Equal("echo-1", ((Meai.ChatClientMetadata)meai.GetService(typeof(Meai.ChatClientMetadata))!).DefaultModelId);
        Assert.Same(echo, meai.GetService(typeof(EchoChat)));

        var response = await meai.GetResponseAsync(
            [new Meai.ChatMessage(Meai.ChatRole.System, "be brief"), new Meai.ChatMessage(Meai.ChatRole.User, "hello") { AuthorName = "u1" }],
            new Meai.ChatOptions { Temperature = 0.25f, MaxOutputTokens = 64, StopSequences = ["END"] }, ct);
        Assert.Equal("echo: hello", response.Text);
        Assert.Equal((3L, 4L, 7L), (response.Usage!.InputTokenCount, response.Usage.OutputTokenCount, response.Usage.TotalTokenCount));
        Assert.Equal("stop", response.FinishReason!.Value.Value);
        var (sent, options) = echo.Calls[^1];
        Assert.Equal([ChatRole.System, ChatRole.User], sent.Select(m => m.Role));
        Assert.Equal("u1", sent[1].Name);
        Assert.Equal((0.25, 64, "END"), (options!.Temperature!.Value, options.MaxTokens!.Value, options.Stop![0]));

        var updates = new List<Meai.ChatResponseUpdate>();
        await foreach (var u in meai.GetStreamingResponseAsync([new Meai.ChatMessage(Meai.ChatRole.User, "stream")], cancellationToken: ct))
            updates.Add(u);
        Assert.Equal("echo: stream", string.Concat(updates.Select(u => u.Text)));

        // And back: a Microsoft.Extensions.AI client drives AIJADE's learning components.
        var back = new MeaiChatClient(meai);
        Assert.Equal("echo-1", back.Model);
        var completion = await back.CompleteAsync([new ChatMessage(ChatRole.User, "again")], new ChatRequestOptions(MaxTokens: 10), ct);
        Assert.Equal(("echo: again", 7.0), (completion.Text, completion.Usage!.TotalTokens));
        Assert.Null(await new SkillForge(back).DetectTeachableMomentAsync([new ChatMessage(ChatRole.User, "hi"), new ChatMessage(ChatRole.Assistant, "hello")], ct));
    }
}
