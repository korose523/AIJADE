using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Companion;

namespace Aijade.Tests;

public class CompanionLifeTests
{
    private static readonly DateTimeOffset Noon = new(2026, 11, 5, 12, 0, 0, TimeSpan.Zero);

    private static StoredMessage Line(string role, double minutes, JsonObject? meta = null) =>
        new(Guid.NewGuid().ToString(), 0, role, "x", Noon.AddMinutes(minutes), meta);

    private static JsonObject First() => new() { [Initiative.ProactiveMeta] = true };

    [Fact]
    public void A_day_counts_only_what_is_stored()
    {
        var day = CompanionLife.Days([
            Line("user", 0), Line("assistant", 1),
            Line("assistant", 100, First()), Line("user", 105),
            Line("assistant", 200, First()),
            Line("assistant", 300, new JsonObject { [Initiative.ProactiveMeta] = true, ["selfie"] = new JsonObject() }),
            Line("assistant", 310, new JsonObject { [Initiative.ProactiveMeta] = true, ["reminder"] = new JsonObject() }),
        ], zone: TimeZoneInfo.Utc).Single();
        Assert.Equal(2, day.OwnerTurns);
        Assert.Equal(2, day.FirstLines);
        Assert.Equal(1, day.FirstLinesAnswered);
        Assert.Equal(1, day.Selfies);
        Assert.Equal(1, day.Reminders);
    }

    [Fact]
    public void A_day_without_lines_is_not_invented()
    {
        Assert.Empty(CompanionLife.Days([], zone: TimeZoneInfo.Utc));
        var days = CompanionLife.Days([Line("user", 0), Line("user", 60 * 48)], zone: TimeZoneInfo.Utc);
        Assert.Equal(2, days.Count);
        Assert.True(days[0].Day > days[1].Day);
    }

    [Fact]
    public void Mood_fades_to_its_base_with_the_half_life()
    {
        Assert.Equal(CompanionLife.MoodBase, CompanionLife.Fade(CompanionLife.MoodBase, 5), 12);
        Assert.Equal(.6, CompanionLife.Fade(1, CompanionLife.MoodHalfLifeHours), 12);
        Assert.Equal(1, CompanionLife.Fade(1, -2), 12);
    }

    [Fact]
    public void Talking_lifts_her_mood_and_an_unanswered_line_lowers_it()
    {
        var up = CompanionLife.Days([.. Enumerable.Range(0, 3).Select(i => Line("user", i))], zone: TimeZoneInfo.Utc).Single();
        Assert.Equal(1, up.MoodTrend);
        var down = CompanionLife.Days([Line("assistant", 0, First()), Line("assistant", 15, First()), Line("assistant", 30, First()), Line("assistant", 45)], zone: TimeZoneInfo.Utc).Single();
        Assert.True(down.MoodEnd < down.MoodStart);
    }

    [Fact]
    public async Task A_failed_minute_step_is_reported_and_the_loop_can_go_on()
    {
        Exception? reported = null;
        await CompanionLife.MinuteStepAsync(() => throw new InvalidOperationException("boom"), e => reported = e);
        Assert.IsType<InvalidOperationException>(reported);
    }

    [Fact]
    public async Task A_closed_page_still_ends_the_loop() =>
        await Assert.ThrowsAsync<ObjectDisposedException>(() => CompanionLife.MinuteStepAsync(() => throw new ObjectDisposedException("page"), _ => { }));
}
