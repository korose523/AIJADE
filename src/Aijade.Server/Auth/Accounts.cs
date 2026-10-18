using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;

using Aijade.Server.Infrastructure;

using Microsoft.AspNetCore.Authentication;
using Microsoft.Extensions.Options;

using Npgsql;

namespace Aijade.Server.Auth;

// Accounts and bearer authentication, designed for this server. A session is an opaque random token; only its SHA-256
// is stored, so a database leak does not leak usable tokens. Passwords are PBKDF2-SHA256 with a per-user salt. Static
// tokens (configuration, for development and end-to-end runs only) map a token to a user id.

public sealed record AccountUser(string Id, string Email, string Name, string Role, bool Banned);

public sealed class AuthOptions
{
    /// <summary>Session lifetime.</summary>
    public TimeSpan SessionLifetime { get; set; } = TimeSpan.FromDays(30);

    /// <summary>"token=userId" pairs for development / e2e. Never configure in production.</summary>
    public IDictionary<string, string> StaticTokens { get; } = new Dictionary<string, string>(StringComparer.Ordinal);

    /// <summary>Whether email sign-up is open.</summary>
    public bool AllowSignUp { get; set; } = true;
}

public static class PasswordHasher
{
    private const int Iterations = 210_000;

    public static string Hash(string password)
    {
        var salt = RandomNumberGenerator.GetBytes(16);
        var key = Rfc2898DeriveBytes.Pbkdf2(Encoding.UTF8.GetBytes(password), salt, Iterations, HashAlgorithmName.SHA256, 32);
        return $"pbkdf2-sha256${Iterations}${Convert.ToBase64String(salt)}${Convert.ToBase64String(key)}";
    }

    public static bool Verify(string password, string stored)
    {
        var parts = stored.Split('$');
        if (parts.Length != 4 || parts[0] != "pbkdf2-sha256" || !int.TryParse(parts[1], out var iterations))
            return false;
        var salt = Convert.FromBase64String(parts[2]);
        var expected = Convert.FromBase64String(parts[3]);
        var actual = Rfc2898DeriveBytes.Pbkdf2(Encoding.UTF8.GetBytes(password), salt, iterations, HashAlgorithmName.SHA256, expected.Length);
        return CryptographicOperations.FixedTimeEquals(actual, expected);
    }
}

public sealed class AccountService(NpgsqlDataSource db, IOptions<AuthOptions> options, TimeProvider? time = null)
{
    private readonly TimeProvider clock = time ?? TimeProvider.System;

    public static string TokenHash(string token) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(token)));

    private static AccountUser Map(System.Data.Common.DbDataReader r) => new(r.GetString(0), r.GetString(1), r.GetString(2), r.GetString(3), r.GetBoolean(4));

    private const string UserColumns = "u.id, u.email, u.name, u.role, u.banned";

    public async Task<AccountUser?> FindUserAsync(string id, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        return (await Sql.QueryAsync(conn, null, $"SELECT {UserColumns} FROM users u WHERE u.id = $1 AND u.deleted_at IS NULL", Map, ct, Sql.Text(id)).ConfigureAwait(false)).FirstOrDefault();
    }

    /// <summary>Resolve a bearer token: static tokens first, then live sessions. Banned or deleted users do not authenticate.</summary>
    public async Task<AccountUser?> ResolveTokenAsync(string token, CancellationToken ct = default)
    {
        if (options.Value.StaticTokens.TryGetValue(token, out var staticUser))
            return await FindUserAsync(staticUser, ct).ConfigureAwait(false) ?? new AccountUser(staticUser, $"{staticUser}@static.local", staticUser, "user", false);
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        return (await Sql.QueryAsync(conn, null,
            $"SELECT {UserColumns} FROM auth_sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = $1 AND s.expires_at > $2 AND u.deleted_at IS NULL",
            Map, ct, Sql.Text(TokenHash(token)), Sql.Time(clock.GetUtcNow())).ConfigureAwait(false)).FirstOrDefault();
    }

    public async Task<AccountUser> SignUpAsync(string email, string password, string? name, CancellationToken ct = default)
    {
        if (!options.Value.AllowSignUp)
            throw ApiException.Forbidden("Sign-up is disabled");
        email = email.Trim();
        if (email.Length < 3 || !email.Contains('@', StringComparison.Ordinal))
            throw ApiException.BadRequest("A valid email is required", "INVALID_EMAIL");
        if (password.Length < 8)
            throw ApiException.BadRequest("Password must be at least 8 characters", "WEAK_PASSWORD");
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        if (await Sql.CountAsync(conn, tx, "SELECT count(*) FROM users WHERE lower(email) = lower($1) AND deleted_at IS NULL", ct, Sql.Text(email)).ConfigureAwait(false) > 0)
            throw new ApiException(409, "EMAIL_TAKEN", "An account with this email already exists");
        var id = Ids.New();
        await Sql.ExecAsync(conn, tx, "INSERT INTO users (id, email, name) VALUES ($1,$2,$3)", ct, Sql.Text(id), Sql.Text(email), Sql.Text(name ?? "")).ConfigureAwait(false);
        await Sql.ExecAsync(conn, tx, "INSERT INTO user_passwords (user_id, hash) VALUES ($1,$2)", ct, Sql.Text(id), Sql.Text(PasswordHasher.Hash(password))).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
        return new AccountUser(id, email, name ?? "", "user", false);
    }

    public async Task<AccountUser?> CheckPasswordAsync(string email, string password, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        var row = (await Sql.QueryAsync(conn, null,
            $"SELECT {UserColumns}, p.hash FROM users u JOIN user_passwords p ON p.user_id = u.id WHERE lower(u.email) = lower($1) AND u.deleted_at IS NULL",
            r => (User: Map(r), Hash: r.GetString(5)), ct, Sql.Text(email.Trim())).ConfigureAwait(false)).FirstOrDefault();
        return row.User is not null && PasswordHasher.Verify(password, row.Hash) ? row.User : null;
    }

    /// <returns>The new opaque session token (shown once).</returns>
    public async Task<string> CreateSessionAsync(string userId, string? userAgent, string? ip, CancellationToken ct = default)
    {
        var token = Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_');
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await Sql.ExecAsync(conn, null, "INSERT INTO auth_sessions (token_hash, user_id, expires_at, user_agent, ip) VALUES ($1,$2,$3,$4,$5)", ct,
            Sql.Text(TokenHash(token)), Sql.Text(userId), Sql.Time(clock.GetUtcNow() + options.Value.SessionLifetime), Sql.Text(userAgent), Sql.Text(ip)).ConfigureAwait(false);
        return token;
    }

    public async Task RevokeSessionAsync(string token, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await Sql.ExecAsync(conn, null, "DELETE FROM auth_sessions WHERE token_hash = $1", ct, Sql.Text(TokenHash(token))).ConfigureAwait(false);
    }

    /// <summary>Find or create the user behind an external identity (OIDC), linking by verified email when possible.</summary>
    public async Task<AccountUser> UpsertExternalAsync(string provider, string subject, string email, string? name, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        var linked = (await Sql.QueryAsync(conn, null, $"SELECT {UserColumns} FROM user_identities i JOIN users u ON u.id = i.user_id WHERE i.provider = $1 AND i.subject = $2",
            Map, ct, Sql.Text(provider), Sql.Text(subject)).ConfigureAwait(false)).FirstOrDefault();
        if (linked is not null)
            return linked;
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        var user = (await Sql.QueryAsync(conn, tx, $"SELECT {UserColumns} FROM users u WHERE lower(u.email) = lower($1) AND u.deleted_at IS NULL", Map, ct, Sql.Text(email)).ConfigureAwait(false)).FirstOrDefault();
        if (user is null)
        {
            user = new AccountUser(Ids.New(), email, name ?? "", "user", false);
            await Sql.ExecAsync(conn, tx, "INSERT INTO users (id, email, name, email_verified) VALUES ($1,$2,$3,true)", ct, Sql.Text(user.Id), Sql.Text(email), Sql.Text(user.Name)).ConfigureAwait(false);
        }
        await Sql.ExecAsync(conn, tx, "INSERT INTO user_identities (provider, subject, user_id) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING", ct,
            Sql.Text(provider), Sql.Text(subject), Sql.Text(user.Id)).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
        return user;
    }
}

/// <summary>Bearer (or session cookie) authentication; failures answer with the API's JSON 401 body.</summary>
public sealed class BearerAuthHandler(IOptionsMonitor<AuthenticationSchemeOptions> options, ILoggerFactory logger, UrlEncoder encoder, AccountService accounts)
    : AuthenticationHandler<AuthenticationSchemeOptions>(options, logger, encoder)
{
    public const string SchemeName = "AijadeBearer";
    public const string CookieName = "aijade_session";

    public static string? TokenOf(HttpRequest request)
    {
        var header = request.Headers.Authorization.ToString();
        if (header.StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase))
            return header[7..].Trim();
        // Browsers cannot set headers on a WebSocket handshake: an upgrade request may carry the token as access_token.
        if (request.HttpContext.WebSockets.IsWebSocketRequest && request.Query["access_token"] is { Count: > 0 } q && q[0] is { Length: > 0 } fromQuery)
            return fromQuery;
        return request.Cookies.TryGetValue(CookieName, out var cookie) && cookie.Length > 0 ? cookie : null;
    }

    protected override async Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        if (TokenOf(Request) is not { Length: > 0 } token)
            return AuthenticateResult.NoResult();
        var user = await accounts.ResolveTokenAsync(token, Context.RequestAborted).ConfigureAwait(false);
        if (user is null)
            return AuthenticateResult.Fail("invalid or expired token");
        if (user.Banned)
            return AuthenticateResult.Fail("user is banned");
        var identity = new ClaimsIdentity(
            [new Claim(ClaimTypes.NameIdentifier, user.Id), new Claim(ClaimTypes.Email, user.Email), new Claim(ClaimTypes.Role, user.Role)], SchemeName);
        return AuthenticateResult.Success(new AuthenticationTicket(new ClaimsPrincipal(identity), SchemeName));
    }

    protected override Task HandleChallengeAsync(AuthenticationProperties properties) =>
        ApiErrorMiddleware.WriteAsync(Context, 401, "UNAUTHORIZED", "Unauthorized", null);

    protected override Task HandleForbiddenAsync(AuthenticationProperties properties) =>
        ApiErrorMiddleware.WriteAsync(Context, 403, "FORBIDDEN", "Forbidden", null);
}

public static class UserContext
{
    public static string UserId(this ClaimsPrincipal user) => user.FindFirstValue(ClaimTypes.NameIdentifier) ?? throw ApiException.Unauthorized();
}
