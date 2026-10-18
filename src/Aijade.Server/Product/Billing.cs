using System.Globalization;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Server.Auth;
using Aijade.Server.Infrastructure;
using Aijade.Server.V9;

using Npgsql;

namespace Aijade.Server.Product;

// Stripe billing over its public HTTP API (no SDK). A checkout buys a configured flux amount for a configured price; the
// webhook is verified (HMAC-SHA256 over "{t}.{payload}", 5-minute tolerance), every event id is processed once, and the
// credit for a session is idempotent, so retried or duplicated deliveries never credit twice.
//   Stripe:SecretKey, Stripe:WebhookSecret, Stripe:SuccessUrl, Stripe:CancelUrl, Stripe:Prices:<priceId> = <flux>,
//   Stripe:ApiBase (default https://api.stripe.com)

public sealed class StripeOptions
{
    public string? SecretKey { get; set; }

    public string? WebhookSecret { get; set; }

    public string SuccessUrl { get; set; } = "http://localhost:5173/billing/success";

    public string CancelUrl { get; set; } = "http://localhost:5173/billing/cancel";

    public string ApiBase { get; set; } = "https://api.stripe.com";

    public IDictionary<string, long> Prices { get; } = new Dictionary<string, long>(StringComparer.Ordinal);
}

public static class StripeSignature
{
    public static string Sign(string payload, long timestamp, string secret) =>
        Convert.ToHexStringLower(HMACSHA256.HashData(Encoding.UTF8.GetBytes(secret), Encoding.UTF8.GetBytes($"{timestamp.ToString(CultureInfo.InvariantCulture)}.{payload}")));

    /// <summary>Verify a Stripe-Signature header (t=…, one or more v1=…) within the tolerance.</summary>
    public static bool Verify(string payload, string? header, string secret, DateTimeOffset now, TimeSpan? tolerance = null)
    {
        if (string.IsNullOrEmpty(header))
            return false;
        var parts = header.Split(',').Select(p => p.Split('=', 2)).Where(p => p.Length == 2).ToList();
        if (!long.TryParse(parts.FirstOrDefault(p => p[0] == "t")?[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out var t))
            return false;
        if (Math.Abs(now.ToUnixTimeSeconds() - t) > (tolerance ?? TimeSpan.FromMinutes(5)).TotalSeconds)
            return false;
        var expected = Encoding.ASCII.GetBytes(Sign(payload, t, secret));
        return parts.Where(p => p[0] == "v1").Any(p => CryptographicOperations.FixedTimeEquals(expected, Encoding.ASCII.GetBytes(p[1])));
    }
}

public static class BillingEndpoints
{
    public const string HttpClientName = "stripe";

    public static void Map(IEndpointRouteBuilder app)
    {
        app.MapGet("/api/v1/stripe/prices", (Microsoft.Extensions.Options.IOptions<StripeOptions> o) =>
            Results.Json(new JsonObject { ["prices"] = new JsonArray([.. o.Value.Prices.Select(p => (JsonNode)new JsonObject { ["priceId"] = p.Key, ["flux"] = p.Value })]) }));

        app.MapPost("/api/v1/stripe/checkout", async (HttpContext c, Microsoft.Extensions.Options.IOptions<StripeOptions> options, IHttpClientFactory factory, NpgsqlDataSource db,
            ProductEvents events, CancellationToken ct) =>
        {
            var o = options.Value;
            if (string.IsNullOrEmpty(o.SecretKey))
                throw new ApiException(503, "BILLING_UNCONFIGURED", "billing is not configured");
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_CHECKOUT", ct).ConfigureAwait(false);
            var priceId = b?["priceId"]?.GetValue<string>() ?? throw ApiException.BadRequest("priceId is required", "INVALID_CHECKOUT");
            if (!o.Prices.TryGetValue(priceId, out var fluxAmount))
                throw ApiException.BadRequest("unknown price", "INVALID_CHECKOUT");
            var userId = c.User.UserId();
            using var req = new HttpRequestMessage(HttpMethod.Post, $"{o.ApiBase.TrimEnd('/')}/v1/checkout/sessions")
            {
                Content = new FormUrlEncodedContent(new Dictionary<string, string>
                {
                    ["mode"] = "payment",
                    ["line_items[0][price]"] = priceId,
                    ["line_items[0][quantity]"] = "1",
                    ["success_url"] = o.SuccessUrl,
                    ["cancel_url"] = o.CancelUrl,
                    ["client_reference_id"] = userId,
                    ["metadata[user_id]"] = userId,
                }),
            };
            req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", o.SecretKey);
            using var res = await factory.CreateClient(HttpClientName).SendAsync(req, ct).ConfigureAwait(false);
            var json = JsonNode.Parse(await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false));
            if (!res.IsSuccessStatusCode || json?["id"] is null)
                throw new ApiException(502, "BILLING_PROVIDER_ERROR", "the payment provider refused the checkout");
            var sessionId = json["id"]!.GetValue<string>();
            await using (var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false))
            {
                await Sql.ExecAsync(conn, null, "INSERT INTO stripe_checkouts (session_id, user_id, price_id, flux_amount) VALUES ($1,$2,$3,$4)", ct,
                    Sql.Text(sessionId), Sql.Text(userId), Sql.Text(priceId), Sql.P(fluxAmount)).ConfigureAwait(false);
            }
            await events.TrackAsync(userId, "billing", "checkout_started", "started", "stripe.checkout", ct: ct).ConfigureAwait(false);
            return Results.Json(new JsonObject { ["sessionId"] = sessionId, ["url"] = json["url"]?.DeepClone() });
        }).RequireAuthorization();

        app.MapPost("/api/v1/stripe/webhook", async (HttpContext c, Microsoft.Extensions.Options.IOptions<StripeOptions> options, NpgsqlDataSource db, FluxLedger flux,
            ProductEvents events, TimeProvider time, CancellationToken ct) =>
        {
            var o = options.Value;
            if (string.IsNullOrEmpty(o.WebhookSecret))
                throw new ApiException(503, "BILLING_UNCONFIGURED", "billing is not configured");
            using var reader = new StreamReader(c.Request.Body, Encoding.UTF8);
            var payload = await reader.ReadToEndAsync(ct).ConfigureAwait(false);
            if (!StripeSignature.Verify(payload, c.Request.Headers["Stripe-Signature"], o.WebhookSecret, time.GetUtcNow()))
                throw ApiException.BadRequest("invalid signature", "INVALID_SIGNATURE");
            var evt = JsonNode.Parse(payload)!;
            var eventId = evt["id"]!.GetValue<string>();
            var type = evt["type"]!.GetValue<string>();
            await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
            if (await Sql.ExecAsync(conn, null, "INSERT INTO stripe_events (id, type) VALUES ($1,$2) ON CONFLICT DO NOTHING", ct, Sql.Text(eventId), Sql.Text(type)).ConfigureAwait(false) == 0)
                return Results.Json(new JsonObject { ["received"] = true, ["duplicate"] = true });
            var session = evt["data"]?["object"];
            var sessionId = session?["id"]?.GetValue<string>();
            if (type == "checkout.session.completed" && sessionId is not null && session?["payment_status"]?.GetValue<string>() == "paid")
            {
                var checkout = (await Sql.QueryAsync(conn, null, "SELECT user_id, flux_amount FROM stripe_checkouts WHERE session_id = $1", r => (User: r.GetString(0), Flux: r.GetInt64(1)), ct,
                    Sql.Text(sessionId)).ConfigureAwait(false)).FirstOrDefault();
                if (checkout.User is not null)
                {
                    await flux.ApplyAsync(checkout.User, checkout.Flux, "purchase", $"stripe:{sessionId}", $"stripe:{sessionId}", ct: ct).ConfigureAwait(false);
                    await Sql.ExecAsync(conn, null, "UPDATE stripe_checkouts SET status = 'completed', completed_at = now() WHERE session_id = $1", ct, Sql.Text(sessionId)).ConfigureAwait(false);
                    await events.TrackAsync(checkout.User, "billing", "payment_completed", "succeeded", "stripe.webhook", ct: ct).ConfigureAwait(false);
                }
            }
            else if (type == "checkout.session.expired" && sessionId is not null)
            {
                await Sql.ExecAsync(conn, null, "UPDATE stripe_checkouts SET status = 'expired' WHERE session_id = $1 AND status = 'open'", ct, Sql.Text(sessionId)).ConfigureAwait(false);
            }
            return Results.Json(new JsonObject { ["received"] = true });
        });
    }
}
