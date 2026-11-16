using System.Security.Claims;
using System.Text.Json.Nodes;

using Aijade.Server.Infrastructure;

using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Authentication.OpenIdConnect;

using Npgsql;

namespace Aijade.Server.Auth;

// OpenID Connect sign-in (authorization code flow) with any standards-compliant provider, plus account deletion.
//   Auth:Oidc:Authority, Auth:Oidc:ClientId, Auth:Oidc:ClientSecret, Auth:Oidc:Name (display name, default "oidc")
//   Auth:Oidc:AllowedReturnUrls:0..n   absolute return-URL prefixes (apps: custom schemes); relative paths always allowed
// After the provider signs the user in, the external identity is linked (or a user created, linking by email), a normal
// opaque session is issued as the aijade_session cookie, and the browser returns to the requested page. An app return URL
// receives the token in the fragment (never in the query, which reaches server logs).

public static class OidcSetup
{
    public const string ExternalScheme = "aijade-external";
    public const string OidcScheme = "oidc";
    public const string CallbackPath = "/api/v1/auth/oidc/callback";

    private static readonly string[] Scopes = ["openid", "email", "profile"];

    private static readonly string[] UnlinkedTables =
        ["persona_snapshots", "performance_intents", "memory_sync_outbox", "sharing_notifications", "product_events", "llm_request_logs"];

    public static bool IsConfigured(IConfiguration config) => !string.IsNullOrEmpty(config["Auth:Oidc:Authority"]) && !string.IsNullOrEmpty(config["Auth:Oidc:ClientId"]);

    public static void Add(AuthenticationBuilder auth, IConfiguration config)
    {
        if (!IsConfigured(config))
            return;
        auth.AddCookie(ExternalScheme, o =>
        {
            o.Cookie.Name = "aijade_external";
            o.ExpireTimeSpan = TimeSpan.FromMinutes(10);
        });
        auth.AddOpenIdConnect(OidcScheme, o =>
        {
            o.Authority = config["Auth:Oidc:Authority"];
            o.ClientId = config["Auth:Oidc:ClientId"];
            o.ClientSecret = config["Auth:Oidc:ClientSecret"];
            o.ResponseType = "code";
            o.UsePkce = true;
            o.SignInScheme = ExternalScheme;
            o.CallbackPath = CallbackPath;
            o.SaveTokens = false;
            o.GetClaimsFromUserInfoEndpoint = true;
            o.MapInboundClaims = false;
            o.Scope.Clear();
            foreach (var scope in Scopes)
                o.Scope.Add(scope);
        });
    }

    /// <summary>A return URL is allowed when it is a local path or starts with a configured prefix.</summary>
    public static bool IsAllowedReturnUrl(string url, IConfiguration config) =>
        (url.StartsWith('/') && !url.StartsWith("//", StringComparison.Ordinal) && !url.StartsWith("/\\", StringComparison.Ordinal))
        || config.GetSection("Auth:Oidc:AllowedReturnUrls").GetChildren().Any(p => !string.IsNullOrEmpty(p.Value) && url.StartsWith(p.Value, StringComparison.Ordinal));

    public static void Map(IEndpointRouteBuilder app, IConfiguration config)
    {
        app.MapGet("/api/v1/auth/providers", () => Results.Json(new JsonObject
        {
            ["email"] = true,
            ["oidc"] = IsConfigured(config) ? new JsonObject { ["name"] = config["Auth:Oidc:Name"] ?? OidcScheme } : null,
        }));
        app.MapDelete("/api/v1/auth/account", DeleteAccountAsync).RequireAuthorization();
        if (!IsConfigured(config))
            return;
        app.MapGet("/api/v1/auth/oidc/login", (string? returnUrl) =>
        {
            var target = returnUrl is { Length: > 0 } r && IsAllowedReturnUrl(r, config) ? r : "/";
            return Results.Challenge(new AuthenticationProperties { RedirectUri = $"/api/v1/auth/oidc/complete?returnUrl={Uri.EscapeDataString(target)}" }, [OidcScheme]);
        });
        app.MapGet("/api/v1/auth/oidc/complete", async (HttpContext c, string? returnUrl, AccountService accounts, CancellationToken ct) =>
        {
            var external = await c.AuthenticateAsync(ExternalScheme).ConfigureAwait(false);
            if (!external.Succeeded || external.Principal is not { } p)
                throw ApiException.Unauthorized();
            var subject = p.FindFirstValue("sub") ?? throw ApiException.BadRequest("the provider returned no subject", "OIDC_NO_SUBJECT");
            var email = p.FindFirstValue("email") ?? throw ApiException.BadRequest("the provider returned no email", "OIDC_NO_EMAIL");
            var provider = new Uri(config["Auth:Oidc:Authority"]!).Host;
            var user = await accounts.UpsertExternalAsync(provider, subject, email, p.FindFirstValue("name"), ct).ConfigureAwait(false);
            if (user.Banned)
                throw ApiException.Forbidden("This account is banned");
            var token = await accounts.CreateSessionAsync(user.Id, c.Request.Headers.UserAgent.ToString(), c.Connection.RemoteIpAddress?.ToString(), ct).ConfigureAwait(false);
            await c.SignOutAsync(ExternalScheme).ConfigureAwait(false);
            var target = returnUrl is { Length: > 0 } r && IsAllowedReturnUrl(r, config) ? r : "/";
            if (target.StartsWith('/'))
            {
                c.Response.Cookies.Append(BearerAuthHandler.CookieName, token, new CookieOptions
                {
                    HttpOnly = true, Secure = c.Request.IsHttps, SameSite = SameSiteMode.Lax, MaxAge = TimeSpan.FromDays(30), Path = "/",
                });
                return Results.Redirect(target);
            }
            return Results.Redirect($"{target}#token={Uri.EscapeDataString(token)}");
        });
    }

    /// <summary>Delete the caller's account and everything personal stored for it; sessions end immediately.</summary>
    private static async Task<IResult> DeleteAccountAsync(HttpContext c, NpgsqlDataSource db, CancellationToken ct)
    {
        var userId = c.User.UserId();
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        // Tables keyed by user id without a foreign key are cleared explicitly; the rest cascade from users.
        foreach (var table in UnlinkedTables)
            await Sql.ExecAsync(conn, tx, $"DELETE FROM {table} WHERE user_id = $1", ct, Sql.Text(userId)).ConfigureAwait(false);
        await Sql.ExecAsync(conn, tx, "DELETE FROM users WHERE id = $1", ct, Sql.Text(userId)).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
        c.Response.Cookies.Delete(BearerAuthHandler.CookieName);
        return Results.NoContent();
    }
}

/// <summary>The cookie scheme name used by <see cref="CookieAuthenticationDefaults"/>; referenced so the package stays explicit.</summary>
internal static class OidcDefaults
{
    public const string Cookie = CookieAuthenticationDefaults.AuthenticationScheme;

    public const string Oidc = OpenIdConnectDefaults.AuthenticationScheme;
}
