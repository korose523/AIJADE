using System.Text.Json.Nodes;

using Aijade.Server.Infrastructure;
using Aijade.Server.V9;

namespace Aijade.Server.Auth;

public static class AuthEndpoints
{
    private static JsonObject UserJson(AccountUser u) => new() { ["id"] = u.Id, ["email"] = u.Email, ["name"] = u.Name, ["role"] = u.Role };

    public static void Map(IEndpointRouteBuilder app)
    {
        var g = app.MapGroup("/api/v1/auth");
        g.MapPost("/sign-up/email", async (HttpContext c, AccountService accounts, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_AUTH_REQUEST", ct).ConfigureAwait(false);
            var user = await accounts.SignUpAsync(b?["email"]?.GetValue<string>() ?? "", b?["password"]?.GetValue<string>() ?? "", b?["name"]?.GetValue<string>(), ct).ConfigureAwait(false);
            var token = await accounts.CreateSessionAsync(user.Id, c.Request.Headers.UserAgent.ToString(), c.Connection.RemoteIpAddress?.ToString(), ct).ConfigureAwait(false);
            return Results.Json(new JsonObject { ["user"] = UserJson(user), ["token"] = token }, statusCode: 201);
        });
        g.MapPost("/sign-in/email", async (HttpContext c, AccountService accounts, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_AUTH_REQUEST", ct).ConfigureAwait(false);
            var user = await accounts.CheckPasswordAsync(b?["email"]?.GetValue<string>() ?? "", b?["password"]?.GetValue<string>() ?? "", ct).ConfigureAwait(false)
                ?? throw new ApiException(401, "INVALID_CREDENTIALS", "Invalid email or password");
            if (user.Banned)
                throw ApiException.Forbidden("This account is banned");
            var token = await accounts.CreateSessionAsync(user.Id, c.Request.Headers.UserAgent.ToString(), c.Connection.RemoteIpAddress?.ToString(), ct).ConfigureAwait(false);
            return Results.Json(new JsonObject { ["user"] = UserJson(user), ["token"] = token });
        });
        g.MapPost("/sign-out", async (HttpContext c, AccountService accounts, CancellationToken ct) =>
        {
            if (BearerAuthHandler.TokenOf(c.Request) is { } token)
                await accounts.RevokeSessionAsync(token, ct).ConfigureAwait(false);
            return Results.Json(new JsonObject { ["ok"] = true });
        });
        g.MapGet("/session", async (HttpContext c, AccountService accounts, CancellationToken ct) =>
        {
            var user = await accounts.FindUserAsync(c.User.UserId(), ct).ConfigureAwait(false) ?? throw ApiException.Unauthorized();
            return Results.Json(new JsonObject { ["user"] = UserJson(user) });
        }).RequireAuthorization();
    }
}
