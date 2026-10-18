using System.Text.Json.Nodes;

using Aijade.ComputerUse;

using ModelContextProtocol.Client;
using ModelContextProtocol.Protocol;

namespace Aijade.Tests;

/// <summary>Never touches the real desktop: the policy is tested against a fake, the process only waits or refuses.</summary>
public class ComputerUseTests
{
    private sealed class FakeDesktop : IDesktop
    {
        public List<string> Done { get; } = [];

        public Task<(byte[] Png, int Width, int Height)> CaptureAsync(CancellationToken ct) => Task.FromResult((new byte[] { 0x89, 0x50 }, 1440, 900));

        public void Click(int x, int y, string button, int count, IReadOnlyList<string> modifiers) => Done.Add($"click {button} x{count} {x},{y} [{string.Join("+", modifiers)}]");

        public void Drag(int fromX, int fromY, int toX, int toY) => Done.Add($"drag {fromX},{fromY}->{toX},{toY}");

        public void Scroll(int x, int y, string direction, int amount) => Done.Add($"scroll {direction} {amount}");

        public void Type(string text) => Done.Add($"type {text}");

        public void Key(string combo) => Done.Add($"key {combo}");

        public Task<IReadOnlyList<string>> ListAppsAsync(CancellationToken ct) => Task.FromResult<IReadOnlyList<string>>(["Finder", "Safari"]);

        public Task FocusAppAsync(string app, CancellationToken ct)
        {
            Done.Add($"focus {app}");
            return Task.CompletedTask;
        }
    }

    [Fact]
    public async Task Read_only_actions_always_run_and_desktop_changes_need_explicit_allowance()
    {
        var ct = TestContext.Current.CancellationToken;
        var desk = new FakeDesktop();
        var locked = new ComputerUseTool(desk, ComputerUsePolicy.FromEnvironment(null));
        var capture = await locked.RunAsync(new JsonObject { ["action"] = "capture" }, ct);
        Assert.True(capture.Ok && capture.Safe && capture.Png is not null);
        Assert.Equal("Finder\nSafari", (await locked.RunAsync(new JsonObject { ["action"] = "list_apps" }, ct)).Summary);
        var click = await locked.RunAsync(new JsonObject { ["action"] = "click", ["coordinate"] = new JsonArray(10, 20) }, ct);
        Assert.False(click.Ok);
        Assert.StartsWith("blocked:", click.Summary, StringComparison.Ordinal);
        Assert.Empty(desk.Done); // fail-closed: nothing happened

        var some = new ComputerUseTool(desk, ComputerUsePolicy.FromEnvironment("click, key"));
        Assert.StartsWith("blocked", (await some.RunAsync(new JsonObject { ["action"] = "double_click", ["coordinate"] = new JsonArray(10, 20) }, ct)).Summary, StringComparison.Ordinal);
        Assert.True((await some.RunAsync(new JsonObject { ["action"] = "click", ["coordinate"] = new JsonArray(10, 20), ["modifiers"] = new JsonArray("cmd") }, ct)).Ok);
        Assert.True((await some.RunAsync(new JsonObject { ["action"] = "key", ["keys"] = "cmd+s" }, ct)).Ok);
        Assert.False((await some.RunAsync(new JsonObject { ["action"] = "type", ["text"] = "hi" }, ct)).Ok);
        Assert.Equal(["click left x1 10,20 [cmd]", "key cmd+s"], desk.Done);

        var all = new ComputerUseTool(desk, ComputerUsePolicy.FromEnvironment("all"));
        Assert.True((await all.RunAsync(new JsonObject { ["action"] = "right_click", ["coordinate"] = new JsonArray(1, 2) }, ct)).Ok);
        Assert.Equal("click right x1 1,2 []", desk.Done[^1]);
        Assert.False((await all.RunAsync(new JsonObject { ["action"] = "click" }, ct)).Ok); // no coordinate
        Assert.Contains("accessibility", (await all.RunAsync(new JsonObject { ["action"] = "click", ["element"] = 3 }, ct)).Summary, StringComparison.Ordinal);
        // A desktop without an accessibility layer says so instead of pretending.
        Assert.Contains("not available on this platform", (await all.RunAsync(new JsonObject { ["action"] = "capture", ["mode"] = "som" }, ct)).Summary, StringComparison.Ordinal);
        Assert.Contains("not supported", (await all.RunAsync(new JsonObject { ["action"] = "capture", ["mode"] = "x-ray" }, ct)).Summary, StringComparison.Ordinal);
        Assert.Contains("invalid", (await all.RunAsync(new JsonObject { ["action"] = "format_disk" }, ct)).Summary, StringComparison.Ordinal);

        var (mods, key) = KeyCombo.Parse("Command+Shift+Esc");
        Assert.Equal(["cmd", "shift"], mods);
        Assert.Equal("escape", key);
        Assert.Throws<ArgumentException>(() => KeyCombo.Parse("hyper+x"));
    }

    /// <summary>A desktop with an accessibility layer: two elements, an overlay that marks the image, values recorded.</summary>
    private sealed class AccessibleDesktop : IDesktop
    {
        public List<string> Done { get; } = [];

        public List<string?> Apps { get; } = [];

        public Task<(byte[] Png, int Width, int Height)> CaptureAsync(CancellationToken ct) => Task.FromResult((new byte[] { 1, 2, 3 }, 800, 600));

        public void Click(int x, int y, string button, int count, IReadOnlyList<string> modifiers) => Done.Add($"click {x},{y}");

        public void Drag(int fromX, int fromY, int toX, int toY) => Done.Add($"drag {fromX},{fromY}->{toX},{toY}");

        public void Scroll(int x, int y, string direction, int amount) => Done.Add($"scroll {x},{y}");

        public void Type(string text) => Done.Add($"type {text}");

        public void Key(string combo) => Done.Add($"key {combo}");

        public Task<IReadOnlyList<string>> ListAppsAsync(CancellationToken ct) => Task.FromResult<IReadOnlyList<string>>([]);

        public Task FocusAppAsync(string app, CancellationToken ct) => Task.CompletedTask;

        public Task<IReadOnlyList<UiElement>> ElementsAsync(string? app, CancellationToken ct)
        {
            Apps.Add(app);
            return Task.FromResult<IReadOnlyList<UiElement>>([new(1, "Button", "Send", 100, 200, 80, 30), new(2, "TextField", "Message", 10, 10, 300, 24)]);
        }

        public byte[] Annotate(byte[] png, IReadOnlyList<UiElement> elements) => [.. png, (byte)elements.Count];

        public void SetValue(int index, string value) => Done.Add($"set {index}={value}");
    }

    [Fact]
    public async Task Numbered_elements_from_an_accessibility_capture_can_be_clicked_and_filled()
    {
        var ct = TestContext.Current.CancellationToken;
        var desk = new AccessibleDesktop();
        var tool = new ComputerUseTool(desk, ComputerUsePolicy.FromEnvironment("click,drag,set_value"));
        Assert.Contains("run capture", (await tool.RunAsync(new JsonObject { ["action"] = "click", ["element"] = 1 }, ct)).Summary, StringComparison.Ordinal);

        // ax: the numbered list as text, no screenshot.
        var ax = await tool.RunAsync(new JsonObject { ["action"] = "capture", ["mode"] = "ax", ["app"] = "Mail" }, ct);
        Assert.True(ax.Ok && ax.Safe && ax.Png is null);
        Assert.Contains("[1] Button \"Send\" at (100, 200) 80×30", ax.Summary, StringComparison.Ordinal);
        Assert.Contains("[2] TextField \"Message\"", ax.Summary, StringComparison.Ordinal);
        Assert.Equal(["Mail"], desk.Apps);

        // som: the screenshot comes back with the overlay drawn for the same elements.
        var som = await tool.RunAsync(new JsonObject { ["action"] = "capture", ["mode"] = "som" }, ct);
        Assert.Equal(new byte[] { 1, 2, 3, 2 }, som.Png);
        Assert.Contains("2 numbered elements", som.Summary, StringComparison.Ordinal);

        Assert.True((await tool.RunAsync(new JsonObject { ["action"] = "click", ["element"] = 1 }, ct)).Ok);
        Assert.Equal("click 140,215", desk.Done[^1]); // the element's centre
        Assert.True((await tool.RunAsync(new JsonObject { ["action"] = "drag", ["from_element"] = 2, ["to_coordinate"] = new JsonArray(5, 6) }, ct)).Ok);
        Assert.Equal("drag 160,22->5,6", desk.Done[^1]);
        Assert.True((await tool.RunAsync(new JsonObject { ["action"] = "set_value", ["element"] = 2, ["text"] = "hello" }, ct)).Ok);
        Assert.Equal("set 2=hello", desk.Done[^1]);
        Assert.Contains("not in the last capture (1–2)", (await tool.RunAsync(new JsonObject { ["action"] = "click", ["element"] = 9 }, ct)).Summary, StringComparison.Ordinal);
        Assert.False((await tool.RunAsync(new JsonObject { ["action"] = "click", ["element"] = 1.5 }, ct)).Ok);
        // The allowance still applies to element-addressed actions.
        Assert.StartsWith("blocked", (await tool.RunAsync(new JsonObject { ["action"] = "double_click", ["element"] = 1 }, ct)).Summary, StringComparison.Ordinal);
    }

    /// <summary>A w×h opaque black PNG written by hand (stored zlib blocks), so the overlay can be tested without a screen.</summary>
    internal static byte[] BlackPng(int w, int h)
    {
        static uint Crc32(byte[] data)
        {
            var c = 0xFFFFFFFFu;
            foreach (var b in data)
            {
                c ^= b;
                for (var k = 0; k < 8; k++)
                    c = (c & 1) != 0 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            }
            return ~c;
        }
        static void Chunk(BinaryWriter bw, string type, byte[] data)
        {
            var len = BitConverter.GetBytes(data.Length);
            Array.Reverse(len);
            bw.Write(len);
            var td = System.Text.Encoding.ASCII.GetBytes(type).Concat(data).ToArray();
            bw.Write(td);
            var crc = BitConverter.GetBytes(Crc32(td));
            Array.Reverse(crc);
            bw.Write(crc);
        }
        var raw = new byte[h * ((w * 4) + 1)];
        for (var y = 0; y < h; y++)
        {
            for (var x = 0; x < w; x++)
                raw[(y * ((w * 4) + 1)) + 1 + (x * 4) + 3] = 255; // alpha
        }
        using var z = new MemoryStream();
        using (var zs = new System.IO.Compression.ZLibStream(z, System.IO.Compression.CompressionLevel.Optimal, leaveOpen: true))
            zs.Write(raw);
        using var ms = new MemoryStream();
        using var bw = new BinaryWriter(ms);
        bw.Write(new byte[] { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A });
        var ihdr = new byte[13];
        BitConverter.GetBytes(System.Buffers.Binary.BinaryPrimitives.ReverseEndianness(w)).CopyTo(ihdr, 0);
        BitConverter.GetBytes(System.Buffers.Binary.BinaryPrimitives.ReverseEndianness(h)).CopyTo(ihdr, 4);
        ihdr[8] = 8;
        ihdr[9] = 6; // RGBA
        Chunk(bw, "IHDR", ihdr);
        Chunk(bw, "IDAT", z.ToArray());
        Chunk(bw, "IEND", []);
        return ms.ToArray();
    }

    [Fact]
    public void On_macos_the_overlay_marks_the_screenshot_and_keeps_its_size()
    {
        if (!OperatingSystem.IsMacOS())
        {
            Assert.Skip("CoreGraphics overlay is macOS only");
            return;
        }
        var png = BlackPng(120, 60);
        IDesktop desk = new MacDesktop();
        var plain = desk.Annotate(png, []);
        var marked = desk.Annotate(png, [new UiElement(12, "Button", "OK", 10, 10, 60, 30)]);
        static (int W, int H) Size(byte[] p) => (System.Buffers.Binary.BinaryPrimitives.ReadInt32BigEndian(p.AsSpan(16)), System.Buffers.Binary.BinaryPrimitives.ReadInt32BigEndian(p.AsSpan(20)));
        Assert.Equal((120, 60), Size(plain));
        Assert.Equal((120, 60), Size(marked));
        Assert.NotEqual(plain, marked); // the frame and the number were drawn
    }

    [Fact]
    public async Task The_server_process_speaks_mcp_on_stdio_and_refuses_unallowed_actions()
    {
        if (!OperatingSystem.IsMacOS() && !OperatingSystem.IsWindows())
            Assert.Skip("the computer-use server is implemented for macOS and Windows only");
        var ct = TestContext.Current.CancellationToken;
        var dll = typeof(ComputerUseTests).Assembly.GetCustomAttributes(typeof(System.Reflection.AssemblyMetadataAttribute), false)
            .Cast<System.Reflection.AssemblyMetadataAttribute>().Single(a => a.Key == "AijadeComputerUseDll").Value!;
        Assert.True(File.Exists(Path.ChangeExtension(dll, ".runtimeconfig.json")), "runtimeconfig next to the server assembly");
        await using var client = await McpClient.CreateAsync(new StdioClientTransport(new StdioClientTransportOptions
        {
            Name = "computer-use", Command = "dotnet", Arguments = [dll],
            EnvironmentVariables = new Dictionary<string, string?> { ["AIJADE_COMPUTER_USE_ALLOW"] = "" },
        }), cancellationToken: ct);
        var tool = Assert.Single(await client.ListToolsAsync(cancellationToken: ct));
        Assert.Equal("computer_use", tool.Name);
        var waited = await client.CallToolAsync("computer_use", new Dictionary<string, object?> { ["action"] = "wait", ["seconds"] = 0.1 }, cancellationToken: ct);
        Assert.NotEqual(true, waited.IsError);
        var refused = await client.CallToolAsync("computer_use", new Dictionary<string, object?> { ["action"] = "type", ["text"] = "should never be typed" }, cancellationToken: ct);
        Assert.True(refused.IsError);
        Assert.StartsWith("blocked:", ((TextContentBlock)refused.Content[0]).Text, StringComparison.Ordinal);
    }
    [Fact]
    public void Windows_ui_automation_output_is_parsed_and_caller_strings_never_reach_the_script_text()
    {
        var long60 = new string('x', 70);
        var json = $$"""{"window":66310,"elements":[{"role":"Button","name":"保存","x":10,"y":20,"w":80,"h":24,"id":"42.66310.4.7"},{"role":"Edit","name":"{{long60}}","x":5.5,"y":60,"w":200,"h":22,"id":"42.66310.4.8"},{"role":"Button","name":"tiny","x":0,"y":0,"w":1,"h":10,"id":"1"},{"role":"MenuItem","name":"File\nOpen","x":0,"y":0,"w":40,"h":18,"id":"42.1"}]}""";
        var capture = WindowsUiAutomation.ParseElements(json);
        Assert.Equal(66310, capture.Window);
        Assert.Equal([1, 2, 3], capture.Elements.Select(e => e.Index));                 // the 1-pixel element is dropped
        Assert.Equal("保存", capture.Elements[0].Name);
        Assert.Equal(new string('x', 57) + "…", capture.Elements[1].Name);              // shortened as on macOS
        Assert.Equal("File Open", capture.Elements[2].Name);
        Assert.Equal((50, 32), capture.Elements[0].Center);
        Assert.Equal(["42.66310.4.7", "42.66310.4.8", "42.1"], capture.RuntimeIds);
        // a one-element collection written as an object, and an empty one
        Assert.Single(WindowsUiAutomation.ParseElements("""{"window":1,"elements":{"role":"Edit","name":"a","x":0,"y":0,"w":10,"h":10,"id":"7"}}""").Elements);
        Assert.Empty(WindowsUiAutomation.ParseElements("""{"window":1,"elements":[]}""").Elements);

        const string app = "evil'; Remove-Item C:\\ -Recurse; '$(calc)";
        var script = WindowsUiAutomation.ElementsScript(app);
        Assert.DoesNotContain("Remove-Item", script, StringComparison.Ordinal);
        Assert.Contains(Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(app)), script, StringComparison.Ordinal);
        var set = WindowsUiAutomation.SetValueScript(66310, "42.66310.4.8", "x'; Stop-Computer; '");
        Assert.DoesNotContain("Stop-Computer", set, StringComparison.Ordinal);
        Assert.Throws<ArgumentException>(() => WindowsUiAutomation.SetValueScript(1, "42'; calc; '", "v"));
        // annotation boxes travel as a flat list of five numbers per element
        Assert.Contains("$d = @(1,10,20,80,24,2,5.5,60,200,22)", WindowsUiAutomation.AnnotateScript("in.png", "out.png", capture.Elements.Take(2).ToList()), StringComparison.Ordinal);
    }
}
