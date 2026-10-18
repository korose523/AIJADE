using System.Net.Http.Headers;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Server;
using Aijade.Server.Infrastructure;

using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

using Npgsql;

namespace Aijade.Tests;

/// <summary>
/// The real server (in-memory transport) over a fresh PostgreSQL database created for this host and dropped afterwards.
/// Needs AIJADE_TEST_DATABASE_URL (a server the tests may create databases on, e.g. the dev container started by
/// tools/dev-services.sh); without it the database tests are skipped, never reported as passing.
/// </summary>
public sealed class ServerTestHost : IAsyncDisposable
{
    public const string Token = "test-token-aijade";
    public const string UserId = "test-user";
    public const string AdminToken = "test-admin-token-aijade";
    public const string AdminId = "test-admin";

    private readonly string adminConnection;
    private readonly string database;

    public WebApplication App { get; }

    public HttpClient Client { get; }

    public NpgsqlDataSource Db { get; }

    private ServerTestHost(WebApplication app, HttpClient client, NpgsqlDataSource db, string adminConnection, string database)
    {
        App = app;
        Client = client;
        Db = db;
        this.adminConnection = adminConnection;
        this.database = database;
    }

    public static string? ServerUrl => Environment.GetEnvironmentVariable("AIJADE_TEST_DATABASE_URL");

    public static async Task<ServerTestHost> StartAsync(IDictionary<string, string?>? settings = null, bool worker = true, Action<IServiceCollection>? services = null)
    {
        if (ServerUrl is not { Length: > 0 } url)
        {
            Assert.Skip("AIJADE_TEST_DATABASE_URL is not set (start tools/dev-services.sh); database tests skipped");
            throw new InvalidOperationException("unreachable");
        }
        var admin = AijadeServer.NormalizeConnectionString(url);
        var database = $"aijade_test_{Guid.NewGuid():N}";
        await using (var conn = new NpgsqlConnection(admin))
        {
            await conn.OpenAsync();
            await using var cmd = new NpgsqlCommand($"CREATE DATABASE {database}", conn);
            await cmd.ExecuteNonQueryAsync();
        }
        var cs = new NpgsqlConnectionStringBuilder(admin) { Database = database, Pooling = true }.ConnectionString;
        var config = new Dictionary<string, string?>
        {
            ["DATABASE_URL"] = cs,
            ["Aijade:Role"] = worker ? "all" : "api",
            [$"Auth:StaticTokens:{Token}"] = UserId,
            [$"Auth:StaticTokens:{AdminToken}"] = AdminId,
            ["DataProtection:KeysDir"] = Path.Combine(Path.GetTempPath(), "aijade-test-dp-keys"),
            ["Logging:LogLevel:Default"] = "Warning",
        };
        foreach (var (k, v) in settings ?? new Dictionary<string, string?>())
            config[k] = v;
        var app = AijadeServer.Build([], b =>
        {
            b.WebHost.UseTestServer();
            b.Configuration.AddInMemoryCollection(config);
            services?.Invoke(b.Services);
        });
        await AijadeServer.PrepareAsync(app);
        await using (var conn = await app.Services.GetRequiredService<NpgsqlDataSource>().OpenConnectionAsync())
        {
            await using var seed = new NpgsqlCommand(
                $"UPDATE users SET email = 'user@test.local', name = 'Test' WHERE id = '{UserId}'; UPDATE users SET email = 'admin@test.local', name = 'Admin', role = 'admin' WHERE id = '{AdminId}'", conn);
            await seed.ExecuteNonQueryAsync();
        }
        await app.StartAsync();
        var client = app.GetTestClient();
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", Token);
        return new ServerTestHost(app, client, app.Services.GetRequiredService<NpgsqlDataSource>(), admin, database);
    }

    public async Task<(int Status, JsonNode? Body)> PostAsync(string path, JsonNode body, bool auth = true) => await PostRawAsync(path, body.ToJsonString(), auth);

    /// <summary>Any method, with an explicit bearer token (null = anonymous).</summary>
    public async Task<(int Status, JsonNode? Body)> SendAsync(HttpMethod method, string path, JsonNode? body = null, string? token = Token)
    {
        using var req = new HttpRequestMessage(method, path);
        if (body is not null)
            req.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
        req.Headers.Authorization = token is null ? null : new AuthenticationHeaderValue("Bearer", token);
        using var raw = new HttpClient(App.GetTestServer().CreateHandler()) { BaseAddress = Client.BaseAddress };
        using var res = await raw.SendAsync(req);
        var text = await res.Content.ReadAsStringAsync();
        JsonNode? json = null;
        try
        {
            json = text.Length == 0 ? null : JsonNode.Parse(text);
        }
        catch (System.Text.Json.JsonException)
        {
            json = new JsonObject { ["raw"] = text };
        }
        return ((int)res.StatusCode, json);
    }

    public async Task<(int Status, JsonNode? Body)> PostRawAsync(string path, string raw, bool auth = true)
    {
        using var req = new HttpRequestMessage(HttpMethod.Post, path) { Content = new StringContent(raw, Encoding.UTF8, "application/json") };
        if (!auth)
            req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", "not-a-token");
        using var res = await Client.SendAsync(req);
        var text = await res.Content.ReadAsStringAsync();
        JsonNode? json;
        try
        {
            json = JsonNode.Parse(text);
        }
        catch (System.Text.Json.JsonException)
        {
            json = new JsonObject { ["raw"] = text };
        }
        return ((int)res.StatusCode, json);
    }

    public async Task<long> CountAsync(string sql, params object[] args)
    {
        await using var conn = await Db.OpenConnectionAsync();
        return await Sql.CountAsync(conn, null, sql, CancellationToken.None, [.. args.Select(Sql.P)]);
    }

    public async Task<string?> ScalarAsync(string sql, params object[] args)
    {
        await using var conn = await Db.OpenConnectionAsync();
        await using var cmd = Sql.Cmd(conn, null, sql, [.. args.Select(Sql.P)]);
        var v = await cmd.ExecuteScalarAsync();
        return v is null or DBNull ? null : Convert.ToString(v, System.Globalization.CultureInfo.InvariantCulture);
    }

    public async Task ExecAsync(string sql, params object[] args)
    {
        await using var conn = await Db.OpenConnectionAsync();
        await Sql.ExecAsync(conn, null, sql, CancellationToken.None, [.. args.Select(Sql.P)]);
    }

    public async ValueTask DisposeAsync()
    {
        Client.Dispose();
        await App.StopAsync();
        await App.DisposeAsync();
        NpgsqlConnection.ClearAllPools();
        await using var conn = new NpgsqlConnection(adminConnection);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand($"DROP DATABASE IF EXISTS {database} WITH (FORCE)", conn);
        await cmd.ExecuteNonQueryAsync();
    }
}
