using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;

using Aijade.Client.Companion;
using Aijade.Client.Settings;
using Aijade.Integrations;

using Microsoft.Extensions.Configuration;

namespace Aijade.Bots;

/// <summary>Product settings and a durable notebook per platform/person/character, never one shared relationship.</summary>
public sealed class CompanionConfiguration
{
    private readonly ConcurrentDictionary<string, CompanionExperience> companions = new(StringComparer.Ordinal);
    private readonly IKeyValueStore store;
    private readonly CompanionWeather weather = new(new HttpClient { Timeout = TimeSpan.FromSeconds(10) });
    public CompanionProfile Profile { get; }
    private readonly Aijade.Client.Api.AijadeApi api;
    private readonly ConcurrentDictionary<string, byte> imported = new(StringComparer.Ordinal);

    public CompanionConfiguration(IConfiguration config, Aijade.Client.Api.AijadeApi api)
    {
        this.api = api;
        Profile = config.GetSection("Companion").Get<CompanionProfile>() ?? new();
        _ = Profile.Zone;
        var state = config["Bridge:StateFile"] is { Length: > 0 } path ? path : "aijade-bots-state.json";
        store = new NotebookFiles(state + ".companion");
        CharacterId = config["Bridge:CharacterId"] ?? "default";
    }

    private string CharacterId { get; }

    public CompanionExperience For(ChannelMessage m)
    {
        var key = $"{m.Platform}:{m.AuthorId}:{CharacterId}";
        return companions.GetOrAdd(key, _ => new(new CompanionNotebook(store, key), () => Profile, weather, key));
    }

    public async Task PairAsync(ChannelMessage message, string code, CancellationToken ct)
        => _ = await new CompanionSync(api).PairAsync(code.Trim(), message.AuthorId, ct).ConfigureAwait(false);

    public async Task<CompanionChatContext?> ForAsync(ChannelMessage message, CancellationToken ct)
    {
        if (message.Platform != "qq" || !message.IsDirect) return null;
        var actor = await api.SessionAsync(ct).ConfigureAwait(false) ?? throw new InvalidOperationException("The bot account is not signed in");
        var own = new CompanionSync(api);
        var link = await own.ResolveAsync(message.AuthorId, ct).ConfigureAwait(false);
        var sync = link is null ? own : new CompanionSync(api, link.Id);
        var state = await sync.CurrentAsync(ct).ConfigureAwait(false);
        var legacyKey = $"{message.Platform}:{message.AuthorId}:{CharacterId}";
        if (state.OwnerId == actor.Id && imported.TryAdd(legacyKey, 0))
        {
            try
            {
                using var legacy = new CompanionNotebook(store, legacyKey);
                await sync.ImportAsync(CharacterId == "default" ? null : CharacterId, "bot:" + legacyKey, Profile, await legacy.ReadAsync(ct: ct).ConfigureAwait(false), activate: true, ct: ct).ConfigureAwait(false);
                state = await sync.CurrentAsync(ct).ConfigureAwait(false);
            }
            catch (Aijade.Client.Api.AijadeApiException e) when (e.Status == 404) { }
            catch { imported.TryRemove(legacyKey, out _); throw; }
        }
        var notebook = new SyncedCompanionNotebook(sync, state.CharacterId, state);
        var identity = state.OwnerId + ":" + (state.CharacterId ?? "default");
        var experience = new CompanionExperience(notebook, () => notebook.Latest!.RuntimeProfile, weather, identity);
        return new(experience, state.Character, identity, state.OwnerId == actor.Id);
    }

    private sealed class NotebookFiles(string directory) : IKeyValueStore
    {
        private string PathFor(string key) => Path.Combine(directory, Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(key))) + ".json");
        public async ValueTask<string?> GetAsync(string key) => File.Exists(PathFor(key)) ? await File.ReadAllTextAsync(PathFor(key)).ConfigureAwait(false) : null;
        public async ValueTask SetAsync(string key, string value)
        {
            Directory.CreateDirectory(directory);
            var path = PathFor(key);
            var temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            await File.WriteAllTextAsync(temp, value).ConfigureAwait(false);
            File.Move(temp, path, overwrite: true);
        }
        public ValueTask RemoveAsync(string key) { File.Delete(PathFor(key)); return ValueTask.CompletedTask; }
    }
}
