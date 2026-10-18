using System.Text.Json.Nodes;

using Aijade.Research.RqC;
using Aijade.Research.SkillBench;

namespace Aijade.Tests;

public class VerifyTemplateTests
{
    private static readonly BenchTask Sample = new("t", "Write a function `f(x)` that doubles x.", BenchCategory.Math, BenchTier.Easy,
        [new BenchCase("[1]", "2"), new BenchCase("[\"a\"]", "null")]);

    [Fact]
    public void Template_B_is_the_registered_wording()
    {
        Assert.Equal(
            "Task: Write a function `f(x)` that doubles x.\n" +
            "A candidate solution:\n" +
            "```js\nfunction f(x){return 2*x}\n```\n" +
            "Test inputs (the expected outputs are not shown):\n" +
            "  1. [1]\n" +
            "  2. [\"a\"]\n" +
            "Question: does the candidate return the correct output for every one of these inputs?\n" +
            "Answer on one line that starts with PASS (it does) or FAIL (it does not), then give a brief justification.",
            Backends.BuildVerifyPromptB(Sample, "function f(x){return 2*x}"));
    }

    /// <summary>Records each request's prompt and answers PASS.</summary>
    private sealed class RecordingOllama : HttpMessageHandler
    {
        public List<string> Prompts { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var body = JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!;
            Prompts.Add(body["messages"]![0]!["content"]!.GetValue<string>());
            return new HttpResponseMessage(System.Net.HttpStatusCode.OK)
            {
                Content = new StringContent(new JsonObject { ["message"] = new JsonObject { ["content"] = "PASS ok" }, ["done_reason"] = "stop" }.ToJsonString()),
            };
        }
    }

    [Fact]
    public async Task The_verifier_sends_template_A_by_default_and_B_when_asked()
    {
        var ct = TestContext.Current.CancellationToken;
        const string code = "function f(x){return 2*x}";
        using var a = new RecordingOllama();
        using (var http = new HttpClient(a))
            await new OllamaBackend(http, "m", "http://fake", seed: 1).VerifyAsync(Sample, code, ct);
        using var b = new RecordingOllama();
        using (var http = new HttpClient(b))
            await new OllamaBackend(http, "m", "http://fake", seed: 1, verifyTemplate: "B").VerifyAsync(Sample, code, ct);
        Assert.Equal(Backends.BuildVerifyPrompt(Sample, code), Assert.Single(a.Prompts));
        Assert.Equal(Backends.BuildVerifyPromptB(Sample, code), Assert.Single(b.Prompts));

        var plain = RqcCliConfig.Parse(["--backend", "ollama", "--model", "m"]);
        var withB = RqcCliConfig.Parse(["--backend", "ollama", "--model", "m", "--verify-template", "B"]);
        Assert.Equal(plain.Fingerprint(), RqcCliConfig.Parse(["--backend", "ollama", "--model", "m", "--verify-template", "A"]).Fingerprint());
        Assert.NotEqual(plain.Fingerprint(), withB.Fingerprint());
        Assert.Equal(plain.RunId, withB.RunId);
        Assert.Throws<ArgumentException>(() => RqcCliConfig.Parse(["--backend", "ollama", "--model", "m", "--verify-template", "C"]));
    }
}
