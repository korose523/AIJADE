using System.Globalization;

using Aijade.Client.Api;
using Aijade.Client.Companion;
using Aijade.Integrations;

using Microsoft.Playwright;

using static Microsoft.Playwright.Assertions;

namespace Aijade.E2E;

public sealed partial class CompanionExperienceWebTests
{
    [Fact]
    public async Task QQ_first_lines_and_due_reminders_share_typed_delivery_records_visible_after_Web_reload()
    {
        host.RequireEnabled(); var ct = TestContext.Current.CancellationToken;
        var (page, _) = await host.SignUpAsync("Proactive delivery owner");
        using var ownerHttp = new HttpClient { BaseAddress = host.BaseUrl };
        var tokens = new MemoryTokenStore(); await tokens.SetAsync(await page.EvaluateAsync<string>("localStorage.getItem('aijade.session')"));
        var sync = new CompanionSync(new AijadeApi(ownerHttp, tokens));
        using var relayHttp = new HttpClient { BaseAddress = host.BaseUrl };
        var relayTokens = new MemoryTokenStore(); await relayTokens.SetAsync(E2EHost.AdminToken);
        var time = new DeliveryClock();
        var offset = 12 - time.GetUtcNow().Hour;
        var zone = offset == 0 ? "Etc/UTC" : "Etc/GMT" + (offset > 0 ? "-" : "+") + Math.Abs(offset).ToString(CultureInfo.InvariantCulture);
        // Finish the Web client's first notebook import before changing its revision through the API.
        await page.GetByRole(AriaRole.Link, new() { Name = "Companion life" }).ClickAsync();
        await Expect(page.GetByLabel("Home", new() { Exact = true })).ToBeVisibleAsync();
        var shared = await sync.CurrentAsync(ct);
        await sync.SaveProfileAsync(shared.CharacterId, shared.Profile with { TimeZone = zone, NaturalPacing = false, Weather = false }, shared.ProfileRevision, ct);
        await using var qq = new LocalQqHarness(new AijadeApi(relayHttp, relayTokens), ct, time, speakFirst: true);
        try
        {
            var code = (await sync.PairingCodeAsync(ct))!["code"]!.GetValue<string>();
            await qq.SendAsync("/bind " + code, ct);
            await LocalQqHarness.WaitAsync(() => qq.Texts.Any(t => t.Contains("同步绑定完成", StringComparison.Ordinal)), ct);
            await qq.SendAsync("SYNTHETIC-PROACTIVE: 今天有点紧张，陪我聊聊", ct);
            await WaitForDeliveryAsync(sync, 1, "acknowledged", ct);
            time.Advance(TimeSpan.FromSeconds(600)); qq.ReplyMode = "missing-id";
            await Assert.ThrowsAsync<OneBotSendException>(() => qq.SpeakFirstAsync(ct));
            var first = await WaitForDeliveryAsync(sync, 2, "unknown", ct);
            Assert.Equal("initiative", first.Entries[0].Kind);
            Assert.Equal(0, await qq.SpeakFirstAsync(ct));

            qq.ReplyMode = "ok";
            await qq.SendAsync("十分钟后提醒我喝水", ct);
            await WaitForDeliveryAsync(sync, 3, "acknowledged", ct);
            time.Advance(TimeSpan.FromSeconds(600)); qq.ReplyMode = "failed";
            await Assert.ThrowsAsync<OneBotSendException>(() => qq.RemindAsync(ct));
            var reminder = (await WaitForDeliveryAsync(sync, 4, "rejected", ct)).Entries[0];
            Assert.Equal("reminder", reminder.Kind); Assert.False(string.IsNullOrWhiteSpace(reminder.TriggerId));
            Assert.Equal(0, await qq.RemindAsync(ct));
            await page.GetByRole(AriaRole.Button, new() { Name = "Read QQ delivery records", Exact = true }).ClickAsync();
            await Expect(page.Locator(".companion-delivery-entry")).ToHaveCountAsync(4);
            await Expect(page.Locator(".companion-delivery-entry").First).ToContainTextAsync("Reminder");
            await Expect(page.Locator(".companion-delivery-entry").First).ToContainTextAsync("A part was rejected by the platform");
            await page.ReloadAsync();
            var initiative = page.Locator(".companion-delivery-entry").Filter(new() { HasText = "Proactive message" });
            await Expect(initiative).ToHaveCountAsync(1);
            await Expect(initiative).ToContainTextAsync("Outcome unknown");
            var reminderEntry = page.Locator(".companion-delivery-entry").First;
            await reminderEntry.Locator("summary").ClickAsync();
            await Expect(reminderEntry).ToContainTextAsync(reminder.TriggerId!);
            if (Environment.GetEnvironmentVariable("AIJADE_E2E_DIAGNOSTICS") is { Length: > 0 } directory)
            {
                Directory.CreateDirectory(directory);
                await page.Locator("section[aria-label='QQ delivery records']").ScreenshotAsync(new() { Path = Path.Combine(directory, "qq-proactive-reminder-records.png") });
            }
        }
        finally { await page.Context.CloseAsync(); }
    }

    private sealed class DeliveryClock : TimeProvider
    {
        private DateTimeOffset now = DateTimeOffset.UtcNow;
        public override DateTimeOffset GetUtcNow() => now;
        public void Advance(TimeSpan span) => now += span;
    }

    [Fact]
    public async Task Signed_QQ_delivery_rejection_unknown_and_acknowledgement_survive_a_Web_reload_without_claiming_read_receipts()
    {
        host.RequireEnabled(); var ct = TestContext.Current.CancellationToken;
        var (page, _) = await host.SignUpAsync("Delivery owner");
        using var ownerHttp = new HttpClient { BaseAddress = host.BaseUrl };
        var tokens = new MemoryTokenStore(); await tokens.SetAsync(await page.EvaluateAsync<string>("localStorage.getItem('aijade.session')"));
        var sync = new CompanionSync(new AijadeApi(ownerHttp, tokens));
        using var relayHttp = new HttpClient { BaseAddress = host.BaseUrl };
        var relayTokens = new MemoryTokenStore(); await relayTokens.SetAsync(E2EHost.AdminToken);
        await using var qq = new LocalQqHarness(new AijadeApi(relayHttp, relayTokens), ct);
        try
        {
            var code = (await sync.PairingCodeAsync(ct))!["code"]!.GetValue<string>();
            await qq.SendAsync("/bind " + code, ct);
            await LocalQqHarness.WaitAsync(() => qq.Texts.Any(t => t.Contains("同步绑定完成", StringComparison.Ordinal)), ct);
            qq.ReplyMode = "failed";
            await qq.SendAsync("SYNTHETIC-REJECTED: How was your day?", ct);
            var rejected = await WaitForDeliveryAsync(sync, 1, "rejected", ct);
            await page.GetByRole(AriaRole.Link, new() { Name = "Companion life" }).ClickAsync();
            await Expect(page.Locator(".companion-delivery-entry")).ToHaveCountAsync(1);
            await Expect(page.Locator(".companion-delivery-entry")).ToContainTextAsync("A part was rejected by the platform");

            qq.ReplyMode = "missing-id";
            await qq.SendAsync("SYNTHETIC-UNKNOWN: The action receipt will be incomplete.", ct);
            await WaitForDeliveryAsync(sync, 2, "unknown", ct);
            await page.GetByRole(AriaRole.Button, new() { Name = "Read QQ delivery records", Exact = true }).ClickAsync();
            await Expect(page.Locator(".companion-delivery-entry")).ToHaveCountAsync(2);
            await Expect(page.Locator(".companion-delivery-entry").First).ToContainTextAsync("Outcome unknown");
            await page.ReloadAsync();
            await Expect(page.Locator(".companion-delivery-entry")).ToHaveCountAsync(2);
            Assert.Contains((await sync.DeliveriesAsync(null, ct)).Entries, e => e.Id == rejected.Entries[0].Id);

            qq.ReplyMode = "ok";
            await qq.SendAsync("/life", ct); // explicit command uses the same source-linked delivery path
            var acknowledged = await WaitForDeliveryAsync(sync, 3, "acknowledged", ct);
            Assert.Equal("7", Assert.Single(acknowledged.Entries[0].Parts!).PlatformMessageId);
            await page.GetByRole(AriaRole.Button, new() { Name = "Read QQ delivery records", Exact = true }).ClickAsync();
            await Expect(page.Locator(".companion-delivery-entry")).ToHaveCountAsync(3);
            await Expect(page.Locator(".companion-delivery-entry").First).ToContainTextAsync("Platform acknowledged");
            await Expect(page.GetByText("Platform acceptance does not prove", new() { Exact = false })).ToBeVisibleAsync();
            if (Environment.GetEnvironmentVariable("AIJADE_E2E_DIAGNOSTICS") is { Length: > 0 } directory)
            {
                Directory.CreateDirectory(directory);
                await page.Locator("section[aria-label='QQ delivery records']").ScreenshotAsync(new() { Path = Path.Combine(directory, "qq-delivery-records.png") });
            }
        }
        finally { await page.Context.CloseAsync(); }
    }

    private static async Task<DeliveryLog> WaitForDeliveryAsync(CompanionSync sync, int count, string state, CancellationToken ct)
    {
        var deadline = DateTimeOffset.UtcNow.AddSeconds(20);
        do
        {
            var log = await sync.DeliveriesAsync(null, ct);
            if (log.Entries.Count == count && log.Entries[0].State == state) return log;
            await Task.Delay(50, ct);
        } while (DateTimeOffset.UtcNow < deadline);
        throw new TimeoutException("A synthetic QQ delivery observation did not settle");
    }
}
