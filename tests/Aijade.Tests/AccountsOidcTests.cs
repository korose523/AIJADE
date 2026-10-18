using System.Net;
using System.Text.Json.Nodes;

using Aijade.Server.Auth;

using Microsoft.AspNetCore.Authentication.OpenIdConnect;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.IdentityModel.Protocols.OpenIdConnect;

namespace Aijade.Tests;

public class AccountsOidcTests
{
    [Fact]
    public async Task Oidc_login_redirects_to_the_provider_with_pkce_and_external_identities_link_by_email()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(new Dictionary<string, string?>
        {
            ["Auth:Oidc:Authority"] = "https://idp.test", ["Auth:Oidc:ClientId"] = "aijade-web", ["Auth:Oidc:ClientSecret"] = "s",
            ["Auth:Oidc:AllowedReturnUrls:0"] = "aijade://auth",
        }, worker: false, services: s => s.PostConfigure<OpenIdConnectOptions>(OidcSetup.OidcScheme, o => o.Configuration = new OpenIdConnectConfiguration
        {
            Issuer = "https://idp.test", AuthorizationEndpoint = "https://idp.test/authorize", TokenEndpoint = "https://idp.test/token",
        }));
        using var client = host.App.GetTestServerClient();
        using var res = await client.GetAsync(new Uri("/api/v1/auth/oidc/login?returnUrl=/chat", UriKind.Relative), ct);
        Assert.Equal(HttpStatusCode.Redirect, res.StatusCode);
        var location = res.Headers.Location!.ToString();
        Assert.StartsWith("https://idp.test/authorize?", location, StringComparison.Ordinal);
        Assert.Contains("client_id=aijade-web", location, StringComparison.Ordinal);
        Assert.Contains("code_challenge=", location, StringComparison.Ordinal);
        Assert.Contains("redirect_uri=http%3A%2F%2Flocalhost%2Fapi%2Fv1%2Fauth%2Foidc%2Fcallback", location, StringComparison.Ordinal);
        var (_, providers) = await host.SendAsync(HttpMethod.Get, "/api/v1/auth/providers", token: null);
        Assert.Equal("oidc", providers!["oidc"]!["name"]!.GetValue<string>());

        var config = host.App.Services.GetRequiredService<IConfiguration>();
        Assert.True(OidcSetup.IsAllowedReturnUrl("/chat", config));
        Assert.True(OidcSetup.IsAllowedReturnUrl("aijade://auth/done", config));
        Assert.False(OidcSetup.IsAllowedReturnUrl("//evil.example", config));
        Assert.False(OidcSetup.IsAllowedReturnUrl("https://evil.example", config));

        var accounts = host.App.Services.GetRequiredService<AccountService>();
        var linked = await accounts.UpsertExternalAsync("idp.test", "sub-1", "user@test.local", "Test", ct);
        Assert.Equal(ServerTestHost.UserId, linked.Id); // linked to the existing account by email
        var fresh = await accounts.UpsertExternalAsync("idp.test", "sub-2", "new@x.io", "New", ct);
        Assert.Equal(fresh.Id, (await accounts.UpsertExternalAsync("idp.test", "sub-2", "changed@x.io", null, ct)).Id); // the subject is the key
    }

    [Fact]
    public async Task Deleting_an_account_removes_personal_data_and_ends_sessions()
    {
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var (_, up) = await host.SendAsync(HttpMethod.Post, "/api/v1/auth/sign-up/email", new JsonObject { ["email"] = "d@x.io", ["password"] = "correct horse" }, token: null);
        var token = up!["token"]!.GetValue<string>();
        var (_, chat) = await host.SendAsync(HttpMethod.Post, "/api/v1/chats", new JsonObject { ["title"] = "t" }, token);
        await host.SendAsync(HttpMethod.Post, $"/api/v1/chats/{chat!["id"]}/messages", new JsonObject { ["role"] = "user", ["content"] = "private" }, token);
        Assert.Equal(204, (await host.SendAsync(HttpMethod.Delete, "/api/v1/auth/account", token: token)).Status);
        Assert.Equal(401, (await host.SendAsync(HttpMethod.Get, "/api/v1/auth/session", token: token)).Status);
        Assert.Equal(0, await host.CountAsync("SELECT count(*) FROM chat_messages WHERE content = 'private'"));
        Assert.Equal(0, await host.CountAsync("SELECT count(*) FROM product_events WHERE user_id = $1", up["user"]!["id"]!.GetValue<string>()));
        Assert.Equal(0, await host.CountAsync("SELECT count(*) FROM users WHERE email = 'd@x.io'"));
    }
}

internal static class TestServerExtensions
{
    /// <summary>A client that does not follow redirects, so a 302 can be asserted.</summary>
    public static HttpClient GetTestServerClient(this Microsoft.AspNetCore.Builder.WebApplication app)
    {
        var handler = ((Microsoft.AspNetCore.TestHost.TestServer)app.Services.GetRequiredService<Microsoft.AspNetCore.Hosting.Server.IServer>()).CreateHandler();
        return new HttpClient(handler) { BaseAddress = new Uri("http://localhost") };
    }
}
