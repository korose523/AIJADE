using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Settings;

namespace Aijade.Client.Companion;

/// <summary>When she sends a picture: MOSAIC's defaults (mosaic/life/share.py, DEFAULTS).</summary>
public sealed record SelfieRules(int PerDay = 2, double FromHour = 10, double ToHour = 21.5, double MinGapHours = 3, double OwnerAwayMin = 30,
    double ChancePerMinute = .05)
{
    public static SelfieRules Default { get; } = new();
}

/// <summary>
/// Her selfies now and then (ADR-003, migration batch 2; MOSAIC owner 2026-11-01: "给她配个手机，让她学会自拍并时不时…发照片给我").
/// When: AIJADE's port of <c>due</c> in MOSAIC's mosaic/life/share.py (r601), checked case by case against vectors its own
/// module made (configs/companion/selfie-vectors.json): at most two a day, between 10:00 and 21:30 and never in her night,
/// three hours apart, only once the user has left her alone half an hour (while they are there they can see her), and then
/// by chance each minute, so that it comes now and then, not by the clock. MOSAIC also waits until she has settled
/// somewhere in her home; AIJADE's stage has no home, so that rule has no counterpart. The picture is taken by the stage
/// (tools/mmd-bundle/selfie-shot.js) and put in the open chat as her line; its words say only what is true.
/// </summary>
public static class Selfies
{
    /// <summary>Her night (MOSAIC's mosaic/life/model.py NIGHT): from 23:00 to 07:00 nothing is done and nothing is said.</summary>
    public const int NightFrom = 23, NightTo = 7;

    /// <summary>The local hour with its minutes (MOSAIC's model.hour: seconds are not counted).</summary>
    public static double Hour(double now, TimeZoneInfo? zone = null)
    {
        var t = TimeZoneInfo.ConvertTime(DateTimeOffset.FromUnixTimeMilliseconds((long)Math.Round(now * 1000)), zone ?? TimeZoneInfo.Local);
        return t.Hour + t.Minute / 60.0;
    }

    /// <summary>
    /// (true, why) when a picture now would be "now and then", else (false, why), in MOSAIC's order and words.
    /// <paramref name="rules"/> null means the user has not switched selfies on; <paramref name="takenToday"/> are today's
    /// pictures, oldest first (epoch seconds); <paramref name="ownerAgoS"/> is how long ago the user last spoke (null: not yet);
    /// <paramref name="random"/> is this minute's draw in [0, 1).
    /// </summary>
    public static (bool Due, string Why) Due(SelfieRules? rules, IReadOnlyList<double> takenToday, double now, double? ownerAgoS, double random, TimeZoneInfo? zone = null)
    {
        if (rules is null)
            return (false, "no channel set");
        var h = Hour(now, zone);
        if (h >= NightFrom || h < NightTo || !(rules.FromHour <= h && h < rules.ToHour))
            return (false, "not the hours for pictures");
        if (ownerAgoS is { } ago && ago < 60 * rules.OwnerAwayMin)
            return (false, "the owner is around");
        if (takenToday.Count >= rules.PerDay)
            return (false, "today's pictures are sent");
        if (takenToday.Count > 0 && now - takenToday[^1] < 3600 * rules.MinGapHours)
            return (false, "a picture went not long ago");
        if (random >= rules.ChancePerMinute)
            return (false, "not this minute");
        return (true, "now and then");
    }

    /// <summary>The pictures taken on the local day of <paramref name="now"/>, oldest first.</summary>
    public static IReadOnlyList<double> Today(IEnumerable<double> taken, double now, TimeZoneInfo? zone = null)
    {
        DateOnly Day(double t) => DateOnly.FromDateTime(TimeZoneInfo.ConvertTime(DateTimeOffset.FromUnixTimeMilliseconds((long)Math.Round(t * 1000)), zone ?? TimeZoneInfo.Local).DateTime);
        var today = Day(now);
        return [.. taken.Where(t => Day(t) == today).Order()];
    }

    /// <summary>Whether a stored message is a selfie she sent (meta.selfie).</summary>
    public static bool IsSelfie(StoredMessage m) => m.Role == "assistant" && m.Meta?["selfie"] is JsonObject;

    /// <summary>
    /// Keep the picture for the account and put it in the chat as her line: a line she began (<see cref="Initiative.ProactiveMeta"/>,
    /// so speaking first counts it), its words the caption, meta.image the stored picture, meta.selfie the stage that took it.
    /// </summary>
    public static async Task<StoredMessage> ShareAsync(AijadeApi api, string chatId, byte[] picture, string caption, string renderer, CancellationToken ct = default)
    {
        var image = await api.UploadSelfieAsync(picture, caption, renderer, ct).ConfigureAwait(false);
        return await api.AppendMessageAsync(chatId, "assistant", caption, new JsonObject
        {
            [Initiative.ProactiveMeta] = true,
            ["image"] = new JsonObject { ["id"] = image.Id, ["mime"] = image.Mime, ["prompt"] = image.Prompt },
            ["selfie"] = new JsonObject { ["renderer"] = renderer },
        }, ct).ConfigureAwait(false);
    }
}

/// <summary>
/// When this device's stage sent her pictures, per account, in the platform key-value store beside the settings (no server
/// table: the server's migration count is a number one of the manuscripts reports). Two days are kept.
/// </summary>
public sealed class SelfieStore(IKeyValueStore store, Func<string> account)
{
    public const string KeyPrefix = "aijade.selfies.";
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    private string Key => KeyPrefix + account();

    public async Task<List<double>> LoadAsync()
    {
        var json = await store.GetAsync(Key).ConfigureAwait(false);
        if (string.IsNullOrEmpty(json))
            return [];
        try
        {
            return JsonSerializer.Deserialize<List<double>>(json, Json) ?? [];
        }
        catch (JsonException)
        {
            return [];
        }
    }

    public async Task RecordAsync(double at)
    {
        var taken = await LoadAsync().ConfigureAwait(false);
        taken.Add(at);
        await store.SetAsync(Key, JsonSerializer.Serialize(taken.Where(t => t > at - 2 * 86400).Order().ToList(), Json)).ConfigureAwait(false);
    }
}
