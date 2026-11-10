using System.Net;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;

namespace Aijade.Tests;

public sealed class ProductPolicyQualificationTests
{
    private sealed class MemoryFixture : HttpMessageHandler
    {
        public List<int> Limits { get; } = [];
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            var query = global::System.Web.HttpUtility.ParseQueryString(request.RequestUri!.Query);
            var limit = int.Parse(query["limit"]!, global::System.Globalization.CultureInfo.InvariantCulture);
            Limits.Add(limit);
            var items = new JsonArray();
            // Similarity order is the reverse of recency. The oldest item beyond the narrow response is never inferred visible.
            for (var i = 0; i < Math.Min(limit, 10); i++)
                items.Add(new JsonObject
                {
                    ["id"] = $"source-{i}", ["sessionId"] = "fixture", ["source"] = "chat", ["content"] = $"evidence-{i}",
                    ["createdAt"] = new DateTimeOffset(2026, 1, 1, 0, 0, 0, TimeSpan.Zero).AddDays(i), ["memoryVersions"] = 1,
                });
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(new JsonObject { ["items"] = items }.ToJsonString(), Encoding.UTF8, "application/json"),
            });
        }
    }

    [Theory]
    [InlineData(6, true, "evidence-5", "evidence-1")]
    [InlineData(6, false, "evidence-0", "evidence-4")]
    [InlineData(60, true, "evidence-9", "evidence-5")]
    [InlineData(60, false, "evidence-0", "evidence-4")]
    public async Task Response_budget_and_order_are_separate_policies(int limit, bool newest, string first, string last)
    {
        var ct = TestContext.Current.CancellationToken;
        using var handler = new MemoryFixture();
        using var http = new HttpClient(handler) { BaseAddress = new Uri("http://fixture/") };
        var api = new AijadeApi(http, new MemoryTokenStore());
        var provider = new PolicyMemoryContext(api, limit, newest);
        var turn = new TurnContext("fixture", null, [], "question");
        var result = await provider.SupplyAsync(turn, ct);
        Assert.NotNull(result);
        var lines = result.Split('\n');
        Assert.Equal("- " + first, lines[1]);
        Assert.Equal("- " + last, lines[^1]);
        Assert.Single(handler.Limits);
        Assert.Equal(limit, handler.Limits[0]);
    }

    [Fact]
    public async Task Baseline_adapter_matches_production_on_same_responses()
    {
        var ct = TestContext.Current.CancellationToken;
        using var handler = new MemoryFixture();
        using var http = new HttpClient(handler) { BaseAddress = new Uri("http://fixture/") };
        var api = new AijadeApi(http, new MemoryTokenStore());
        var turn = new TurnContext("fixture", null, [], "question");
        Assert.Equal(await new MemoryRecallProvider(api, () => true).SupplyAsync(turn, ct),
            await new PolicyMemoryContext(api, 6, true).SupplyAsync(turn, ct));
    }
}
