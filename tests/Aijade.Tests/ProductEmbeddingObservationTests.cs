using System.Net;
using System.Text;

namespace Aijade.Tests;

public sealed class ProductEmbeddingObservationTests
{
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
        using var observer = new ProductEmbeddingObservation(upstream);
        using var http = new HttpClient(observer);
        using var request = new StringContent("""{"model":"fixture","input":["first","second"]}""", Encoding.UTF8, "application/json");
        using var response = await http.PostAsync("http://fixture.invalid/embeddings", request, TestContext.Current.CancellationToken);
        Assert.Equal(body, await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        Assert.Equal([1f, 2f], observer.Vectors["first"]);
        Assert.Equal([3f, 4f], observer.Vectors["second"]);
        Assert.Equal(1, upstream.Calls); Assert.Equal(1, observer.Requests); Assert.Equal(0, observer.Failures);
    }

    [Fact]
    public async Task Failed_embedding_response_remains_a_failure_without_fabricated_vectors()
    {
        const string body = """{"error":"fixture unavailable"}""";
        var upstream = new Upstream(HttpStatusCode.ServiceUnavailable, body);
        using var observer = new ProductEmbeddingObservation(upstream);
        using var http = new HttpClient(observer);
        using var request = new StringContent("""{"model":"fixture","input":["first"]}""", Encoding.UTF8, "application/json");
        using var response = await http.PostAsync("http://fixture.invalid/embeddings", request, TestContext.Current.CancellationToken);
        Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
        Assert.Equal(body, await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        Assert.Empty(observer.Vectors); Assert.Equal(1, observer.Failures); Assert.Equal(1, upstream.Calls);
    }
}
