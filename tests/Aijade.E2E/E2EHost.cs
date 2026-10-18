using System.Diagnostics;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Text.Json.Nodes;

using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Microsoft.Playwright;

using Npgsql;

[assembly: AssemblyFixture(typeof(Aijade.E2E.E2EHost))]

namespace Aijade.E2E;

/// <summary>
/// The whole product as a user meets it: the real server, run as its own process from its build output (so the Blazor
/// WebAssembly client and static assets are served exactly as deployed), over a fresh PostgreSQL database, with a fake
/// OpenAI-compatible upstream behind the gateway, driven through headless Chromium.
/// Opt-in: needs AIJADE_E2E=1 and AIJADE_TEST_DATABASE_URL; otherwise every test is skipped, never reported as passing.
/// The first run downloads Chromium for Playwright (approved by the author on 2026-10-09).
/// Optional: AIJADE_E2E_MMD_DIR (a folder with a PMX model the author is licensed to use) and AIJADE_E2E_MMD_MODEL (its
/// file name) enable the MMD stage test; such models are never copied into the repository.
/// </summary>
public sealed class E2EHost : IAsyncLifetime
{
    public const string AdminToken = "e2e-admin-token";
    public const string AdminId = "e2e-admin";

    private readonly StringBuilder serverLog = new();
    private Process? server;
    private WebApplication? upstream;
    private string? adminConnection;
    private string? database;

    public string? SkipReason { get; private set; }

    public Uri BaseUrl { get; private set; } = new("http://127.0.0.1/");

    public NpgsqlDataSource Db { get; private set; } = null!;

    public IBrowser Browser { get; private set; } = null!;

    public FakeUpstream Llm { get; } = new();

    public static string? MmdDir => Environment.GetEnvironmentVariable("AIJADE_E2E_MMD_DIR") is { Length: > 0 } d && Directory.Exists(d) ? d : null;

    public static string? MmdModel => Environment.GetEnvironmentVariable("AIJADE_E2E_MMD_MODEL") is { Length: > 0 } m ? m : null;

    private IPlaywright? playwright;

    public async ValueTask InitializeAsync()
    {
        if (Environment.GetEnvironmentVariable("AIJADE_E2E") != "1")
        {
            SkipReason = "AIJADE_E2E is not 1; browser end-to-end tests skipped";
            return;
        }
        if (Environment.GetEnvironmentVariable("AIJADE_TEST_DATABASE_URL") is not { Length: > 0 } url)
        {
            SkipReason = "AIJADE_TEST_DATABASE_URL is not set (start tools/dev-services.sh); browser end-to-end tests skipped";
            return;
        }

        adminConnection = NormalizeConnectionString(url);
        database = $"aijade_e2e_{Guid.NewGuid():N}";
        await using (var conn = new NpgsqlConnection(adminConnection))
        {
            await conn.OpenAsync();
            await using var cmd = new NpgsqlCommand($"CREATE DATABASE {database}", conn);
            await cmd.ExecuteNonQueryAsync();
        }
        var cs = new NpgsqlConnectionStringBuilder(adminConnection) { Database = database }.ConnectionString;
        Db = NpgsqlDataSource.Create(cs);

        upstream = Llm.Build();
        await upstream.StartAsync();
        var upstreamUrl = upstream.Urls.First();

        var port = FreePort();
        BaseUrl = new Uri($"http://127.0.0.1:{port}/");
        server = StartServer(cs, BaseUrl);
        await WaitHealthyAsync();

        await using (var cmd = Db.CreateCommand($"UPDATE users SET role = 'admin' WHERE id = '{AdminId}'"))
            await cmd.ExecuteNonQueryAsync();
        using var http = new HttpClient { BaseAddress = BaseUrl };
        using var put = new HttpRequestMessage(HttpMethod.Put, "/api/v1/admin/gateway/routes")
        {
            Content = new StringContent(new JsonObject
            {
                ["models"] = new JsonObject
                {
                    ["aijade-chat"] = new JsonObject { ["upstream"] = $"{upstreamUrl}/v1", ["model"] = "fake", ["keys"] = new JsonArray("k"), ["fluxPer1k"] = 0 },
                },
                ["transcription"] = new JsonObject { ["upstream"] = $"{upstreamUrl}/v1", ["model"] = "fake-asr", ["keys"] = new JsonArray("k") },
                ["images"] = new JsonObject { ["kind"] = "openai", ["upstream"] = $"{upstreamUrl}/v1", ["model"] = "fake-image", ["keys"] = new JsonArray("k") },
            }.ToJsonString(), Encoding.UTF8, "application/json"),
        };
        put.Headers.Authorization = new AuthenticationHeaderValue("Bearer", AdminToken);
        using (var res = await http.SendAsync(put))
            Assert.True(res.IsSuccessStatusCode, $"gateway route setup failed: {(int)res.StatusCode} {await res.Content.ReadAsStringAsync()}");

        Assert.Equal(0, Microsoft.Playwright.Program.Main(["install", "chromium"]));
        playwright = await Playwright.CreateAsync();
        // Synthetic audio in the beat-sync test must play without a click on the page itself.
        Browser = await playwright.Chromium.LaunchAsync(new() { Headless = true, Args = ["--autoplay-policy=no-user-gesture-required"] });
        // The WebAssembly client boots in a few seconds after every reload (longer under software WebGL).
        Assertions.SetDefaultExpectTimeout(30_000);
    }

    /// <summary>Skips the calling test when the environment does not opt in.</summary>
    public void RequireEnabled()
    {
        if (SkipReason is not null)
            Assert.Skip(SkipReason);
    }

    /// <summary>A fresh browser context (own storage) in English, so selectors can use the English UI text.</summary>
    public async Task<IPage> NewPageAsync(string locale = "en-US")
    {
        var context = await Browser.NewContextAsync(new() { BaseURL = BaseUrl.ToString(), Locale = locale, ViewportSize = new() { Width = 1280, Height = 800 } });
        context.SetDefaultTimeout(30_000);
        return await context.NewPageAsync();
    }

    /// <summary>Signs up a new account through the UI and waits for the chat page.</summary>
    public async Task<(IPage Page, string Email)> SignUpAsync(string name = "E2E")
    {
        var page = await NewPageAsync();
        var email = $"e2e-{Guid.NewGuid():N}@aijade.test";
        await page.GotoAsync("/");
        await page.GetByRole(AriaRole.Button, new() { Name = "No account yet?" }).ClickAsync();
        await page.GetByLabel("Name").FillAsync(name);
        await page.GetByLabel("Email").FillAsync(email);
        await page.GetByLabel("Password").FillAsync("e2e-password-1234");
        await page.GetByRole(AriaRole.Button, new() { Name = "Create account" }).ClickAsync();
        await page.GetByPlaceholder("Say something…").WaitForAsync();
        return (page, email);
    }

    public async Task<long> CountAsync(string sql, params object[] args)
    {
        await using var cmd = Db.CreateCommand(sql);
        foreach (var a in args)
            cmd.Parameters.Add(new NpgsqlParameter { Value = a });
        return Convert.ToInt64(await cmd.ExecuteScalarAsync(), System.Globalization.CultureInfo.InvariantCulture);
    }

    public async Task<long> WaitCountAsync(string sql, long atLeast, params object[] args)
    {
        var deadline = DateTime.UtcNow.AddSeconds(30);
        long n;
        while ((n = await CountAsync(sql, args)) < atLeast && DateTime.UtcNow < deadline)
            await Task.Delay(250);
        return n;
    }

    public string ServerLog
    {
        get
        {
            lock (serverLog)
                return serverLog.ToString();
        }
    }

    private Process StartServer(string connectionString, Uri baseUrl)
    {
        var dll = Environment.GetEnvironmentVariable("AIJADE_E2E_SERVER_DLL") is { Length: > 0 } overridden
            ? overridden
            : typeof(E2EHost).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>().Single(a => a.Key == "AijadeServerDll").Value!;
        if (!File.Exists(dll))
            throw new FileNotFoundException("the server build output was not found; build tests/Aijade.E2E first", dll);
        var psi = new ProcessStartInfo("dotnet") { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false, WorkingDirectory = Path.GetDirectoryName(dll)! };
        psi.ArgumentList.Add(dll);
        psi.Environment["ASPNETCORE_ENVIRONMENT"] = "Development";
        psi.Environment["ASPNETCORE_URLS"] = baseUrl.ToString().TrimEnd('/');
        psi.Environment["DATABASE_URL"] = connectionString;
        psi.Environment["Aijade__Role"] = "all";
        psi.Environment[$"Auth__StaticTokens__{AdminToken}"] = AdminId;
        psi.Environment["DataProtection__KeysDir"] = Path.Combine(Path.GetTempPath(), "aijade-e2e-dp-keys");
        psi.Environment["Logging__LogLevel__Default"] = "Warning";
        if (MmdDir is { } models)
            psi.Environment["Aijade__ModelsDir"] = models;
        var p = Process.Start(psi) ?? throw new InvalidOperationException("could not start the server");
        void Capture(object? _, DataReceivedEventArgs e)
        {
            if (e.Data is null)
                return;
            lock (serverLog)
                serverLog.AppendLine(e.Data);
        }
        p.OutputDataReceived += Capture;
        p.ErrorDataReceived += Capture;
        p.BeginOutputReadLine();
        p.BeginErrorReadLine();
        return p;
    }

    private async Task WaitHealthyAsync()
    {
        using var http = new HttpClient { BaseAddress = BaseUrl, Timeout = TimeSpan.FromSeconds(2) };
        var deadline = DateTime.UtcNow.AddSeconds(60);
        while (DateTime.UtcNow < deadline)
        {
            if (server!.HasExited)
                throw new InvalidOperationException($"the server exited with code {server.ExitCode}:\n{ServerLog}");
            try
            {
                using var res = await http.GetAsync("/healthz");
                if (res.IsSuccessStatusCode)
                    return;
            }
            catch (HttpRequestException)
            {
            }
            catch (TaskCanceledException)
            {
            }
            await Task.Delay(250);
        }
        throw new TimeoutException($"the server did not become healthy:\n{ServerLog}");
    }

    private static int FreePort()
    {
        using var l = new TcpListener(IPAddress.Loopback, 0);
        l.Start();
        return ((IPEndPoint)l.LocalEndpoint).Port;
    }

    /// <summary>postgres://user:pass@host:port/db → Npgsql key/value form (a key/value string passes through).</summary>
    private static string NormalizeConnectionString(string url)
    {
        if (!url.StartsWith("postgres", StringComparison.Ordinal))
            return url;
        var u = new Uri(url);
        var userInfo = u.UserInfo.Split(':', 2);
        return new NpgsqlConnectionStringBuilder
        {
            Host = u.Host,
            Port = u.Port > 0 ? u.Port : 5432,
            Username = Uri.UnescapeDataString(userInfo[0]),
            Password = userInfo.Length > 1 ? Uri.UnescapeDataString(userInfo[1]) : null,
            Database = u.AbsolutePath.Trim('/'),
        }.ConnectionString;
    }

    public async ValueTask DisposeAsync()
    {
        if (Browser is not null)
            await Browser.DisposeAsync();
        playwright?.Dispose();
        if (server is { HasExited: false })
        {
            server.Kill(entireProcessTree: true);
            await server.WaitForExitAsync();
        }
        server?.Dispose();
        if (upstream is not null)
            await upstream.DisposeAsync();
        if (Db is not null)
            await Db.DisposeAsync();
        if (adminConnection is not null && database is not null)
        {
            NpgsqlConnection.ClearAllPools();
            await using var conn = new NpgsqlConnection(adminConnection);
            await conn.OpenAsync();
            await using var cmd = new NpgsqlCommand($"DROP DATABASE IF EXISTS {database} WITH (FORCE)", conn);
            await cmd.ExecuteNonQueryAsync();
        }
    }
}

/// <summary>
/// An OpenAI-compatible upstream that streams a fixed reply. The reply opens with an expression marker, which the UI must
/// lift out of the text and send to the stage; the request bodies are kept so tests can check what the client sent.
/// </summary>
public sealed class FakeUpstream
{
    public const string Reply = "Nice to meet you! I will remember that you like jasmine tea.";

    public const string DrawingReply = "Here is your picture!";

    public const string VisionDescription = "A small square of solid colour.";

    public const string ChessComment = "Let us see where this goes.";

    public const string Transcript = "hello from the server recognizer";

    public List<(string Mime, long Bytes)> Transcriptions { get; } = [];

    public const string DrawingPrompt = "a calico cat asleep on a sunny windowsill";

    /// <summary>A 1×1 PNG, the "drawing".</summary>
    public const string PngBase64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

    private readonly List<JsonNode> requests = [];
    private readonly List<string> authorizations = [];

    /// <summary>The Authorization header of each upstream call, to check which key the gateway used.</summary>
    public IReadOnlyList<string> Authorizations
    {
        get
        {
            lock (requests)
                return [.. authorizations];
        }
    }

    public IReadOnlyList<JsonNode> Requests
    {
        get
        {
            lock (requests)
                return [.. requests];
        }
    }

    /// <summary>Only the streamed chat turns (the learning loop also calls the model, non-streaming, in the background).</summary>
    public IReadOnlyList<JsonNode> ChatRequests => [.. Requests.Where(r => r["stream"]?.GetValue<bool>() == true)];

    public WebApplication Build()
    {
        var b = WebApplication.CreateSlimBuilder();
        b.WebHost.UseUrls("http://127.0.0.1:0");
        b.Logging.ClearProviders();
        var app = b.Build();
        app.MapPost("/v1/audio/transcriptions", async (HttpContext c) =>
        {
            var form = await c.Request.ReadFormAsync(c.RequestAborted);
            lock (requests)
                Transcriptions.Add((form.Files["file"]?.ContentType ?? "", form.Files["file"]?.Length ?? 0));
            return Results.Json(new JsonObject { ["text"] = Transcript });
        });
        app.MapPost("/v1/images/generations", () => Results.Json(new JsonObject { ["data"] = new JsonArray(new JsonObject { ["b64_json"] = PngBase64 }) }));
        app.MapPost("/v1/chat/completions", async (HttpContext c) =>
        {
            var body = await JsonNode.ParseAsync(c.Request.Body, cancellationToken: c.RequestAborted);
            lock (requests)
            {
                requests.Add(body!);
                authorizations.Add(c.Request.Headers.Authorization.ToString());
            }
            if (body!["stream"]?.GetValue<bool>() != true && body.ToJsonString().Contains("\"image_url\"", StringComparison.Ordinal))
            {
                // A vision request: describe the frame.
                await c.Response.WriteAsJsonAsync(new JsonObject
                {
                    ["id"] = "fake-vision", ["model"] = "fake",
                    ["choices"] = new JsonArray(new JsonObject { ["index"] = 0, ["message"] = new JsonObject { ["role"] = "assistant", ["content"] = VisionDescription }, ["finish_reason"] = "stop" }),
                }, c.RequestAborted);
                return;
            }
            var lastUserText = body["messages"]!.AsArray().LastOrDefault(m => m?["role"]?.GetValue<string>() == "user")?["content"]?.ToString() ?? "";
            if (body["stream"]?.GetValue<bool>() != true && lastUserText.Contains("We are playing chess", StringComparison.Ordinal))
            {
                // A chess move: the first legal move offered, with a comment.
                var legal = lastUserText.Split('\n').First(l => l.TrimStart().StartsWith("Your legal moves:", StringComparison.Ordinal)).Split(':')[1].Split(',')[0].Trim();
                await c.Response.WriteAsJsonAsync(new JsonObject
                {
                    ["choices"] = new JsonArray(new JsonObject { ["index"] = 0, ["message"] = new JsonObject { ["role"] = "assistant", ["content"] = $"[[move:{legal}]] {ChessComment}" } }),
                }, c.RequestAborted);
                return;
            }
            if (body["stream"]?.GetValue<bool>() != true)
            {
                // The learning loop's background questions (is this a teachable moment?) get a plain "no".
                await c.Response.WriteAsJsonAsync(new JsonObject
                {
                    ["id"] = "fake", ["model"] = "fake",
                    ["choices"] = new JsonArray(new JsonObject { ["index"] = 0, ["message"] = new JsonObject { ["role"] = "assistant", ["content"] = """{"shouldCreate":false,"rationale":"chit-chat"}""" }, ["finish_reason"] = "stop" }),
                    ["usage"] = new JsonObject { ["prompt_tokens"] = 5, ["completion_tokens"] = 5 },
                }, c.RequestAborted);
                return;
            }
            c.Response.ContentType = "text/event-stream";
            var lastUser = body["messages"]!.AsArray().LastOrDefault(m => m?["role"]?.GetValue<string>() == "user")?["content"]?.GetValue<string>() ?? "";
            string[] chunks = lastUser.Contains("draw", StringComparison.OrdinalIgnoreCase)
                ? [$"{DrawingReply} [[draw: {DrawingPrompt[..10]}", $"{DrawingPrompt[10..]}]]"]
                : ["[[emote:jo", "y]]Nice to meet you! ", "I will remember that ", "you like jasmine tea."];
            foreach (var chunk in chunks)
            {
                var delta = new JsonObject { ["choices"] = new JsonArray(new JsonObject { ["index"] = 0, ["delta"] = new JsonObject { ["content"] = chunk } }) };
                await c.Response.WriteAsync($"data: {delta.ToJsonString()}\n\n", c.RequestAborted);
                await c.Response.Body.FlushAsync(c.RequestAborted);
                await Task.Delay(40, c.RequestAborted);
            }
            await c.Response.WriteAsync("data: {\"choices\":[],\"usage\":{\"prompt_tokens\":12,\"completion_tokens\":14}}\n\n", c.RequestAborted);
            await c.Response.WriteAsync("data: [DONE]\n\n", c.RequestAborted);
        });
        return app;
    }
}
