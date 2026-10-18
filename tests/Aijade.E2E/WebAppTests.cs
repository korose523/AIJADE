using System.Text.Json;
using System.Text.Json.Nodes;

using Microsoft.Playwright;

using static Microsoft.Playwright.Assertions;

namespace Aijade.E2E;

/// <summary>
/// Acceptance walk-throughs of the companion features (docs/STATUS.md §4) in a real browser. Tests in this class run one after another (they
/// share one server and count rows in its database).
/// </summary>
public sealed class WebAppTests(E2EHost host)
{
    [Fact]
    public async Task A_sign_up_chat_streams_lifts_the_expression_marker_and_pairs_the_render_receipt()
    {
        host.RequireEnabled();
        var pairedBefore = await host.CountAsync("SELECT count(*) FROM render_traces WHERE projection_status = 'paired'");
        var (page, email) = await host.SignUpAsync();

        await page.GetByPlaceholder("Say something…").FillAsync("Hi! I like jasmine tea.");
        await page.GetByRole(AriaRole.Button, new() { Name = "Send" }).ClickAsync();

        var reply = page.Locator(".bubble.assistant").Last;
        await Expect(reply).ToHaveTextAsync(FakeUpstream.Reply);
        await Expect(page.Locator(".messages")).Not.ToContainTextAsync("[[emote");
        await Expect(page.GetByRole(AriaRole.Button, new() { Name = "Send" })).ToBeVisibleAsync();

        // The client sent the default companion persona and the user's words through the gateway.
        var sent = host.Llm.ChatRequests[^1];
        Assert.StartsWith("You are 艾娅德", sent["messages"]![0]!["content"]!.GetValue<string>(), StringComparison.Ordinal);
        // The learning module (on by default) contributed the learned persona to the system prompt.
        Assert.Contains("warmth:", sent["messages"]![0]!["content"]!.GetValue<string>(), StringComparison.Ordinal);
        Assert.Equal("Hi! I like jasmine tea.", sent["messages"]!.AsArray()[^1]!["content"]!.GetValue<string>());

        // The stage applied the expression and the server paired the render receipt with the intent.
        Assert.True(await host.WaitCountAsync("SELECT count(*) FROM render_traces WHERE projection_status = 'paired'", pairedBefore + 1) > pairedBefore);

        // Both turns are stored, and survive a reload of the chat (multi-session history).
        Assert.Equal(2, await host.CountAsync(
            "SELECT count(*) FROM chat_messages m JOIN chats c ON c.id = m.chat_id JOIN users u ON u.id = c.owner_id WHERE u.email = $1", email));
        await page.ReloadAsync();
        await Expect(page.Locator(".bubble.user")).ToHaveTextAsync("Hi! I like jasmine tea.");
        await Expect(page.Locator(".bubble.assistant")).ToHaveTextAsync(FakeUpstream.Reply);

        // A second chat starts empty; the first stays listed.
        await page.GetByRole(AriaRole.Button, new() { Name = "＋ New chat" }).ClickAsync();
        await Expect(page.Locator(".chat-item")).ToHaveCountAsync(2);
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task A_what_the_user_says_reaches_long_term_memory_and_can_be_searched_and_forgotten()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        await page.GetByPlaceholder("Say something…").FillAsync("My cat is called Mochi.");
        await page.GetByRole(AriaRole.Button, new() { Name = "Send" }).ClickAsync();
        await Expect(page.Locator(".bubble.assistant").Last).ToHaveTextAsync(FakeUpstream.Reply);

        await page.GetByRole(AriaRole.Link, new() { Name = "Memory" }).ClickAsync();
        var item = page.Locator(".memory-list li", new() { HasText = "Mochi" });
        // The perception pipeline commits asynchronously (worker role); reload until it shows up.
        for (var i = 0; i < 30 && await item.CountAsync() == 0; i++)
        {
            await Task.Delay(1000, TestContext.Current.CancellationToken);
            await page.ReloadAsync();
            await page.GetByRole(AriaRole.Heading, new() { Name = "Long-term memory" }).WaitForAsync();
        }
        await Expect(item).ToHaveCountAsync(1);

        await page.GetByPlaceholder("Search memory").FillAsync("zebra-not-there");
        await Expect(item).ToHaveCountAsync(0);
        await page.GetByPlaceholder("Search memory").FillAsync("Mochi");
        await Expect(item).ToHaveCountAsync(1);

        await item.GetByTitle("Forget").ClickAsync();
        await Expect(item).ToHaveCountAsync(0);
        await page.ReloadAsync();
        await page.GetByRole(AriaRole.Heading, new() { Name = "Long-term memory" }).WaitForAsync();
        await Expect(page.Locator(".memory-list li", new() { HasText = "Mochi" })).ToHaveCountAsync(0);
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task A_a_character_card_drives_the_persona_and_greeting()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Characters" }).ClickAsync();
        await page.GetByLabel("Name", new() { Exact = true }).FillAsync("Tea Maid");
        await page.GetByLabel("Persona").FillAsync("A calm maid who loves tea ceremonies.");
        await page.GetByLabel("Greeting").FillAsync("Welcome back, shall I brew some tea?");
        await page.GetByRole(AriaRole.Button, new() { Name = "Save" }).ClickAsync();
        var card = page.Locator(".card:not(.new)", new() { HasText = "Tea Maid" });
        await Expect(card).ToBeVisibleAsync();

        await card.GetByRole(AriaRole.Button, new() { Name = "Talk to this character" }).ClickAsync();
        await Expect(page.Locator(".messages")).ToContainTextAsync("Welcome back, shall I brew some tea?");
        await page.GetByPlaceholder("Say something…").FillAsync("Hello");
        await page.GetByRole(AriaRole.Button, new() { Name = "Send" }).ClickAsync();
        await Expect(page.Locator(".bubble.assistant").Last).ToHaveTextAsync(FakeUpstream.Reply);
        var system = host.Llm.ChatRequests[^1]["messages"]![0]!["content"]!.GetValue<string>();
        Assert.Contains("Tea Maid", system, StringComparison.Ordinal);
        Assert.Contains("A calm maid who loves tea ceremonies.", system, StringComparison.Ordinal);
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task C_voice_input_that_cannot_start_says_so_clearly()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        // Headless Chromium leaves a permission prompt pending forever, so the user's "Block" is simulated directly:
        // capture is refused the way the browser refuses it. The failure must be shown, not swallowed.
        await page.Context.AddInitScriptAsync("navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('blocked', 'NotAllowedError'));");
        await page.ReloadAsync();
        await page.GetByTitle("Voice", new() { Exact = true }).ClickAsync();
        await Expect(page.GetByRole(AriaRole.Alert)).ToContainTextAsync("Voice input cannot start: microphone permission denied");
        await Expect(page.GetByTitle("Voice", new() { Exact = true })).Not.ToHaveClassAsync(new System.Text.RegularExpressions.Regex(@"\bon\b"));
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task D_the_built_in_avatar_stage_mounts_without_a_model()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        var canvas = page.Locator(".stage canvas");
        await Expect(canvas).ToBeVisibleAsync();
        var box = await canvas.BoundingBoxAsync();
        Assert.True(box is { Width: > 100, Height: > 100 });
        await Expect(page.Locator(".stage-note")).ToHaveCountAsync(0);
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task D_an_mmd_model_loads_and_its_morphs_follow_the_reply()
    {
        host.RequireEnabled();
        if (E2EHost.MmdDir is null || E2EHost.MmdModel is null)
            Assert.Skip("AIJADE_E2E_MMD_DIR / AIJADE_E2E_MMD_MODEL not set; MMD stage test skipped");
        var (page, _) = await host.SignUpAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Settings" }).ClickAsync();
        var modelUrl = "/models/" + Uri.EscapeDataString(E2EHost.MmdModel!);
        await page.GetByLabel("Model file (PMX/PMD URL)").FillAsync(modelUrl);
        await page.GetByLabel("Model file (PMX/PMD URL)").PressAsync("Tab");
        await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();

        // Loading a real model with large textures takes a while; the badge shows progress meanwhile.
        await page.WaitForFunctionAsync("() => document.querySelector('.stage canvas')?.__aijadeMmd", null, new() { Timeout = 120_000 });
        await Expect(page.Locator(".stage-loading")).ToHaveCountAsync(0, new() { Timeout = 120_000 });
        await Expect(page.Locator(".stage-note")).ToHaveCountAsync(0);
        // Physics runs (Bullet in WebAssembly): rigid-body-driven bones settle under gravity instead of holding the rest pose.
        Assert.True(await page.EvaluateAsync<bool>("() => document.querySelector('.stage canvas').__aijadeMmd.physics !== null"));
        Assert.True(await page.EvaluateAsync<bool>("""
            async () => {
              const { model } = document.querySelector('.stage canvas').__aijadeMmd;
              const driven = model.runtimeBones.filter(b => b.rigidBodyIndices?.length > 0);
              const at = () => driven.map(b => { const m = b.worldMatrix; return [m[12], m[13], m[14]]; }).flat();
              const before = at();
              await new Promise(r => setTimeout(r, 1500));
              const after = at();
              return driven.length > 0 && before.some((v, i) => Math.abs(v - after[i]) > 1e-4);
            }
            """));

        // The eyes follow the pointer across the stage.
        const string EyeAt = "() => [...document.querySelector('.stage canvas').__aijadeMmd.eyes[0].worldMatrix.slice(0, 3)]";
        var box = (await page.Locator(".stage canvas").BoundingBoxAsync())!;
        await page.Mouse.MoveAsync(box.X + 5, box.Y + (box.Height / 2));
        await Task.Delay(300, TestContext.Current.CancellationToken);
        var left = await page.EvaluateAsync<double[]>(EyeAt);
        await page.Mouse.MoveAsync(box.X + box.Width - 5, box.Y + (box.Height / 2));
        await Task.Delay(300, TestContext.Current.CancellationToken);
        var right = await page.EvaluateAsync<double[]>(EyeAt);
        Assert.True(left.Zip(right).Any(p => Math.Abs(p.First - p.Second) > 1e-3), $"eye did not turn: {string.Join(",", left)} vs {string.Join(",", right)}");
        // A beat nods the model.
        Assert.True(await page.EvaluateAsync<bool>("""
            async () => {
              const { mesh } = document.querySelector('.stage canvas').__aijadeMmd;
              const stage = await import('./_content/Aijade.UI/stage.js');
              const rest = mesh.position.y;
              stage.beat(1);
              await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
              return mesh.position.y < rest;
            }
            """));

        await page.GetByPlaceholder("Say something…").FillAsync("We did it!");
        await page.GetByRole(AriaRole.Button, new() { Name = "Send" }).ClickAsync();
        await Expect(page.Locator(".bubble.assistant").Last).ToHaveTextAsync(FakeUpstream.Reply);
        // The expression is applied when the turn completes, just after the last text chunk.
        await page.WaitForFunctionAsync("() => document.querySelector('.stage canvas').__aijadeMmd.model.morph.getMorphWeight('笑い') > 0.3", null, new() { Timeout = 30_000 });
        await page.Context.CloseAsync();
    }

    /// <summary>
    /// A VMD motion written byte by byte from the format (header, Shift-JIS bone names, keyframes with Bézier interpolation):
    /// the head (頭) turns 30° to one side and back over 60 frames. No third-party motion file is needed.
    /// </summary>
    internal static byte[] HeadTurnVmd()
    {
        using var ms = new MemoryStream();
        using var w = new BinaryWriter(ms);
        static byte[] Fixed(byte[] value, int length) { var b = new byte[length]; Array.Copy(value, b, Math.Min(value.Length, length)); return b; }
        w.Write(Fixed(System.Text.Encoding.ASCII.GetBytes("Vocaloid Motion Data 0002"), 30));
        w.Write(Fixed(System.Text.Encoding.ASCII.GetBytes("e2e"), 20));
        var head = new byte[] { 0x93, 0xAA }; // 頭 in Shift-JIS
        // Linear interpolation: control points (20, 20) and (107, 107) for every channel, in the format's 4×16-byte layout.
        var interpolation = new byte[64];
        for (var i = 0; i < 64; i++)
            interpolation[i] = (byte)((i % 16) < 8 ? 20 : 107);
        var keys = new (uint Frame, double Degrees)[] { (0, 0), (30, 30), (60, 0) };
        w.Write((uint)keys.Length);
        foreach (var (frame, degrees) in keys)
        {
            w.Write(Fixed(head, 15));
            w.Write(frame);
            w.Write(0f); w.Write(0f); w.Write(0f); // position
            var half = degrees * Math.PI / 360;
            w.Write(0f); w.Write((float)Math.Sin(half)); w.Write(0f); w.Write((float)Math.Cos(half)); // rotation about Y (x, y, z, w)
            w.Write(interpolation);
        }
        w.Write(0u); // morph keyframes
        w.Write(0u); // camera keyframes
        w.Write(0u); // light keyframes
        w.Write(0u); // self-shadow keyframes
        w.Flush();
        return ms.ToArray();
    }

    [Fact]
    public async Task D_the_mmd_companion_shows_its_mood_nods_while_listening_and_glances_away_while_speaking()
    {
        host.RequireEnabled();
        if (E2EHost.MmdDir is null || E2EHost.MmdModel is null)
            Assert.Skip("AIJADE_E2E_MMD_DIR / AIJADE_E2E_MMD_MODEL not set; MMD stage test skipped");
        var (page, _) = await host.SignUpAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Settings" }).ClickAsync();
        await page.GetByLabel("Model file (PMX/PMD URL)").FillAsync("/models/" + Uri.EscapeDataString(E2EHost.MmdModel!));
        await page.GetByLabel("Model file (PMX/PMD URL)").PressAsync("Tab");
        await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();
        await page.WaitForFunctionAsync("() => document.querySelector('.stage canvas')?.__aijadeMmd", null, new() { Timeout = 120_000 });
        await Expect(page.Locator(".stage-loading")).ToHaveCountAsync(0, new() { Timeout = 120_000 });

        // Mood: a sad, submissive expression slumps the upper body and neck forward; a proud one straightens them. The head
        // moves accordingly (posture eases with a 600 ms half-life, so 2.5 s is close to the target).
        var mood = await page.EvaluateAsync<double[]>("""
            async () => {
              const { model, behaviour } = document.querySelector('.stage canvas').__aijadeMmd;
              const stage = await import('./_content/Aijade.UI/stage.js');
              const head = model.runtimeBones.find(b => b.name === '頭');
              const at = () => { const m = head.worldMatrix; return [m[12], m[13], m[14]]; };
              const wait = (ms) => new Promise(r => setTimeout(r, ms));
              const sad = stage.apply({ expression: { valence: -0.9, dominance: 0.1, arousal: 0.3 } });
              await wait(2500);
              const slumped = at(), leanSad = behaviour.lean;
              stage.apply({ expression: { valence: 0.9, dominance: 0.9, arousal: 0.5 } });
              await wait(2500);
              const upright = at(), leanProud = behaviour.lean;
              return [sad['posture.lean'], leanSad, leanProud, ...slumped, ...upright];
            }
            """);
        Assert.True(mood[0] > 0.1 && mood[1] > 0.1 && mood[2] < -0.05, $"posture targets/leans {mood[0]:0.000} {mood[1]:0.000} {mood[2]:0.000}");
        var shift = Math.Sqrt(Math.Pow(mood[3] - mood[6], 2) + Math.Pow(mood[4] - mood[7], 2) + Math.Pow(mood[5] - mood[8], 2));
        Assert.True(shift > 0.05, $"the head did not move between moods (slumped {mood[3]:0.000},{mood[4]:0.000},{mood[5]:0.000}; upright {mood[6]:0.000},{mood[7]:0.000},{mood[8]:0.000})");
        Assert.True(mood[4] < mood[7], $"a slump lowers the head (slumped y {mood[4]:0.000}, upright y {mood[7]:0.000})");

        // Listening: the microphone module announces a 1.5 s utterance; 250 ms after it ends the companion nods once.
        var nod = await page.EvaluateAsync<double[]>("""
            async () => {
              const { behaviour } = document.querySelector('.stage canvas').__aijadeMmd;
              const say = (speaking, spokeMs = 0) => window.dispatchEvent(new CustomEvent('aijade-user-speech', { detail: { speaking, spokeMs, quietMs: 0 } }));
              const before = behaviour.nods;
              say(true); say(false, 500); // too short for a nod
              await new Promise(r => setTimeout(r, 600));
              const afterShort = behaviour.nods;
              say(true); say(false, 1500);
              await new Promise(r => setTimeout(r, 1500));
              return [before, afterShort, behaviour.nods, behaviour.nodPeak ?? -1, typeof behaviour.nodPeak === 'number' ? 1 : 0];
            }
            """);
        Assert.Equal(nod[0], nod[1]);
        Assert.Equal(nod[0] + 1, nod[2]);
        Assert.True(nod[3] > 0.05, $"nod peak {nod[3]:0.000} rad (nodPeak present: {nod[4]}, nods {nod[0]}→{nod[2]})");

        // Speaking: the eyes glance away now and then (and come back).
        var glances = await page.EvaluateAsync<double>("""
            async () => {
              const { behaviour } = document.querySelector('.stage canvas').__aijadeMmd;
              const stage = await import('./_content/Aijade.UI/stage.js');
              const before = behaviour.saccades;
              stage.mouth(0.5);
              const until = performance.now() + 7000;
              while (performance.now() < until && behaviour.saccades === before) await new Promise(r => setTimeout(r, 100));
              stage.mouth(0);
              return behaviour.saccades - before;
            }
            """);
        Assert.True(glances >= 1, "no glance away while speaking");
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task D_an_idle_vmd_motion_loops_and_moves_the_model()
    {
        host.RequireEnabled();
        if (E2EHost.MmdDir is null || E2EHost.MmdModel is null)
            Assert.Skip("AIJADE_E2E_MMD_DIR / AIJADE_E2E_MMD_MODEL not set; MMD stage test skipped");
        var (page, _) = await host.SignUpAsync();
        var vmd = HeadTurnVmd();
        await page.RouteAsync("**/e2e-motions/head-turn.vmd", route => route.FulfillAsync(new() { Status = 200, ContentType = "application/octet-stream", BodyBytes = vmd }));
        await page.GetByRole(AriaRole.Link, new() { Name = "Settings" }).ClickAsync();
        await page.GetByLabel("Model file (PMX/PMD URL)").FillAsync("/models/" + Uri.EscapeDataString(E2EHost.MmdModel!));
        await page.GetByLabel("Model file (PMX/PMD URL)").PressAsync("Tab");
        await page.GetByLabel("Idle motion (VMD URL)").FillAsync("/e2e-motions/head-turn.vmd");
        await page.GetByLabel("Idle motion (VMD URL)").PressAsync("Tab");
        await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();
        await page.WaitForFunctionAsync("() => document.querySelector('.stage canvas')?.__aijadeMmd", null, new() { Timeout = 120_000 });
        await Expect(page.Locator(".stage-note")).ToHaveCountAsync(0); // no motion error was reported

        // The motion is 60 frames long and loops; the head's orientation changes as it plays and comes back.
        Assert.Equal(60, await page.EvaluateAsync<double>("() => document.querySelector('.stage canvas').__aijadeMmd.runtime.animationFrameTimeDuration"));
        var turns = await page.EvaluateAsync<double[]>("""
            async () => {
              const { model, runtime } = document.querySelector('.stage canvas').__aijadeMmd;
              const head = model.runtimeBones.find(b => b.name === '頭');
              // the head's forward direction in world space (third row of the rotation part)
              const yaw = () => { const m = head.worldMatrix; return Math.atan2(m[8], m[10]) * 180 / Math.PI; };
              // On a loaded machine the animation can start late: wait for its clock to move, then sample until the head
              // has turned through most of the motion (or ten seconds pass).
              const t0 = performance.now(), f0 = runtime.currentFrameTime;
              while (runtime.currentFrameTime === f0 && performance.now() - t0 < 10000) await new Promise(r => setTimeout(r, 50));
              // At a very low frame rate wall-clock sampling sees only a few phases of the loop: sample until the frames seen
              // cover most of it (10 of 12 five-frame bins) or the head has clearly turned, for up to 30 s.
              const samples = [], bins = new Set();
              const start = performance.now();
              while (performance.now() - start < 30000) {
                samples.push(yaw());
                bins.add(Math.floor((runtime.currentFrameTime % 60) / 5));
                if (Math.max(...samples) - Math.min(...samples) > 25 || bins.size >= 10) break;
                await new Promise(r => setTimeout(r, 50));
              }
              window.__vmdDiag = JSON.stringify({ playing: runtime.isAnimationPlaying, f0, bins: bins.size, frame: runtime.currentFrameTime, duration: runtime.animationFrameTimeDuration,
                visibility: document.visibilityState, head: !!head, animations: model.runtimeAnimations?.length ?? null, current: !!model.currentAnimation });
              return [Math.min(...samples), Math.max(...samples), runtime.currentFrameTime];
            }
            """);
        Assert.True(turns[1] - turns[0] > 20, $"head yaw range {turns[0]:0.0}…{turns[1]:0.0}° — the motion did not play; {await page.EvaluateAsync<string>("() => window.__vmdDiag")}");
        Assert.InRange(turns[2], 0, 60); // looped rather than ran off the end
        // Still playing after more than one full pass (the runtime pauses itself at the end of a pass; the stage restarts it).
        await page.WaitForTimeoutAsync(3000);
        Assert.True(await page.EvaluateAsync<bool>("() => document.querySelector('.stage canvas').__aijadeMmd.runtime.isAnimationPlaying"), "the idle motion stopped after a pass");
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task E_language_choice_applies_immediately_and_persists()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Settings" }).ClickAsync();
        await page.GetByLabel("Language").SelectOptionAsync("zh-Hans");
        await Expect(page.GetByRole(AriaRole.Link, new() { Name = "设置" })).ToBeVisibleAsync();
        await page.ReloadAsync();
        await Expect(page.GetByRole(AriaRole.Link, new() { Name = "设置" })).ToBeVisibleAsync();
        var stored = await page.EvaluateAsync<string>("() => localStorage.getItem('aijade.settings.v1')");
        Assert.Equal("zh-Hans", JsonNode.Parse(stored)!["locale"]!.GetValue<string>());
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task E_signing_out_returns_to_the_sign_in_form_and_signing_back_in_restores_the_chats()
    {
        host.RequireEnabled();
        var (page, email) = await host.SignUpAsync();
        await page.GetByPlaceholder("Say something…").FillAsync("Remember this chat.");
        await page.GetByRole(AriaRole.Button, new() { Name = "Send" }).ClickAsync();
        await Expect(page.Locator(".bubble.assistant").Last).ToHaveTextAsync(FakeUpstream.Reply);

        await page.GetByRole(AriaRole.Link, new() { Name = "Settings" }).ClickAsync();
        await page.GetByRole(AriaRole.Button, new() { Name = "Sign out" }).ClickAsync();
        await Expect(page.GetByRole(AriaRole.Button, new() { Name = "Sign in" })).ToBeVisibleAsync();

        await page.GetByLabel("Email").FillAsync(email);
        await page.GetByLabel("Password").FillAsync("e2e-password-1234");
        await page.GetByRole(AriaRole.Button, new() { Name = "Sign in" }).ClickAsync();
        await Expect(page.Locator(".chat-item")).ToHaveCountAsync(1);
        await page.Locator(".chat-item a").First.ClickAsync();
        await Expect(page.Locator(".bubble.user")).ToHaveTextAsync("Remember this chat.");
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task F_the_admin_console_is_for_admins_and_its_gateway_edit_keeps_the_masked_keys()
    {
        host.RequireEnabled();
        var (page, email) = await host.SignUpAsync();
        await Expect(page.GetByRole(AriaRole.Link, new() { Name = "Admin" })).ToHaveCountAsync(0);
        await page.GotoAsync("/admin");
        await Expect(page.GetByRole(AriaRole.Alert)).ToContainTextAsync("This page is for administrators.");

        await using (var cmd = host.Db.CreateCommand("UPDATE users SET role = 'admin' WHERE email = $1"))
        {
            cmd.Parameters.Add(new Npgsql.NpgsqlParameter { Value = email });
            await cmd.ExecuteNonQueryAsync(TestContext.Current.CancellationToken);
        }
        await page.GotoAsync("/");
        await page.GetByRole(AriaRole.Link, new() { Name = "Admin" }).ClickAsync();
        await Expect(page.GetByRole(AriaRole.Row, new() { Name = "events" })).ToBeVisibleAsync();

        // Users: the new account is listed; flux granted through the form lands in the ledger once.
        await page.GetByRole(AriaRole.Link, new() { Name = "Users" }).ClickAsync();
        await page.GetByPlaceholder("Search by email or name").FillAsync(email);
        await Expect(page.Locator("table.grid tbody tr")).ToHaveCountAsync(1);
        await page.GetByRole(AriaRole.Link, new() { Name = "Flux" }).ClickAsync();
        await page.GetByLabel("User").SelectOptionAsync(new SelectOptionValue { Label = $"{email} (0)" });
        await page.GetByLabel("Amount (negative to deduct)").FillAsync("50");
        await page.GetByLabel("Reason").FillAsync("e2e grant");
        await page.GetByRole(AriaRole.Button, new() { Name = "Apply" }).ClickAsync();
        await Expect(page.GetByRole(AriaRole.Status)).ToHaveTextAsync("Flux updated.");
        Assert.Equal(50, await host.CountAsync("SELECT f.balance FROM flux_accounts f JOIN users u ON u.id = f.user_id WHERE u.email = $1", email));

        // Gateway: keys are never shown in full; saving the document as shown keeps them working.
        await page.GetByRole(AriaRole.Link, new() { Name = "Model gateway" }).ClickAsync();
        var editor = page.GetByRole(AriaRole.Textbox, new() { Name = "Model gateway" });
        await Expect(editor).ToHaveValueAsync(new System.Text.RegularExpressions.Regex("aijade-chat"));
        Assert.Contains("…", await editor.InputValueAsync(), StringComparison.Ordinal);
        await page.GetByRole(AriaRole.Button, new() { Name = "Save" }).ClickAsync();
        await Expect(page.GetByRole(AriaRole.Status)).ToHaveTextAsync("Saved");
        await editor.FillAsync("{ not json");
        await page.GetByRole(AriaRole.Button, new() { Name = "Save" }).ClickAsync();
        await Expect(page.GetByRole(AriaRole.Alert)).ToHaveTextAsync("That is not a valid JSON object.");

        await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();
        await page.GetByPlaceholder("Say something…").FillAsync("Still there?");
        await page.GetByRole(AriaRole.Button, new() { Name = "Send" }).ClickAsync();
        await Expect(page.Locator(".bubble.assistant").Last).ToHaveTextAsync(FakeUpstream.Reply);
        Assert.Equal("Bearer k", host.Llm.Authorizations[^1]);

        // Requests: the gateway call just made is logged.
        await page.GetByRole(AriaRole.Link, new() { Name = "Admin" }).ClickAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Requests" }).ClickAsync();
        await Expect(page.Locator("table.grid tbody tr").First).ToContainTextAsync("aijade-chat");
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task B_with_drawing_switched_on_the_companion_answers_with_a_picture()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        // Off by default: the request stays text, and no picture appears.
        await page.GetByPlaceholder("Say something…").FillAsync("Please draw a cat");
        await page.GetByRole(AriaRole.Button, new() { Name = "Send" }).ClickAsync();
        await Expect(page.Locator(".bubble.assistant").Last).ToHaveTextAsync(FakeUpstream.DrawingReply);
        Assert.DoesNotContain("[[draw:", host.Llm.ChatRequests[^1]["messages"]![0]!["content"]!.GetValue<string>(), StringComparison.Ordinal);
        await Expect(page.Locator("figure.bubble.image")).ToHaveCountAsync(0);

        await page.GetByRole(AriaRole.Link, new() { Name = "Settings" }).ClickAsync();
        await page.GetByRole(AriaRole.Checkbox, new() { Name = "Drawing" }).CheckAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();
        await page.Locator(".chat-item a").First.ClickAsync();
        await page.GetByPlaceholder("Say something…").FillAsync("Now draw it please");
        await page.GetByRole(AriaRole.Button, new() { Name = "Send" }).ClickAsync();

        var picture = page.GetByRole(AriaRole.Img, new() { Name = FakeUpstream.DrawingPrompt });
        await Expect(picture).ToBeVisibleAsync();
        Assert.Contains("[[draw:", host.Llm.ChatRequests[^1]["messages"]![0]!["content"]!.GetValue<string>(), StringComparison.Ordinal);
        Assert.True(await picture.EvaluateAsync<bool>("img => img.complete && img.naturalWidth === 1"));
        await page.ReloadAsync();
        await Expect(page.GetByRole(AriaRole.Img, new() { Name = FakeUpstream.DrawingPrompt })).ToBeVisibleAsync();
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task B_an_attached_image_is_scaled_described_and_given_to_the_next_turn()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        // Off by default: no vision controls.
        await Expect(page.GetByRole(AriaRole.Group, new() { Name = "Vision" })).ToHaveCountAsync(0);
        await page.GetByRole(AriaRole.Link, new() { Name = "Settings" }).ClickAsync();
        await page.GetByRole(AriaRole.Checkbox, new() { Name = "Vision" }).CheckAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();

        var bar = page.GetByRole(AriaRole.Group, new() { Name = "Vision" });
        await Expect(bar.GetByRole(AriaRole.Button, new() { Name = "Share screen" })).ToBeVisibleAsync();
        var before = host.Llm.Requests.Count;
        await bar.Locator("input[type=file]").SetInputFilesAsync(new FilePayload { Name = "square.png", MimeType = "image/png", Buffer = Convert.FromBase64String(FakeUpstream.PngBase64) });
        await Expect(bar.GetByRole(AriaRole.Status)).ToHaveTextAsync("Image attached; it goes with your next message.");
        var visionRequest = host.Llm.Requests.Skip(before).Single(r => r.ToJsonString().Contains("image_url", StringComparison.Ordinal));
        // Re-encoded on the device as a (scaled) JPEG, never the original file.
        Assert.StartsWith("data:image/jpeg;base64,", visionRequest["messages"]![0]!["content"]![1]!["image_url"]!["url"]!.GetValue<string>(), StringComparison.Ordinal);

        await page.GetByPlaceholder("Say something…").FillAsync("What is this?");
        await page.GetByRole(AriaRole.Button, new() { Name = "Send" }).ClickAsync();
        await Expect(page.Locator(".bubble.assistant").Last).ToHaveTextAsync(FakeUpstream.Reply);
        var system = host.Llm.ChatRequests[^1]["messages"]![0]!["content"]!.GetValue<string>();
        Assert.Contains($"The user attached an image to this message. It shows: {FakeUpstream.VisionDescription}", system, StringComparison.Ordinal);
        await Expect(bar.GetByRole(AriaRole.Status)).ToHaveCountAsync(0);
        await page.Context.CloseAsync();
    }

    private const string CountResearchTurns = """
        () => new Promise((resolve, reject) => {
          const req = indexedDB.open('aijade-research', 1);
          req.onupgradeneeded = () => { req.transaction.abort(); resolve(0); };
          req.onerror = () => resolve(0);
          req.onsuccess = () => {
            const db = req.result;
            if (!db.objectStoreNames.contains('turns')) { db.close(); resolve(0); return; }
            const all = db.transaction('turns').objectStore('turns').getAll();
            all.onsuccess = () => { db.close(); resolve(all.result.map(r => r.json)); };
            all.onerror = () => reject(all.error);
          };
        })
        """;

    [Fact]
    public async Task E_research_telemetry_needs_consent_stays_on_the_device_exports_and_is_deleted_on_withdrawal()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        async Task<string[]> Turns() => await page.EvaluateAsync<JsonElement>(CountResearchTurns) is { ValueKind: JsonValueKind.Array } a
            ? [.. a.EnumerateArray().Select(e => e.GetString()!)] : [];
        async Task Chat(string text)
        {
            await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();
            await page.GetByPlaceholder("Say something…").FillAsync(text);
            await page.GetByRole(AriaRole.Button, new() { Name = "Send" }).ClickAsync();
            await Expect(page.Locator(".bubble.assistant").Last).ToHaveTextAsync(FakeUpstream.Reply);
        }

        await Chat("Thank you, that was wonderful!");
        Assert.Empty(await Turns()); // no consent, nothing kept

        await page.GetByRole(AriaRole.Link, new() { Name = "Settings" }).ClickAsync();
        await page.GetByRole(AriaRole.Checkbox, new() { Name = "Record research telemetry on this device" }).CheckAsync();
        await Chat("Thank you again, you are great!");
        string[] turns = [];
        for (var i = 0; i < 20 && (turns = await Turns()).Length == 0; i++)
            await Task.Delay(250, TestContext.Current.CancellationToken);
        Assert.NotEmpty(turns);
        Assert.All(turns, t => Assert.Contains("\"persona\"", t, StringComparison.Ordinal));
        Assert.All(turns, t => Assert.DoesNotContain("Thank you", t, StringComparison.Ordinal));

        await page.GetByRole(AriaRole.Link, new() { Name = "Settings" }).ClickAsync();
        var download = await page.RunAndWaitForDownloadAsync(() => page.GetByRole(AriaRole.Button, new() { Name = "Export research data" }).ClickAsync());
        Assert.Equal("aijade-research-sessions.jsonl", download.SuggestedFilename);
        await Expect(page.GetByRole(AriaRole.Status)).ToContainTextAsync("records.");

        await page.GetByRole(AriaRole.Checkbox, new() { Name = "Record research telemetry on this device" }).UncheckAsync();
        await Expect(page.GetByRole(AriaRole.Status)).ToHaveTextAsync("Research data on this device deleted.");
        Assert.Empty(await Turns());
        await page.Context.CloseAsync();
    }

    /// <summary>The "microphone" hears a 120 BPM kick drum, synthesized with WebAudio.</summary>
    private const string KickDrumMicrophone = """
        navigator.mediaDevices.getUserMedia = async () => {
          const ctx = new AudioContext();
          await ctx.resume();
          const out = ctx.createMediaStreamDestination();
          const start = ctx.currentTime + 0.1;
          for (let i = 0; i < 240; i++) {
            const t = start + i * 0.5, osc = ctx.createOscillator(), gain = ctx.createGain();
            osc.frequency.value = 60;
            gain.gain.setValueAtTime(0.0001, t);
            gain.gain.exponentialRampToValueAtTime(1, t + 0.005);
            gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.15);
            osc.connect(gain).connect(out);
            osc.start(t); osc.stop(t + 0.2);
          }
          return out.stream;
        };
        """;

    [Fact]
    public async Task D_beat_sync_hears_the_music_and_finds_its_tempo()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        await page.Context.AddInitScriptAsync(KickDrumMicrophone);
        await Expect(page.GetByRole(AriaRole.Group, new() { Name = "Sync motion to the beat" })).ToHaveCountAsync(0); // off by default
        await page.GetByRole(AriaRole.Link, new() { Name = "Settings" }).ClickAsync();
        await page.GetByRole(AriaRole.Checkbox, new() { Name = "Sync motion to the beat" }).CheckAsync();
        await page.ReloadAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();

        var beat = page.GetByRole(AriaRole.Group, new() { Name = "Sync motion to the beat" });
        await beat.GetByRole(AriaRole.Button, new() { Name = "Microphone" }).ClickAsync();
        await Expect(beat.GetByRole(AriaRole.Status)).ToHaveTextAsync(new System.Text.RegularExpressions.Regex(@"^♪ 1(1[5-9]|2[0-5]) BPM"), new() { Timeout = 30_000 });
        await beat.GetByRole(AriaRole.Button, new() { Name = "Stop" }).ClickAsync();
        await Expect(beat.GetByRole(AriaRole.Button, new() { Name = "Microphone" })).ToBeVisibleAsync();
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task D_a_background_picture_and_saved_scenes_dress_the_stage()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Settings" }).ClickAsync();
        // A 1×1 red PNG: uploaded pictures are re-encoded as JPEG data: URLs small enough for browser storage.
        var png = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==");
        await page.Locator("#stage-image-file").SetInputFilesAsync(new FilePayload { Name = "room.png", MimeType = "image/png", Buffer = png });
        await Expect(page.Locator("#stage-image-url")).ToHaveValueAsync("(uploaded picture)");
        await page.Locator("#stage-scene-name").FillAsync("Red room");
        await page.Locator("#stage-scene-save").ClickAsync();
        await Expect(page.Locator(".scene-list li")).ToHaveCountAsync(1);

        await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();
        var stage = page.Locator(".stage");
        await Expect(stage).ToHaveAttributeAsync("style", new System.Text.RegularExpressions.Regex(@"background-image:url\(""data:image/jpeg;base64,"));
        // The canvas is transparent where the avatar does not draw, so the picture shows through.
        await page.WaitForTimeoutAsync(500);
        var cornerAlpha = await page.EvaluateAsync<int>("() => { const c = document.querySelector('.stage canvas'); return c.getContext('2d').getImageData(0, 0, 1, 1).data[3]; }");
        Assert.Equal(0, cornerAlpha);

        // Removing the picture brings back the plain colour; applying the saved scene restores the picture.
        await page.GetByRole(AriaRole.Link, new() { Name = "Settings" }).ClickAsync();
        await page.GetByRole(AriaRole.Button, new() { Name = "Remove picture" }).ClickAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();
        await Expect(stage).Not.ToHaveAttributeAsync("style", new System.Text.RegularExpressions.Regex("background-image"));
        await page.GetByRole(AriaRole.Link, new() { Name = "Settings" }).ClickAsync();
        await page.Locator(".scene-list li").GetByRole(AriaRole.Button, new() { Name = "Apply" }).ClickAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();
        await Expect(stage).ToHaveAttributeAsync("style", new System.Text.RegularExpressions.Regex("background-image:url"));
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task B_a_game_of_chess_with_the_companion()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Chess" }).ClickAsync();
        await page.GetByRole(AriaRole.Button, new() { Name = "New game" }).ClickAsync();
        await Expect(page.GetByRole(AriaRole.Status)).ToHaveTextAsync("Your move.");
        await page.GetByRole(AriaRole.Button, new() { Name = "e2 White ♙" }).ClickAsync();
        await Expect(page.Locator(".sq.target")).ToHaveCountAsync(2); // e3 and e4
        await page.GetByRole(AriaRole.Button, new() { Name = "e4", Exact = true }).ClickAsync();
        // The companion answers with a legal move and a word about it, then it is the user's turn again.
        await Expect(page.Locator(".chess-log li").First).ToContainTextAsync($"— {FakeUpstream.ChessComment}");
        await Expect(page.GetByRole(AriaRole.Status)).ToHaveTextAsync("Your move.");
        await Expect(page.Locator(".chess-side .meta")).ToHaveTextAsync(new System.Text.RegularExpressions.Regex(@"^1\. e4 \S+$"));
        await page.Context.CloseAsync();
    }

    [Fact]
    public async Task I_the_browser_extension_reads_titles_positions_and_subtitles_from_youtube_and_bilibili_pages()
    {
        host.RequireEnabled();
        var page = await host.NewPageAsync();
        var extract = await File.ReadAllTextAsync(Path.Combine(AppContext.BaseDirectory, "fixtures", "extract.js"), TestContext.Current.CancellationToken);
        async Task<JsonElement> Run(string html, string url)
        {
            await page.SetContentAsync(html);
            await page.AddScriptTagAsync(new() { Content = extract.Replace("export function", "window.extractContext = function", StringComparison.Ordinal) });
            return await page.EvaluateAsync<JsonElement>($"() => window.extractContext(document, new URL('{url}'))");
        }
        var yt = await Run("""
            <title>Bees - YouTube</title><h1 class="title">How bees build combs</h1><video></video>
            <span class="ytp-caption-segment">The wax</span><span class="ytp-caption-segment">is warm.</span>
            """, "https://www.youtube.com/watch?v=x");
        Assert.Equal(("YouTube", "video", "How bees build combs", "The wax is warm.", "0:00"),
            (yt.GetProperty("site").GetString(), yt.GetProperty("kind").GetString(), yt.GetProperty("title").GetString(), yt.GetProperty("text").GetString(), yt.GetProperty("position").GetString()));
        var bili = await Run("""
            <title>蜜蜂_哔哩哔哩_bilibili</title><h1 class="video-title">蜜蜂如何筑巢</h1><video></video><div class="bpx-player-subtitle-panel-text">蜂蜡是温热的</div>
            """, "https://www.bilibili.com/video/BV1");
        Assert.Equal(("Bilibili", "蜜蜂如何筑巢", "蜂蜡是温热的"), (bili.GetProperty("site").GetString(), bili.GetProperty("title").GetString(), bili.GetProperty("text").GetString()));
        await page.Context.CloseAsync();
    }

    /// <summary>The "microphone" plays a tone for 1.2 s, then silence: one utterance for voice-activity detection.</summary>
    private const string SpeakingMicrophone = """
        navigator.mediaDevices.getUserMedia = async () => {
          const ctx = new AudioContext();
          await ctx.resume();
          const out = ctx.createMediaStreamDestination();
          const osc = ctx.createOscillator(), gain = ctx.createGain();
          osc.frequency.value = 220;
          gain.gain.setValueAtTime(0, ctx.currentTime);
          gain.gain.setValueAtTime(0.6, ctx.currentTime + 0.3);
          gain.gain.setValueAtTime(0, ctx.currentTime + 1.5);
          osc.connect(gain).connect(out);
          osc.start();
          return out.stream;
        };
        """;

    [Fact]
    public async Task C_with_server_recognition_an_utterance_is_recorded_transcribed_and_sent()
    {
        host.RequireEnabled();
        var (page, _) = await host.SignUpAsync();
        await page.Context.AddInitScriptAsync(SpeakingMicrophone);
        await page.GetByRole(AriaRole.Link, new() { Name = "Settings" }).ClickAsync();
        await page.GetByLabel("Speech recognition").SelectOptionAsync("server");
        await page.ReloadAsync();
        await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();
        var before = host.Llm.Transcriptions.Count;
        await page.GetByTitle("Voice", new() { Exact = true }).ClickAsync();
        // Voice-activity detection ends the utterance after ~0.9 s of quiet; the transcript is sent automatically.
        await Expect(page.Locator(".bubble.user").Last).ToHaveTextAsync(FakeUpstream.Transcript, new() { Timeout = 30_000 });
        await Expect(page.Locator(".bubble.assistant").Last).ToHaveTextAsync(FakeUpstream.Reply);
        var (mime, bytes) = host.Llm.Transcriptions.Skip(before).First();
        Assert.StartsWith("audio/", mime, StringComparison.Ordinal);
        Assert.True(bytes > 1000, $"recorded {bytes} bytes");
        await page.Context.CloseAsync();
    }
}
