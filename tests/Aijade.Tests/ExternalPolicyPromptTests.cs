using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;

using Microsoft.AspNetCore.TestHost;

namespace Aijade.Tests;

/// <summary>Observes delivery of actual external API results through the common product prompt budget.</summary>
public sealed class ExternalPolicyPromptTests
{
    private static readonly JsonSerializerOptions ReceiptOptions = new() { WriteIndented = true };
    private sealed class ExternalContext : IContextProvider
    {
        public IReadOnlyList<PromptMemory> Items { get; set; } = [];
        public Task<string?> SupplyAsync(TurnContext turn, CancellationToken ct) => Task.FromResult(Items.Count == 0 ? null :
            ProductPromptObservation.Header + string.Join("\n", Items.Select(i => "- " + i.Content)));
    }

    [Fact]
    public async Task Every_external_policy_result_reaches_an_observed_request()
    {
        var ct = TestContext.Current.CancellationToken;
        if (Environment.GetEnvironmentVariable("AIJADE_P3_EXTERNAL_INPUT") is not { Length: > 0 } input
            || Environment.GetEnvironmentVariable("AIJADE_P3_EXTERNAL_OUTPUT") is not { Length: > 0 } output)
        {
            Assert.Skip("set AIJADE_P3_EXTERNAL_INPUT and AIJADE_P3_EXTERNAL_OUTPUT for actual external prompt delivery");
            return;
        }
        var plan = Environment.GetEnvironmentVariable("AIJADE_P3_POLICY_PLAN");
        Assert.Equal(40, plan!.Length);
        var keys = new HashSet<string>(StringComparer.Ordinal);
        var rows = 0;
        var unknown = 0;
        var truncated = 0;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        using var tap = new PolicyTap(host.App.GetTestServer().CreateHandler());
        using var http = new HttpClient(tap) { BaseAddress = host.Client.BaseAddress };
        var tokens = new MemoryTokenStore(); await tokens.SetAsync(ServerTestHost.Token);
        var api = new AijadeApi(http, tokens);
        var context = new ExternalContext();
        var budget = new PromptBudget();
        var runtime = CompanionRuntime.Create(api, [new("memory", context)], new OrchestratorOptions { PromptBudget = budget });
        var chat = await api.CreateChatAsync(null, "external policy prompt capture", ct);
        await using var file = File.OpenRead(input);
        await using var zip = new GZipStream(file, CompressionMode.Decompress);
        using var reader = new StreamReader(zip);
        await using var target = new FileStream(output, FileMode.CreateNew);
        await using var compressed = new GZipStream(target, CompressionLevel.SmallestSize);
        await using var writer = new StreamWriter(compressed);
        while (await reader.ReadLineAsync(ct) is { } line)
        {
            var row = JsonNode.Parse(line)!;
            var key = $"{row["system"]}:{row["c"]}:{row["q"]}:{row["policy"]}:{row["scorer"]}";
            Assert.True(keys.Add(key), "duplicate external policy input");
            context.Items = [.. row["delivered"]!.AsArray().Take(5).Select(i => new PromptMemory(i!["source"]!.GetValue<string>(), i["content"]!.GetValue<string>()))];
            tap.Reset();
            var completed = false;
            await foreach (var item in runtime.SendAsync(chat.Id, null, [], row["question"]!.GetValue<string>(), "p3-external-policy", ct))
                completed |= item is TurnCompleted;
            Assert.True(completed);
            Assert.Empty(tap.Searches);
            var observation = ProductPromptObservation.Observe(tap.SystemMessage, context.Items);
            unknown += observation.Identifiable ? 0 : 1;
            truncated += observation.Truncated ? 1 : 0;
            var gold = row["gold"]!.AsArray().Select(i => i!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
            var result = new JsonObject
            {
                ["key"] = key, ["system"] = row["system"]!.DeepClone(), ["c"] = row["c"]!.DeepClone(), ["q"] = row["q"]!.DeepClone(),
                ["policy"] = row["policy"]!.DeepClone(), ["scorer"] = row["scorer"]!.DeepClone(),
                ["plannedIds"] = new JsonArray([.. context.Items.Select(i => JsonValue.Create(i.Id))]),
                ["observedIds"] = observation.Identifiable ? new JsonArray([.. observation.FullItemIds.Select(i => JsonValue.Create(i))]) : null,
                ["promptGold"] = observation.Identifiable ? observation.FullItemIds.Count(gold.Contains) : null,
                ["rawSystem"] = tap.SystemMessage, ["systemSha256"] = observation.SystemSha256, ["state"] = observation.State,
                ["identifiable"] = observation.Identifiable, ["truncated"] = observation.Truncated, ["completed"] = completed,
            };
            await writer.WriteLineAsync(result.ToJsonString().AsMemory(), ct);
            rows++;
            if (rows % 100 == 0)
            {
                await writer.FlushAsync(ct);
                await File.WriteAllTextAsync(output + ".progress.json", JsonSerializer.Serialize(new { rows, unknown, truncated }), ct);
            }
        }
        Assert.Equal(7944, rows);
        var assembly = typeof(ExternalPolicyPromptTests).Assembly;
        await File.WriteAllTextAsync(output + ".receipt.json", JsonSerializer.Serialize(new
        {
            schema = "aijade.p3.policy.external-prompts.v1", rows, unknown, truncated, budget, planCommit = plan,
            inputSha256 = Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(input))),
            codeCommit = Environment.GetEnvironmentVariable("AIJADE_GIT_COMMIT"),
            assemblySha256 = Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(assembly.Location))),
            informationalVersion = assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()!.InformationalVersion,
            newModelCalls = 0, scope = "actual external write/read results, shared single-turn memory prompt budget, no generated answer",
        }, ReceiptOptions), ct);
    }
}
