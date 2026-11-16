using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace Aijade.ComputerUse;

/// <summary>
/// Windows: mouse and keyboard through SendInput (Unicode text as KEYEVENTF_UNICODE, independent of the keyboard layout),
/// screenshots with Windows PowerShell's System.Drawing, apps from processes with a main window, numbered elements and
/// set_value through UI Automation (<see cref="WindowsUiAutomation"/>). Built but not run on the author's development
/// machine (macOS); coordinates are logical (DPI-scaled) pixels of the primary screen, as long as this process and the
/// PowerShell helpers share the same (default, unaware) DPI awareness.
/// </summary>
[SupportedOSPlatform("windows")]
public sealed partial class WindowsDesktop : IDesktop
{
    [StructLayout(LayoutKind.Sequential)]
    private struct MouseInput
    {
        public int Dx, Dy, MouseData;
        public uint Flags, Time;
        public IntPtr ExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct KeybdInput
    {
        public ushort Vk, Scan;
        public uint Flags, Time;
        public IntPtr ExtraInfo;
    }

    [StructLayout(LayoutKind.Explicit)]
    private struct InputUnion
    {
        [FieldOffset(0)] public MouseInput Mouse;
        [FieldOffset(0)] public KeybdInput Keyboard;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Input
    {
        public uint Type;
        public InputUnion U;
    }

    [LibraryImport("user32.dll", SetLastError = true)]
    private static partial uint SendInput(uint count, [In] Input[] inputs, int size);

    [LibraryImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool SetCursorPos(int x, int y);

    [LibraryImport("user32.dll")]
    private static partial int GetSystemMetrics(int index);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool SetForegroundWindow(IntPtr window);

    private const uint MouseType = 0, KeyboardType = 1;
    private const uint KeyUp = 0x2, Unicode = 0x4;
    private const uint Wheel = 0x800, HWheel = 0x1000;

    private static readonly Dictionary<string, ushort> Vk = new(StringComparer.Ordinal)
    {
        ["enter"] = 0x0D, ["tab"] = 0x09, ["space"] = 0x20, ["backspace"] = 0x08, ["delete"] = 0x2E, ["escape"] = 0x1B, ["home"] = 0x24, ["end"] = 0x23,
        ["pageup"] = 0x21, ["pagedown"] = 0x22, ["left"] = 0x25, ["up"] = 0x26, ["right"] = 0x27, ["down"] = 0x28,
        ["cmd"] = 0x11, ["ctrl"] = 0x11, ["shift"] = 0x10, ["alt"] = 0x12, ["option"] = 0x12, ["win"] = 0x5B, ["windows"] = 0x5B, ["super"] = 0x5B, ["meta"] = 0x5B,
    };

    private static ushort KeyCode(string key)
    {
        if (Vk.TryGetValue(key, out var vk))
            return vk;
        if (key.Length == 1 && char.IsAsciiLetterOrDigit(key[0]))
            return char.ToUpperInvariant(key[0]);
        if (key.Length is 2 or 3 && key[0] == 'f' && int.TryParse(key[1..], out var n) && n is >= 1 and <= 12)
            return (ushort)(0x70 + n - 1);
        throw new ArgumentException($"unknown key '{key}'");
    }

    private static void Send(params Input[] inputs)
    {
        if (SendInput((uint)inputs.Length, inputs, Marshal.SizeOf<Input>()) != inputs.Length)
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "SendInput was blocked (another app may have higher integrity)");
    }

    private static Input Mouse(uint flags, int data = 0) => new() { Type = MouseType, U = new InputUnion { Mouse = new MouseInput { Flags = flags, MouseData = data } } };

    private static Input Key(ushort vk, bool up) => new() { Type = KeyboardType, U = new InputUnion { Keyboard = new KeybdInput { Vk = vk, Flags = up ? KeyUp : 0 } } };

    private WindowsUiAutomation.Capture? lastCapture;

    private static ProcessStartInfo PowerShell(string script)
    {
        var psi = new ProcessStartInfo("powershell.exe")
        {
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8, StandardErrorEncoding = System.Text.Encoding.UTF8,
        };
        foreach (var a in new[] { "-NoProfile", "-NonInteractive", "-Command", script })
            psi.ArgumentList.Add(a);
        return psi;
    }

    private static async Task<string> RunPowerShellAsync(string script, CancellationToken ct)
    {
        using var p = Process.Start(PowerShell(script)) ?? throw new InvalidOperationException("could not start PowerShell");
        var stdout = p.StandardOutput.ReadToEndAsync(ct);
        var stderr = p.StandardError.ReadToEndAsync(ct);
        await p.WaitForExitAsync(ct).ConfigureAwait(false);
        return p.ExitCode == 0 ? await stdout.ConfigureAwait(false) : throw new InvalidOperationException(Failure(await stderr.ConfigureAwait(false)));
    }

    private static string RunPowerShell(string script)
    {
        using var p = Process.Start(PowerShell(script)) ?? throw new InvalidOperationException("could not start PowerShell");
        var stderr = p.StandardError.ReadToEndAsync();
        var stdout = p.StandardOutput.ReadToEnd();
        p.WaitForExit();
        return p.ExitCode == 0 ? stdout : throw new InvalidOperationException(Failure(stderr.GetAwaiter().GetResult()));
    }

    /// <summary>The first line of a PowerShell error record (the thrown message), without the position block.</summary>
    private static string Failure(string stderr) =>
        stderr.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).FirstOrDefault() ?? "PowerShell failed";

    public async Task<(byte[] Png, int Width, int Height)> CaptureAsync(CancellationToken ct)
    {
        var file = Path.Combine(Path.GetTempPath(), $"aijade-capture-{Guid.NewGuid():N}.png");
        var script = "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; $b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; " +
                     "$i=New-Object System.Drawing.Bitmap $b.Width,$b.Height; $g=[System.Drawing.Graphics]::FromImage($i); $g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); " +
                     $"$i.Save('{file}',[System.Drawing.Imaging.ImageFormat]::Png)";
        try
        {
            await RunPowerShellAsync(script, ct).ConfigureAwait(false);
            if (!File.Exists(file))
                throw new InvalidOperationException("the screenshot could not be taken");
            return (await File.ReadAllBytesAsync(file, ct).ConfigureAwait(false), GetSystemMetrics(0), GetSystemMetrics(1));
        }
        finally
        {
            File.Delete(file);
        }
    }

    public void Click(int x, int y, string button, int count, IReadOnlyList<string> modifiers)
    {
        var mods = modifiers.Select(KeyCode).ToList();
        foreach (var m in mods)
            Send(Key(m, false));
        SetCursorPos(x, y);
        var (down, up) = button switch { "right" => (0x8u, 0x10u), "middle" => (0x20u, 0x40u), _ => (0x2u, 0x4u) };
        for (var i = 0; i < count; i++)
            Send(Mouse(down), Mouse(up));
        foreach (var m in Enumerable.Reverse(mods))
            Send(Key(m, true));
    }

    public void Drag(int fromX, int fromY, int toX, int toY)
    {
        SetCursorPos(fromX, fromY);
        Send(Mouse(0x2));
        for (var step = 1; step <= 10; step++)
        {
            SetCursorPos(fromX + ((toX - fromX) * step / 10), fromY + ((toY - fromY) * step / 10));
            Thread.Sleep(15);
        }
        Send(Mouse(0x4));
    }

    public void Scroll(int x, int y, string direction, int amount)
    {
        if (x >= 0 && y >= 0)
            SetCursorPos(x, y);
        Send(direction switch
        {
            "up" => Mouse(Wheel, 120 * amount),
            "down" => Mouse(Wheel, -120 * amount),
            "left" => Mouse(HWheel, -120 * amount),
            _ => Mouse(HWheel, 120 * amount),
        });
    }

    public void Type(string text)
    {
        foreach (var c in text)
        {
            Send(new Input { Type = KeyboardType, U = new InputUnion { Keyboard = new KeybdInput { Scan = c, Flags = Unicode } } },
                 new Input { Type = KeyboardType, U = new InputUnion { Keyboard = new KeybdInput { Scan = c, Flags = Unicode | KeyUp } } });
        }
    }

    public void Key(string combo)
    {
        var (modifiers, key) = KeyCombo.Parse(combo);
        var codes = modifiers.Select(KeyCode).Append(KeyCode(key)).ToList();
        foreach (var c in codes)
            Send(Key(c, false));
        foreach (var c in Enumerable.Reverse(codes))
            Send(Key(c, true));
    }

    public Task<IReadOnlyList<string>> ListAppsAsync(CancellationToken ct) => Task.FromResult<IReadOnlyList<string>>(
        [.. Process.GetProcesses().Where(p => p.MainWindowHandle != IntPtr.Zero && p.MainWindowTitle.Length > 0).Select(p => $"{p.ProcessName}: {p.MainWindowTitle}").Order(StringComparer.Ordinal)]);

    public Task FocusAppAsync(string app, CancellationToken ct)
    {
        var target = Process.GetProcesses().FirstOrDefault(p => p.MainWindowHandle != IntPtr.Zero &&
            (p.ProcessName.Equals(app, StringComparison.OrdinalIgnoreCase) || p.MainWindowTitle.Contains(app, StringComparison.OrdinalIgnoreCase)))
            ?? throw new InvalidOperationException($"no window for '{app}'");
        SetForegroundWindow(target.MainWindowHandle);
        return Task.CompletedTask;
    }

    public async Task<IReadOnlyList<UiElement>> ElementsAsync(string? app, CancellationToken ct)
    {
        lastCapture = WindowsUiAutomation.ParseElements(await RunPowerShellAsync(WindowsUiAutomation.ElementsScript(app), ct).ConfigureAwait(false));
        return lastCapture.Elements;
    }

    public void SetValue(int index, string value)
    {
        if (lastCapture is not { } capture || index < 1 || index > capture.Elements.Count)
            throw new ArgumentException($"element {index} is not in the last capture");
        RunPowerShell(WindowsUiAutomation.SetValueScript(capture.Window, capture.RuntimeIds[index - 1], value));
    }

    public byte[] Annotate(byte[] png, IReadOnlyList<UiElement> elements)
    {
        var input = Path.Combine(Path.GetTempPath(), $"aijade-som-{Guid.NewGuid():N}.png");
        var output = Path.ChangeExtension(input, ".annotated.png");
        try
        {
            File.WriteAllBytes(input, png);
            RunPowerShell(WindowsUiAutomation.AnnotateScript(input, output, elements));
            return File.ReadAllBytes(output);
        }
        finally
        {
            File.Delete(input);
            File.Delete(output);
        }
    }
}
