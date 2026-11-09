using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

using Aijade.Client.Chat;
using Aijade.Client.Settings;

namespace Aijade.Client.Companion;

/// <summary>The companion's fictional setting. A real city is used only after the owner chooses it.</summary>
public sealed record CompanionProfile
{
    public bool Enabled { get; init; } = true;
    public string Home { get; init; } = "窗边的小屋";
    public string City { get; init; } = "";
    public string TimeZone { get; init; } = "";
    public double? Latitude { get; init; }
    public double? Longitude { get; init; }
    public bool Weather { get; init; }
    public bool NaturalPacing { get; init; }
    public string Appearance { get; init; } = "艾娅德，保持同一个角色的脸型、发色与眼睛设定";
    public string Interests { get; init; } = "读书,做饭,散步,音乐,画画";
    public string MusicPreferences { get; init; } = "轻音乐,流行音乐";
    public string Friends { get; init; } = "书店的朋友,邻居";
    public string Hairstyles { get; init; } = "自然披发,低马尾,半扎发";

    public TimeZoneInfo Zone => string.IsNullOrWhiteSpace(TimeZone) ? TimeZoneInfo.Local : TimeZoneInfo.FindSystemTimeZoneById(TimeZone);

    public void ValidateLocation()
    {
        _ = Zone;
        if (Latitude.HasValue != Longitude.HasValue)
            throw new ArgumentException("Set both latitude and longitude, or leave both empty");
        if (Latitude is { } lat && (!double.IsFinite(lat) || lat is < -90 or > 90))
            throw new ArgumentException("Latitude must be between -90 and 90");
        if (Longitude is { } lon && (!double.IsFinite(lon) || lon is < -180 or > 180))
            throw new ArgumentException("Longitude must be between -180 and 180");
        if (Weather && Latitude is null)
            throw new ArgumentException("Choose a city or enter coordinates before enabling weather");
    }
}

/// <summary>Owner-supplied media: sticker, outfit reference or a recording the character can sing.</summary>
public sealed record CompanionAsset(string Id, string Kind, string Name, string Data, string Description = "", string Season = "all", string Emotion = "neutral", string Attribution = "");

public sealed record RelationshipState
{
    public double Affection { get; init; } = 30;
    public double Mood { get; init; } = .2;
    public DateTimeOffset? Updated { get; init; }
    public DateTimeOffset? LastGain { get; init; }
    public string? LastTurn { get; init; }
    public int Interactions { get; init; }
    public string Reason { get; init; } = "慢慢认识彼此";
    public string Stage => Affection < 25 ? "初识" : Affection < 50 ? "熟悉" : Affection < 75 ? "亲近" : "信赖";
}

public sealed record CompanionNotebookData
{
    public RelationshipState Relationship { get; init; } = new();
    public IReadOnlyList<CompanionAsset> Assets { get; init; } = [];
    public IReadOnlyList<string> Shared { get; init; } = [];
}

/// <summary>Private, persistent state, scoped by account/character in the UI and person/character in bots.</summary>
public sealed class CompanionNotebook(IKeyValueStore store, string scope) : IDisposable, ICompanionNotebook
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private readonly SemaphoreSlim gate = new(1, 1);
    private string Key => "aijade.companion." + scope;
    public void Dispose() => gate.Dispose();

    public async Task<CompanionNotebookData> ReadAsync(bool includeMedia = false, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        var text = await store.GetAsync(Key).ConfigureAwait(false);
        return text is null ? new() : JsonSerializer.Deserialize<CompanionNotebookData>(text, Json)
            ?? throw new JsonException("The companion notebook is empty");
    }

    public async Task UpdateAsync(Func<CompanionNotebookData, CompanionNotebookData> update, CancellationToken ct = default)
    {
        await gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            var next = update(await ReadAsync(ct: ct).ConfigureAwait(false));
            await store.SetAsync(Key, JsonSerializer.Serialize(next, Json)).ConfigureAwait(false);
        }
        finally
        {
            gate.Release();
        }
    }

    public Task AddAsync(CompanionAsset asset, CancellationToken ct = default)
    {
        CompanionMedia.Validate(asset);
        return UpdateAsync(data =>
        {
            if (data.Assets.Count >= 32 && data.Assets.All(a => a.Id != asset.Id))
                throw new InvalidOperationException("The collection is full; remove an item before adding another");
            return data with { Assets = [.. data.Assets.Where(a => a.Id != asset.Id), asset] };
        }, ct);
    }

    public Task RemoveAsync(string id, CancellationToken ct = default) => UpdateAsync(d => d with { Assets = [.. d.Assets.Where(a => a.Id != id)] }, ct);
    public async Task<CompanionAsset?> AssetAsync(string id, CancellationToken ct = default) => (await ReadAsync(ct: ct).ConfigureAwait(false)).Assets.FirstOrDefault(a => a.Id == id);
    public Task ObserveAsync(TurnContext turn, DateTimeOffset now, CancellationToken ct = default) => UpdateAsync(d => d with
    {
        Relationship = CompanionRelationship.Observe(d.Relationship, turn.UserText, turn.UserMessageId ?? $"{turn.ChatId}:{turn.History.Count}:{turn.UserText}", now),
    }, ct);
}

public sealed record LifeMoment(string Id, DateTimeOffset LocalTime, string Place, string Activity, string Interest, string Friend, string Hair, CompanionAsset? Outfit)
{
    public string Describe() => $"虚拟生活 · {LocalTime:yyyy-MM-dd HH:mm} · {Place} · {Activity}；今天喜欢聊{Interest}；发型：{Hair}；穿搭：{Outfit?.Description ?? Outfit?.Name ?? "日常便服"}";
}

/// <summary>A stable daily schedule. It is explicitly fictional and never a receipt of physical execution.</summary>
public static class CompanionWorld
{
    private static int Pick(string key, int count) => (int)(System.Buffers.Binary.BinaryPrimitives.ReadUInt32LittleEndian(SHA256.HashData(Encoding.UTF8.GetBytes(key))) % count);

    private static string Select(string values, string key, string fallback)
    {
        var all = values.Split([',', '，'], StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
        return all.Length == 0 ? fallback : all[Pick(key, all.Length)];
    }

    public static LifeMoment Now(CompanionProfile p, IReadOnlyList<CompanionAsset> assets, DateTimeOffset now, string identity)
    {
        var local = TimeZoneInfo.ConvertTime(now, p.Zone);
        var key = $"{identity}:{local:yyyy-MM-dd}";
        var hour = local.Hour;
        var slot = hour < 7 ? "night" : hour < 9 ? "breakfast" : hour < 12 ? "morning" : hour < 14 ? "lunch" : hour < 18 ? "afternoon" : hour < 21 ? "evening" : "rest";
        var interest = Select(p.Interests, key + ":interest", "读书");
        var friend = Select(p.Friends, key + ":friend", "一位虚拟朋友");
        var (place, activity) = slot switch
        {
            "night" => (p.Home, "休息"),
            "breakfast" => (p.Home, "做早餐，整理今天的安排"),
            "morning" => ("附近的书店", $"看书，和{friend}聊几句"),
            "lunch" => (p.Home, "准备午饭"),
            "afternoon" => ("附近的公园", $"散步，想一想{interest}"),
            "evening" => (p.Home, $"做晚饭，练习{interest}"),
            _ => (p.Home, "整理今天的日记，准备休息"),
        };
        var month = local.Month;
        // Seasons follow the configured latitude, not the user's language or the host's locale.
        if (p.Latitude < 0)
            month = (month + 5) % 12 + 1;
        var season = month is 12 or 1 or 2 ? "winter" : month < 6 ? "spring" : month < 9 ? "summer" : "autumn";
        var clothes = assets.Where(a => a.Kind == "outfit" && (a.Season == "all" || a.Season == season)).OrderBy(a => a.Id, StringComparer.Ordinal).ToList();
        return new LifeMoment(key + ":" + slot, local, place, activity, interest, friend,
            Select(p.Hairstyles, key + ":hair", "自然披发"), clothes.Count == 0 ? null : clothes[Pick(key + ":outfit", clothes.Count)]);
    }

    public static string PhotoPrompt(string kind, CompanionProfile profile, LifeMoment moment, WeatherReading? weather) =>
        $"A fictional character's {kind} photo, candid phone photography, consistent character design. " +
        $"Character: {profile.Appearance}. Hair: {moment.Hair}. Clothing: {moment.Outfit?.Description ?? moment.Outfit?.Name ?? "casual everyday clothes"}. " +
        $"Setting: {profile.City} {moment.Place}; local time {moment.LocalTime:yyyy-MM-dd HH:mm}; activity: {moment.Activity}. " +
        (weather is null ? "Weather is unknown: do not invent real weather. " : $"Weather context: {weather.Describe()}. ") +
        (kind == "landscape" ? "Landscape view, no person in the frame. " : kind == "snapshot" ? "An incidental detail of this activity. " : "Arm's length selfie composition. ") +
        "No watermark or text. This is a generated illustration, not evidence of a real visit.";
}

/// <summary>Small, auditable relationship changes; silence is not a loss of affection.</summary>
public static class CompanionRelationship
{
    private static readonly string[] KindWords = ["谢谢", "喜欢你", "辛苦了", "关心", "照顾", "thank you", "love you"];
    private static readonly string[] HurtWords = ["讨厌你", "我讨厌你", "我不喜欢你", "滚开", "你滚开", "你去死", "shut up", "hate you", "i hate you"];
    public static RelationshipState Observe(RelationshipState before, string text, string turnId, DateTimeOffset now)
    {
        if (before.LastTurn == turnId)
            return before;
        var mood = CompanionLife.Fade(before.Mood, before.Updated is { } at ? (now - at).TotalHours : 0);
        var praise = KindWords.Any(s => text.Contains(s, StringComparison.OrdinalIgnoreCase));
        // Do not treat a user reporting somebody else's hurtful words or describing their own distress as an attack.
        var hurt = HurtWords.Contains(text.Trim().TrimEnd('。', '！', '!', '.'), StringComparer.OrdinalIgnoreCase);
        var spaced = before.LastGain is null || now - before.LastGain >= TimeSpan.FromMinutes(10);
        var delta = hurt ? -1 : spaced ? (praise ? 1 : .2) : 0;
        return before with
        {
            Affection = Math.Clamp(before.Affection + delta, 0, 100),
            Mood = Math.Clamp(mood + (hurt ? -.12 : praise ? .12 : .04), -1, 1),
            Updated = now, LastGain = spaced ? now : before.LastGain, LastTurn = turnId, Interactions = before.Interactions + 1,
            Reason = hurt ? "这句话让她有些难过" : praise ? "收到关心与善意" : "一起聊了一会儿",
        };
    }
}

/// <summary>Shared by the Web/MAUI chat and private bot chats. Research apparatus never constructs it.</summary>
public sealed class CompanionExperience(ICompanionNotebook notebook, Func<CompanionProfile> profile, CompanionWeather weather, string identity, TimeProvider? time = null)
    : IContextProvider, ITurnObserver
{
    private readonly TimeProvider clock = time ?? TimeProvider.System;
    public ICompanionNotebook Notebook => notebook;
    public CompanionProfile Profile => profile();

    public async Task<(LifeMoment Moment, RelationshipState Relationship, WeatherReading? Weather)> SnapshotAsync(CancellationToken ct = default)
    {
        var data = await notebook.ReadAsync(ct: ct).ConfigureAwait(false);
        var p = profile();
        var now = clock.GetUtcNow();
        var relationship = data.Relationship with { Mood = CompanionLife.Fade(data.Relationship.Mood, data.Relationship.Updated is { } at ? (now - at).TotalHours : 0) };
        return (CompanionWorld.Now(p, data.Assets, now, identity), relationship,
            p.Weather ? await weather.CurrentAsync(p, ct).ConfigureAwait(false) : null);
    }

    public async Task<string?> SupplyAsync(TurnContext turn, CancellationToken ct)
    {
        try { return await DescribeAsync(ct).ConfigureAwait(false); }
#pragma warning disable CA1031 // companion life is optional; storage failure must not prevent ordinary chat
        catch (Exception e) when (!ct.IsCancellationRequested)
        {
            Console.Error.WriteLine($"Companion context unavailable: {e.GetType().Name}");
            return "Private companion life state is unavailable. Do not invent a saved relationship, outfit, song or real weather.";
        }
#pragma warning restore CA1031
    }

    private async Task<string?> DescribeAsync(CancellationToken ct)
    {
        var s = await SnapshotAsync(ct).ConfigureAwait(false);
        if (!profile().Enabled)
            return null;
        return $"Companion setting (fictional, not physical execution): {s.Moment.Describe()}. " +
            $"Configured city: {(string.IsNullOrWhiteSpace(profile().City) ? "not configured" : profile().City)}; time zone: {profile().Zone.Id}. " +
            $"Fictional appearance: {profile().Appearance}. " +
            $"Fictional friend: {s.Moment.Friend}. Relationship: {s.Relationship.Stage}, mood {s.Relationship.Mood.ToString("F2", CultureInfo.InvariantCulture)}. " +
            (s.Weather is null ? "Real weather is unavailable; do not guess it. " : $"Real weather source: {s.Weather.Describe()}. ") +
            "Share a small relevant detail of your own day sometimes, and have your own interests; do not repeat the setting in every reply. " +
            "You are an AI companion with a fictional life. Do not claim to be a human, to have visited a real place, or to have passed a Turing test. " +
            "Do not guilt the user for being away. Respect requests to stop, sleep or take a break. A score never creates an obligation to reply. " +
            $"Music preferences: {profile().MusicPreferences}. A preference does not mean you can sing a song. " +
            "Photos and songs are available through /photo and /sing; do not claim to have sent media unless a delivery result says so.";
    }

    public Task UserTurnAsync(TurnContext turn, CancellationToken ct) => !profile().Enabled && notebook is not SyncedCompanionNotebook
        ? Task.CompletedTask : notebook.ObserveAsync(turn, clock.GetUtcNow(), ct);

    public Task AssistantTurnAsync(TurnContext turn, string reply, CancellationToken ct) => Task.CompletedTask;
}
