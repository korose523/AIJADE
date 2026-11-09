using Microsoft.Playwright;

using static Microsoft.Playwright.Assertions;

namespace Aijade.E2E;

public sealed partial class CompanionExperienceWebTests(E2EHost host)
{
    [Fact]
    public async Task Location_and_timezone_can_be_saved_offline_changed_and_cleared()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Companion life" }).ClickAsync();
        await page.GetByLabel("City label").FillAsync("Flexible city");
        await page.GetByLabel("Time zone (blank uses the shared server clock)").FillAsync("Asia/Seoul");
        await page.GetByLabel("Latitude", new() { Exact = true }).FillAsync("37.566");
        await page.GetByLabel("Longitude", new() { Exact = true }).FillAsync("126.9784");
        await PersistProfileAsync(page, "Save location and time zone");
        await page.ReloadAsync();
        await Expect(page.GetByLabel("City label")).ToHaveValueAsync("Flexible city");
        await Expect(page.GetByLabel("Latitude", new() { Exact = true })).ToHaveValueAsync("37.566");
        await page.GetByLabel("Latitude", new() { Exact = true }).FillAsync("91");
        await page.GetByRole(AriaRole.Button, new() { Name = "Save location and time zone" }).ClickAsync();
        await Expect(page.GetByRole(AriaRole.Alert)).ToContainTextAsync("Latitude must be");
        await page.ReloadAsync();
        await Expect(page.GetByLabel("Latitude", new() { Exact = true })).ToHaveValueAsync("37.566");
        await PersistProfileAsync(page, "Clear location; use shared server clock");
        await page.ReloadAsync();
        await Expect(page.GetByLabel("City label")).ToHaveValueAsync("");
        await Expect(page.GetByLabel("Time zone (blank uses the shared server clock)")).ToHaveValueAsync("");
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task An_administrator_can_keep_change_disable_and_check_local_services_without_loading_a_model()
    {
        host.RequireEnabled();
        using var http = new HttpClient { BaseAddress = host.BaseUrl };
        http.DefaultRequestHeaders.Authorization = new("Bearer", E2EHost.AdminToken);
        var original = await http.GetStringAsync("/api/v1/admin/gateway/routes", TestContext.Current.CancellationToken);
        var page = await host.NewPageAsync();
        try
        {
            await page.GotoAsync("/");
            await page.EvaluateAsync("token => localStorage.setItem('aijade.session', token)", E2EHost.AdminToken);
            await page.ReloadAsync();
            await page.GetByRole(AriaRole.Link, new() { Name = "Companion life" }).ClickAsync();
            await page.GetByRole(AriaRole.Link, new() { Name = "Local voice and singing" }).ClickAsync();
            var service = page.GetByRole(AriaRole.Region, new() { Name = "Singing", Exact = true });
            await service.GetByLabel("Service address").FillAsync("http://127.0.0.1:1");
            await service.GetByLabel("Voice identifier").FillAsync("aijade-local");
            await service.GetByLabel("Model folder (record only)").FillAsync("/private/model");
            await service.GetByLabel("Authorised sample folder (record only)").FillAsync("/private/samples");
            await service.GetByLabel("Enable this service").CheckAsync();
            await service.GetByRole(AriaRole.Button, new() { Name = "Save", Exact = true }).ClickAsync();
            await Expect(page.GetByRole(AriaRole.Status)).ToHaveTextAsync("Settings saved. Subsequent requests will use them.");
            await page.ReloadAsync();
            service = page.GetByRole(AriaRole.Region, new() { Name = "Singing", Exact = true });
            await Expect(service.GetByLabel("Model folder (record only)")).ToHaveValueAsync("/private/model");
            await Expect(service.GetByLabel("Enable this service")).ToBeCheckedAsync();
            await service.GetByRole(AriaRole.Button, new() { Name = "Check connection" }).ClickAsync();
            await Expect(service.GetByRole(AriaRole.Status)).ToHaveTextAsync("Service could not be reached.");
            await service.GetByLabel("Enable this service").UncheckAsync();
            await service.GetByRole(AriaRole.Button, new() { Name = "Save", Exact = true }).ClickAsync();
            await Expect(page.GetByRole(AriaRole.Status)).ToHaveTextAsync("Settings saved. Subsequent requests will use them.");
            await page.ReloadAsync();
            service = page.GetByRole(AriaRole.Region, new() { Name = "Singing", Exact = true });
            await Expect(service.GetByLabel("Enable this service")).Not.ToBeCheckedAsync();
            await Expect(service.GetByLabel("Authorised sample folder (record only)")).ToHaveValueAsync("/private/samples");
            if (Environment.GetEnvironmentVariable("AIJADE_SERVICES_SCREENSHOT") is { Length: > 0 } screenshot)
                await page.ScreenshotAsync(new() { Path = screenshot, FullPage = true });
        }
        finally
        {
            using var content = new StringContent(original, System.Text.Encoding.UTF8, "application/json");
            using var restored = await http.PutAsync("/api/v1/admin/gateway/routes", content, TestContext.Current.CancellationToken);
            Assert.True(restored.IsSuccessStatusCode);
            await page.Context.CloseAsync();
        }
    }

    [Fact]
    public async Task Companion_life_is_editable_persistent_and_reaches_the_real_chat_prompt()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Companion life" }).ClickAsync();
        await page.GetByLabel("Home", new() { Exact = true }).FillAsync("a quiet attic");
        await page.GetByLabel("Character appearance").FillAsync("silver hair, green eyes");
        await page.GetByLabel("Interests (comma separated)").FillAsync("painting,reading");
        await page.GetByRole(AriaRole.Checkbox, new() { Name = "Natural reading and typing pace" }).CheckAsync();
        await PersistProfileAsync(page, "Save");
        await page.ReloadAsync();
        await Expect(page.GetByLabel("Home", new() { Exact = true })).ToHaveValueAsync("a quiet attic");
        if (Environment.GetEnvironmentVariable("AIJADE_COMPANION_SCREENSHOT") is { Length: > 0 } screenshot)
            await page.ScreenshotAsync(new() { Path = screenshot, FullPage = true });
        await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();
        await page.GetByPlaceholder("Say something…").FillAsync("谢谢你，今天过得怎么样？");
        await page.GetByRole(AriaRole.Button, new() { Name = "Send", Exact = true }).ClickAsync();
        await Expect(page.Locator(".bubble.assistant").Last).ToHaveTextAsync(FakeUpstream.Reply);
        var prompt = host.Llm.ChatRequests[^1]["messages"]![0]!["content"]!.GetValue<string>();
        Assert.Contains("fictional", prompt, StringComparison.Ordinal);
        Assert.True(prompt.Contains("painting", StringComparison.Ordinal) || prompt.Contains("reading", StringComparison.Ordinal),
            "The day's interest must come from the owner's configured interests, not the default list.");
        Assert.Contains("Do not guilt the user", prompt, StringComparison.Ordinal);
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task A_song_added_on_the_page_is_playable_in_chat_and_an_unknown_song_is_declined()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Companion life" }).ClickAsync();
        await page.Locator("select").First.SelectOptionAsync("song");
        await page.GetByPlaceholder("Name / song title").FillAsync("Our little tune");
        await page.GetByPlaceholder("Source and voice/music permission").FillAsync("Test fixture, synthetic silent WAV; no human voice");
        // A valid short WAV, sufficient to exercise import, persistence and the actual browser audio element.
        var wav = new byte[44 + 1600];
        "RIFF"u8.CopyTo(wav); BitConverter.GetBytes(wav.Length - 8).CopyTo(wav, 4); "WAVEfmt "u8.CopyTo(wav.AsSpan(8));
        BitConverter.GetBytes(16).CopyTo(wav, 16); BitConverter.GetBytes((short)1).CopyTo(wav, 20); BitConverter.GetBytes((short)1).CopyTo(wav, 22);
        BitConverter.GetBytes(8000).CopyTo(wav, 24); BitConverter.GetBytes(16000).CopyTo(wav, 28); BitConverter.GetBytes((short)2).CopyTo(wav, 32);
        BitConverter.GetBytes((short)16).CopyTo(wav, 34); "data"u8.CopyTo(wav.AsSpan(36)); BitConverter.GetBytes(1600).CopyTo(wav, 40);
        await page.Locator("input[type=file]").SetInputFilesAsync(new FilePayload { Name = "tune.wav", MimeType = "audio/wav", Buffer = wav });
        await Expect(page.GetByRole(AriaRole.Status)).ToHaveTextAsync("Saved to your collection");
        await page.ReloadAsync();
        await Expect(page.Locator("audio")).ToHaveCountAsync(1);
        await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();
        await page.GetByPlaceholder("Say something…").FillAsync("/sing Our little tune");
        await page.GetByRole(AriaRole.Button, new() { Name = "Send", Exact = true }).ClickAsync();
        await Expect(page.Locator(".messages audio")).ToHaveCountAsync(1);
        Assert.True(await page.Locator(".messages audio").EvaluateAsync<bool>("async audio => { await audio.play(); return audio.duration > 0; }"));
        await Expect(page.GetByRole(AriaRole.Button, new() { Name = "Send", Exact = true })).ToBeVisibleAsync();
        await page.GetByPlaceholder("Say something…").FillAsync("/sing never learned");
        await page.GetByRole(AriaRole.Button, new() { Name = "Send", Exact = true }).ClickAsync();
        await Expect(page.Locator(".bubble.assistant").Last).ToContainTextAsync("还没有练好");
        await Expect(page.Locator(".messages audio")).ToHaveCountAsync(1);
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task An_outfit_reference_is_kept_and_its_description_reaches_a_generated_photo()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Companion life" }).ClickAsync();
        await page.Locator("select").First.SelectOptionAsync("outfit");
        await page.GetByPlaceholder("Name / song title").FillAsync("blue coat");
        await page.GetByPlaceholder("Description for chat and photos").FillAsync("a blue coat with silver buttons");
        await page.Locator("input[type=file]").SetInputFilesAsync(new FilePayload { Name = "coat.png", MimeType = "image/png", Buffer = Convert.FromBase64String(FakeUpstream.PngBase64) });
        await Expect(page.GetByRole(AriaRole.Status)).ToHaveTextAsync("Saved to your collection");
        await page.GetByRole(AriaRole.Link, new() { Name = "Settings" }).ClickAsync();
        await page.GetByRole(AriaRole.Checkbox, new() { Name = "Drawing", Exact = true }).CheckAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();
        await page.GetByPlaceholder("Say something…").FillAsync("/photo selfie");
        await page.GetByRole(AriaRole.Button, new() { Name = "Send", Exact = true }).ClickAsync();
        var photo = page.Locator("figure.bubble.image img");
        await Expect(photo).ToBeVisibleAsync();
        await Expect(photo).ToHaveAttributeAsync("alt", new System.Text.RegularExpressions.Regex("blue coat with silver buttons"));
        Assert.True(await photo.EvaluateAsync<bool>("img => img.complete && img.naturalWidth === 1"));
        await page.Context.CloseAsync();
    }
}
