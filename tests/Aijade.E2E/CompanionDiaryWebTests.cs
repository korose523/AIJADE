using Aijade.Client.Api;
using Aijade.Client.Companion;

using Microsoft.Playwright;

using static Microsoft.Playwright.Assertions;

namespace Aijade.E2E;

public sealed partial class CompanionExperienceWebTests
{
    [Fact]
    public async Task A_saved_diary_exchange_can_be_read_on_signed_QQ_and_forgotten_on_the_Web_without_deleting_the_chat()
    {
        host.RequireEnabled(); var ct = TestContext.Current.CancellationToken;
        var (page, _) = await host.SignUpAsync("Diary owner");
        using var ownerHttp = new HttpClient { BaseAddress = host.BaseUrl };
        var tokens = new MemoryTokenStore(); await tokens.SetAsync(await page.EvaluateAsync<string>("localStorage.getItem('aijade.session')"));
        var api = new AijadeApi(ownerHttp, tokens); var sync = new CompanionSync(api);
        using var relayHttp = new HttpClient { BaseAddress = host.BaseUrl };
        var relayTokens = new MemoryTokenStore(); await relayTokens.SetAsync(E2EHost.AdminToken);
        await using var qq = new LocalQqHarness(new AijadeApi(relayHttp, relayTokens), ct);
        try
        {
            await page.GetByPlaceholder("Say something…").FillAsync("DIARY-WEB-SOURCE: I finished my book today.");
            await page.GetByRole(AriaRole.Button, new() { Name = "Send", Exact = true }).ClickAsync();
            await Expect(page.Locator(".bubble.assistant").Last).ToHaveTextAsync(FakeUpstream.Reply);
            await page.GetByPlaceholder("Say something…").FillAsync("/diary save");
            await page.GetByRole(AriaRole.Button, new() { Name = "Send", Exact = true }).ClickAsync();
            await Expect(page.Locator(".bubble.assistant").Last).ToContainTextAsync("已加入共同日记");
            var day = await sync.ReadDiaryAsync(null, ct: ct); var entry = Assert.Single(day.Entries);
            var code = (await sync.PairingCodeAsync(ct))!["code"]!.GetValue<string>();
            await qq.SendAsync("/bind " + code, ct);
            await LocalQqHarness.WaitAsync(() => qq.Texts.Any(t => t.Contains("同步绑定完成", StringComparison.Ordinal)), ct);
            await qq.SendAsync($"/diary {day.Day:yyyy-MM-dd}", ct);
            await LocalQqHarness.WaitAsync(() => qq.Texts.Any(t => t.Contains("DIARY-WEB-SOURCE", StringComparison.Ordinal)), ct);

            await page.GetByRole(AriaRole.Link, new() { Name = "Companion life" }).ClickAsync();
            await Expect(page.Locator(".companion-diary-entry")).ToHaveCountAsync(1);
            await Expect(page.Locator(".companion-diary-entry")).ToContainTextAsync("DIARY-WEB-SOURCE");
            await page.GetByRole(AriaRole.Button, new() { Name = "Forget excerpt", Exact = true }).ClickAsync();
            await Expect(page.Locator(".companion-diary-entry")).ToHaveCountAsync(0);
            Assert.NotEmpty(await api.MessagesAsync(entry.ChatId, ct: ct));
            await qq.SendAsync($"/diary {day.Day:yyyy-MM-dd}", ct);
            await LocalQqHarness.WaitAsync(() => qq.Texts.Any(t => t.Contains("还没有保存的对话", StringComparison.Ordinal)), ct);

            // Save on the still-running signed QQ route, then refresh the same Web view.
            var priorReplies = qq.Texts.Count(t => t.Contains(FakeUpstream.Reply, StringComparison.Ordinal));
            await qq.SendAsync("DIARY-QQ-SOURCE: I will read another chapter.", ct);
            await LocalQqHarness.WaitAsync(() => qq.Texts.Count(t => t.Contains(FakeUpstream.Reply, StringComparison.Ordinal)) > priorReplies, ct);
            await qq.SendAsync("/diary save", ct);
            await LocalQqHarness.WaitAsync(() => qq.Texts.Any(t => t.Contains("DIARY-QQ-SOURCE", StringComparison.Ordinal)), ct);
            await page.GetByRole(AriaRole.Button, new() { Name = "Read diary", Exact = true }).ClickAsync();
            await Expect(page.Locator(".companion-diary-entry")).ToHaveCountAsync(1);
            await Expect(page.Locator(".companion-diary-entry")).ToContainTextAsync("DIARY-QQ-SOURCE");
        }
        finally { await page.Context.CloseAsync(); }
    }
}
