using System.Net;
using System.Text;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

public sealed class ProductEmbeddingObservationTests
{
    [Fact]
    public async Task A_conversation_observer_remains_usable_across_named_client_creation()
    {
        const string body = """{"data":[{"index":0,"embedding":[1.0,2.0]}]}""";
        var capture = new ProductEmbeddingCapture();
        var upstreams = new List<Upstream>();
        var services = new ServiceCollection();
        services.AddHttpClient("embedding-fixture").ConfigurePrimaryHttpMessageHandler(() =>
            {
                var upstream = new Upstream(HttpStatusCode.OK, body);
                upstreams.Add(upstream);
                return new ProductEmbeddingObservation(upstream, capture);
            })
            .SetHandlerLifetime(TimeSpan.FromSeconds(1));
        using var provider = services.BuildServiceProvider();
        var factory = provider.GetRequiredService<IHttpClientFactory>();
        async Task SendAsync()
        {
            using var client = factory.CreateClient("embedding-fixture");
            using var request = new StringContent("""{"model":"fixture","input":["first"]}""", Encoding.UTF8, "application/json");
            using var response = await client.PostAsync("http://fixture.invalid/embeddings", request, TestContext.Current.CancellationToken);
            Assert.Equal(body, await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        }
        await SendAsync();
        await Task.Delay(TimeSpan.FromMilliseconds(1200), TestContext.Current.CancellationToken);
        await SendAsync();
        GC.Collect();
        GC.WaitForPendingFinalizers();
        await Task.Delay(TimeSpan.FromSeconds(12), TestContext.Current.CancellationToken);
        await SendAsync();
        Assert.Equal(3, upstreams.Sum(u => u.Calls));
        Assert.True(upstreams.Count >= 2); // factory rotation actually occurred; retired handlers are not reused
        Assert.Equal(3, capture.Requests);
    }

    private sealed class Upstream(HttpStatusCode status, string body) : HttpMessageHandler
    {
        public int Calls { get; private set; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Calls++;
            return Task.FromResult(new HttpResponseMessage(status) { Content = new StringContent(body, Encoding.UTF8, "application/json") });
        }
    }

    [Fact]
    public async Task Actual_response_vectors_are_observed_by_index_without_a_second_model_call_or_body_change()
    {
        const string body = """{"data":[{"index":1,"embedding":[3.0,4.0]},{"index":0,"embedding":[1.0,2.0]}]}""";
        var upstream = new Upstream(HttpStatusCode.OK, body);
        var capture = new ProductEmbeddingCapture();
        using var observer = new ProductEmbeddingObservation(upstream, capture);
        using var http = new HttpClient(observer);
        using var request = new StringContent("""{"model":"fixture","input":["first","second"]}""", Encoding.UTF8, "application/json");
        using var response = await http.PostAsync("http://fixture.invalid/embeddings", request, TestContext.Current.CancellationToken);
        Assert.Equal(body, await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        Assert.Equal([1f, 2f], capture.Vectors["first"]);
        Assert.Equal([3f, 4f], capture.Vectors["second"]);
        Assert.Equal(1, upstream.Calls); Assert.Equal(1, capture.Requests); Assert.Equal(0, capture.Failures);
    }

    [Fact]
    public async Task Failed_embedding_response_remains_a_failure_without_fabricated_vectors()
    {
        const string body = """{"error":"fixture unavailable"}""";
        var upstream = new Upstream(HttpStatusCode.ServiceUnavailable, body);
        var capture = new ProductEmbeddingCapture();
        using var observer = new ProductEmbeddingObservation(upstream, capture);
        using var http = new HttpClient(observer);
        using var request = new StringContent("""{"model":"fixture","input":["first"]}""", Encoding.UTF8, "application/json");
        using var response = await http.PostAsync("http://fixture.invalid/embeddings", request, TestContext.Current.CancellationToken);
        Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
        Assert.Equal(body, await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        Assert.Empty(capture.Vectors); Assert.Equal(1, capture.Failures); Assert.Equal(1, upstream.Calls);
    }
}
