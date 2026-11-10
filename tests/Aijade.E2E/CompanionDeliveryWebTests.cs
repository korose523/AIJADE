using Aijade.Client.Api;
using Aijade.Client.Companion;

using Microsoft.Playwright;

using static Microsoft.Playwright.Assertions;

namespace Aijade.E2E;

public sealed partial class CompanionExperienceWebTests
{
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
