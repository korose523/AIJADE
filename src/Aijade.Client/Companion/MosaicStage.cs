using System.Text.Json.Nodes;

using Aijade.Client.Api;

namespace Aijade.Client.Companion;

/// <summary>
/// A motion her MOSAIC video learner really captured (contract 1.4.0 A): the local day (YYYY-MM-DD), the motion library's
/// skill and its Chinese name, the seconds kept, and the seconds of poses the library did not have (null before the nightly
/// rebuild). The video's title and uploader are third-party content: they are read but never stored or given to a model.
/// </summary>
public sealed record LearnedMotion(string Day, string Skill, string SkillWords, double KeptSeconds, double? NovelSeconds, string VideoTitle, string Uploader, string Source);

/// <summary>
/// Her place on MOSAIC's stage, as the workbench reports it: whether the scene runs, where she is, her posture, and the
/// motions she has learned lately (newest first, at most five, as MOSAIC filters them). <paramref name="Notice"/> is the
/// workbench's last notice, for the owner's eyes only; <paramref name="SequenceRunning"/> says whether its last command line is
/// still being carried out, null when it does not say.
/// </summary>
public sealed record StageState(bool Running, string? Where, string? Posture, IReadOnlyList<LearnedMotion>? Learned = null, string? Notice = null, bool? SequenceRunning = null, string? StateKind = null, bool? RenderObserved = null, string? CharacterId = null)
{
    /// <summary>Sitting or lying, so that "get up" means something.</summary>
    public bool Seated => Posture is "sit" or "lie";

    /// <summary>Lying down: MOSAIC does not let her speak first then, and neither does AIJADE.</summary>
    public bool Lying => Posture == "lie";
}

/// <summary>
/// The chat client for the AIJADE-owned virtual scene. Legacy response fields remain readable; virtual state is not a render receipt.
/// </summary>
public sealed class CompanionStage(AijadeApi api, string? characterId = null)
{
    /// <summary>
    /// Her state, or null when the server has no stage, the account may not use it, the workbench is not running, or the
    /// server cannot be reached.
    /// </summary>
    public async Task<StageState?> StateAsync(CancellationToken ct = default)
    {
        try
        {
            if (await api.SendAsync(HttpMethod.Get, "/api/v1/stage?characterId=" + Uri.EscapeDataString(characterId ?? "default"), ct: ct).ConfigureAwait(false) is not JsonObject r || r["running"]?.GetValue<bool>() != true)
                return null;
            return new StageState(true, r["where"]?.GetValue<string>(), r["posture"]?.GetValue<string>(), Learned(r["learned"] as JsonArray),
                Text(r, "notice"), r["sequenceRunning"] is JsonValue v && v.TryGetValue<bool>(out var busy) ? busy : null,
                Text(r, "stateKind"), r["renderObserved"] is JsonValue observed && observed.TryGetValue<bool>(out var rendered) ? rendered : null, Text(r, "characterId"));
        }
        catch (Exception e) when (e is AijadeApiException or HttpRequestException || e is TaskCanceledException && !ct.IsCancellationRequested)
        {
            return null;
        }
    }

    /// <summary>The learned motions of a state reply; an item without a day, a skill name or seconds kept is left out.</summary>
    private static List<LearnedMotion> Learned(JsonArray? items) =>
        [.. (items ?? []).OfType<JsonObject>()
            .Where(m => Text(m, "day") is { Length: > 0 } && Text(m, "skill_words") is { Length: > 0 } && Number(m, "kept_seconds") > 0)
            .Select(m => new LearnedMotion(Text(m, "day")!, Text(m, "skill") ?? "", Text(m, "skill_words")!, Number(m, "kept_seconds")!.Value,
                Number(m, "novel_seconds"), Text(m, "video_title") ?? "", Text(m, "uploader") ?? "", Text(m, "source") ?? ""))];

    private static string? Text(JsonObject o, string key) =>
        o[key] is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;

    private static double? Number(JsonObject o, string key) =>
        o[key] is JsonValue v && v.TryGetValue<double>(out var d) ? d : null;

    /// <summary>Send one command line (<see cref="Stage.CommandLine"/>); a refusal comes back as <see cref="AijadeApiException"/>.</summary>
    public Task SendAsync(string commandLine, CancellationToken ct = default) =>
        api.SendAsync(HttpMethod.Post, "/api/v1/stage/command", new JsonObject { ["text"] = commandLine, ["commandId"] = Guid.NewGuid().ToString("N"), ["characterId"] = characterId ?? "default" }, ct);

    /// <summary>
    /// Follows a command line just sent until the workbench has finished it, then judges the last notice
    /// (<see cref="Stage.Outcome"/>). Unknown when it does not finish within <paramref name="limit"/> (5 minutes), or when the
    /// workbench does not say whether it is running a line. While the scene restarts or the server cannot be reached it keeps asking.
    /// </summary>
    public async Task<StageReport> FollowAsync(StageAction? action, string? noticeBefore, TimeSpan? every = null, TimeSpan? limit = null, CancellationToken ct = default)
    {
        var watch = System.Diagnostics.Stopwatch.StartNew();
        while (watch.Elapsed < (limit ?? TimeSpan.FromMinutes(5)))
        {
            if (await StateAsync(ct).ConfigureAwait(false) is { SequenceRunning: false } done)
                return new StageReport(done.StateKind == "virtual" ? StageOutcome.Unknown : Stage.Outcome(action, noticeBefore, done.Notice), done.Notice);
            await Task.Delay(every ?? TimeSpan.FromSeconds(2), ct).ConfigureAwait(false);
        }
        return new StageReport(StageOutcome.Unknown, null);
    }
}

/// <summary>Source-compatible name for older clients; delegates to AIJADE's native scene client.</summary>
public sealed class MosaicStage(AijadeApi api)
{
    private readonly CompanionStage stage = new(api);
    public Task<StageState?> StateAsync(CancellationToken ct = default) => stage.StateAsync(ct);
    public Task SendAsync(string commandLine, CancellationToken ct = default) => stage.SendAsync(commandLine, ct);
    public Task<StageReport> FollowAsync(StageAction? action, string? noticeBefore, TimeSpan? every = null, TimeSpan? limit = null, CancellationToken ct = default)
        => stage.FollowAsync(action, noticeBefore, every, limit, ct);
}
