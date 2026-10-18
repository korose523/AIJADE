using System.Text.Json.Nodes;

using Aijade.Research.RqC;
using Aijade.Research.SkillBench;

namespace Aijade.Tests;

public class FormatPrecheckTests
{
    [Fact]
    public void The_precheck_tasks_are_outside_the_bench_and_their_candidates_are_labelled_correctly()
    {
        var bench = Bench.Tasks.Select(t => t.Id).ToHashSet(StringComparer.Ordinal);
        var sandbox = new Sandbox();
        Assert.Equal(5, FormatPrecheck.Items.Count);
        Assert.Equal(3, FormatPrecheck.Items.Count(i => i.Correct));
        foreach (var (task, code, correct) in FormatPrecheck.Items)
        {
            Assert.DoesNotContain(task.Id, bench);
            Assert.Equal(correct, sandbox.RunTask(code, task).Ok);
        }
    }

    /// <summary>Answers every chat request with the next reply in turn (the first request is the warm-up).</summary>
    private sealed class ScriptedOllama(params string[] replies) : HttpMessageHandler
    {
        private int next;

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var reply = replies[Math.Min(next++, replies.Length - 1)];
            if (reply == "ABORT")
                return Task.FromResult(new HttpResponseMessage(System.Net.HttpStatusCode.InternalServerError) { Content = new StringContent("{\"error\":\"token repeat limit reached\"}") });
            return Task.FromResult(new HttpResponseMessage(System.Net.HttpStatusCode.OK)
            {
                Content = new StringContent(new JsonObject { ["message"] = new JsonObject { ["content"] = reply }, ["done_reason"] = "stop" }.ToJsonString()),
            });
        }
    }

    [Fact]
    public async Task A_model_passes_only_when_every_reply_begins_with_PASS_or_FAIL()
    {
        var ct = TestContext.Current.CancellationToken;
        async Task<JsonObject> Run(params string[] replies)
        {
            using var http = new HttpClient(new ScriptedOllama(replies));
            return FormatPrecheck.Report(await FormatPrecheck.RunAsync(new OllamaBackend(http, "m", "http://fake", seed: 1, maxReplyTokens: 4096), ct));
        }

        var good = await Run("READY", "PASS fine", "FAIL returns the first element", "PASS", "fail: lowercase", "Pass.");
        Assert.True(good["pass"]!.GetValue<bool>());
        Assert.Equal(5, good["conforming"]!.GetValue<int>());

        var listing = await Run("READY", "PASS", "* Case 0: PASS\nOverall verdict: PASS", "FAIL", "PASS", "PASS");
        Assert.False(listing["pass"]!.GetValue<bool>());
        Assert.Equal(4, listing["conforming"]!.GetValue<int>());

        // an aborted reply is recorded as "FAIL [...]" by the backend but does not count as following the format
        var aborted = await Run("READY", "PASS", "ABORT", "FAIL", "PASS", "PASS");
        Assert.False(aborted["pass"]!.GetValue<bool>());
        Assert.True(aborted["replies"]!.AsArray()[1]!["aborted"]!.GetValue<bool>());
    }
}
