using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace Aijade.ComputerUse;

/// <summary>
/// macOS: mouse and keyboard through CoreGraphics events, screenshots with screencapture (scaled to points with sips so a
/// capture's pixels are the coordinates clicks use), apps through System Events. Needs the Accessibility and Screen
/// Recording permissions for the process that runs this server; macOS asks the first time.
/// </summary>
[SupportedOSPlatform("macos")]
public sealed partial class MacDesktop : IDesktop
{
    private const string CoreGraphics = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics";
    private const string CoreFoundation = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation";

    [StructLayout(LayoutKind.Sequential)]
    private struct CGPoint(double x, double y)
    {
        public double X = x;
        public double Y = y;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct CGRect
    {
        public double X, Y, Width, Height;
    }

    [LibraryImport(CoreGraphics)]
    private static partial IntPtr CGEventCreateMouseEvent(IntPtr source, uint type, CGPoint point, uint button);

    [LibraryImport(CoreGraphics)]
    private static partial IntPtr CGEventCreateKeyboardEvent(IntPtr source, ushort keycode, [MarshalAs(UnmanagedType.U1)] bool down);

    [LibraryImport(CoreGraphics)]
    private static unsafe partial void CGEventKeyboardSetUnicodeString(IntPtr ev, nuint length, char* text);

    [LibraryImport(CoreGraphics)]
    private static partial IntPtr CGEventCreateScrollWheelEvent2(IntPtr source, uint units, uint wheelCount, int wheel1, int wheel2, int wheel3);

    [LibraryImport(CoreGraphics)]
    private static partial void CGEventSetFlags(IntPtr ev, ulong flags);

    [LibraryImport(CoreGraphics)]
    private static partial void CGEventSetIntegerValueField(IntPtr ev, uint field, long value);

    [LibraryImport(CoreGraphics)]
    private static partial void CGEventPost(uint tap, IntPtr ev);

    [LibraryImport(CoreGraphics)]
    private static partial uint CGMainDisplayID();

    [LibraryImport(CoreGraphics)]
    private static partial CGRect CGDisplayBounds(uint display);

    [LibraryImport(CoreFoundation)]
    private static partial void CFRelease(IntPtr obj);

    private const uint HidTap = 0;
    private const uint ClickStateField = 1;

    private static readonly Dictionary<string, ulong> Flags = new(StringComparer.Ordinal)
    {
        ["cmd"] = 0x100000, ["meta"] = 0x100000, ["super"] = 0x100000, ["win"] = 0x100000, ["windows"] = 0x100000,
        ["shift"] = 0x20000, ["option"] = 0x80000, ["alt"] = 0x80000, ["ctrl"] = 0x40000, ["fn"] = 0x800000,
    };

    // US layout virtual key codes (kVK_*).
    private static readonly Dictionary<string, ushort> Keys = new(StringComparer.Ordinal)
    {
        ["a"] = 0x00, ["s"] = 0x01, ["d"] = 0x02, ["f"] = 0x03, ["h"] = 0x04, ["g"] = 0x05, ["z"] = 0x06, ["x"] = 0x07, ["c"] = 0x08, ["v"] = 0x09,
        ["b"] = 0x0B, ["q"] = 0x0C, ["w"] = 0x0D, ["e"] = 0x0E, ["r"] = 0x0F, ["y"] = 0x10, ["t"] = 0x11, ["1"] = 0x12, ["2"] = 0x13, ["3"] = 0x14,
        ["4"] = 0x15, ["6"] = 0x16, ["5"] = 0x17, ["="] = 0x18, ["9"] = 0x19, ["7"] = 0x1A, ["-"] = 0x1B, ["8"] = 0x1C, ["0"] = 0x1D, ["]"] = 0x1E,
        ["o"] = 0x1F, ["u"] = 0x20, ["["] = 0x21, ["i"] = 0x22, ["p"] = 0x23, ["l"] = 0x25, ["j"] = 0x26, ["'"] = 0x27, ["k"] = 0x28, [";"] = 0x29,
        ["\\"] = 0x2A, [","] = 0x2B, ["/"] = 0x2C, ["n"] = 0x2D, ["m"] = 0x2E, ["."] = 0x2F, ["`"] = 0x32,
        ["enter"] = 0x24, ["tab"] = 0x30, ["space"] = 0x31, ["delete"] = 0x33, ["backspace"] = 0x33, ["escape"] = 0x35, ["forwarddelete"] = 0x75,
        ["home"] = 0x73, ["end"] = 0x77, ["pageup"] = 0x74, ["pagedown"] = 0x79, ["left"] = 0x7B, ["right"] = 0x7C, ["down"] = 0x7D, ["up"] = 0x7E,
        ["f1"] = 0x7A, ["f2"] = 0x78, ["f3"] = 0x63, ["f4"] = 0x76, ["f5"] = 0x60, ["f6"] = 0x61, ["f7"] = 0x62, ["f8"] = 0x64, ["f9"] = 0x65,
        ["f10"] = 0x6D, ["f11"] = 0x67, ["f12"] = 0x6F,
    };

    private static void Post(IntPtr ev)
    {
        if (ev == IntPtr.Zero)
            throw new InvalidOperationException("CoreGraphics could not create the event (is Accessibility permission granted?)");
        CGEventPost(HidTap, ev);
        CFRelease(ev);
    }

    private static ulong FlagsOf(IEnumerable<string> modifiers) => modifiers.Aggregate(0UL, (f, m) => f | (Flags.TryGetValue(m, out var v) ? v : 0));

    public async Task<(byte[] Png, int Width, int Height)> CaptureAsync(CancellationToken ct)
    {
        var bounds = CGDisplayBounds(CGMainDisplayID());
        var file = Path.Combine(Path.GetTempPath(), $"aijade-capture-{Guid.NewGuid():N}.png");
        try
        {
            await RunAsync("/usr/sbin/screencapture", ["-x", "-t", "png", file], ct).ConfigureAwait(false);
            if (!File.Exists(file))
                throw new InvalidOperationException("screencapture produced no image (is Screen Recording permission granted?)");
            await RunAsync("/usr/bin/sips", ["--resampleWidth", ((int)bounds.Width).ToString(System.Globalization.CultureInfo.InvariantCulture), file], ct).ConfigureAwait(false);
            return (await File.ReadAllBytesAsync(file, ct).ConfigureAwait(false), (int)bounds.Width, (int)bounds.Height);
        }
        finally
        {
            File.Delete(file);
        }
    }

    public void Click(int x, int y, string button, int count, IReadOnlyList<string> modifiers)
    {
        var (down, up, cgButton) = button switch { "right" => (3u, 4u, 1u), "middle" => (25u, 26u, 2u), _ => (1u, 2u, 0u) };
        var flags = FlagsOf(modifiers);
        Post(CGEventCreateMouseEvent(IntPtr.Zero, 5, new CGPoint(x, y), 0)); // move there first
        for (var i = 1; i <= count; i++)
        {
            foreach (var type in new[] { down, up })
            {
                var ev = CGEventCreateMouseEvent(IntPtr.Zero, type, new CGPoint(x, y), cgButton);
                CGEventSetIntegerValueField(ev, ClickStateField, i);
                if (flags != 0)
                    CGEventSetFlags(ev, flags);
                Post(ev);
            }
        }
    }

    public void Drag(int fromX, int fromY, int toX, int toY)
    {
        Post(CGEventCreateMouseEvent(IntPtr.Zero, 5, new CGPoint(fromX, fromY), 0));
        Post(CGEventCreateMouseEvent(IntPtr.Zero, 1, new CGPoint(fromX, fromY), 0));
        for (var step = 1; step <= 10; step++)
        {
            Post(CGEventCreateMouseEvent(IntPtr.Zero, 6, new CGPoint(fromX + ((toX - fromX) * step / 10.0), fromY + ((toY - fromY) * step / 10.0)), 0));
            Thread.Sleep(15);
        }
        Post(CGEventCreateMouseEvent(IntPtr.Zero, 2, new CGPoint(toX, toY), 0));
    }

    public void Scroll(int x, int y, string direction, int amount)
    {
        if (x >= 0 && y >= 0)
            Post(CGEventCreateMouseEvent(IntPtr.Zero, 5, new CGPoint(x, y), 0));
        var (vertical, horizontal) = direction switch { "up" => (amount, 0), "down" => (-amount, 0), "left" => (0, amount), _ => (0, -amount) };
        Post(CGEventCreateScrollWheelEvent2(IntPtr.Zero, 1, 2, vertical, horizontal, 0));
    }

    public unsafe void Type(string text)
    {
        // Unicode text in small chunks: independent of keyboard layout, works for CJK.
        foreach (var chunk in text.Chunk(16))
        {
            foreach (var down in new[] { true, false })
            {
                var ev = CGEventCreateKeyboardEvent(IntPtr.Zero, 0, down);
                fixed (char* p = chunk)
                    CGEventKeyboardSetUnicodeString(ev, (nuint)chunk.Length, p);
                Post(ev);
            }
        }
    }

    public void Key(string combo)
    {
        var (modifiers, key) = KeyCombo.Parse(combo);
        if (!Keys.TryGetValue(key, out var code))
            throw new ArgumentException($"unknown key '{key}'");
        var flags = FlagsOf(modifiers);
        foreach (var down in new[] { true, false })
        {
            var ev = CGEventCreateKeyboardEvent(IntPtr.Zero, code, down);
            if (flags != 0)
                CGEventSetFlags(ev, flags);
            Post(ev);
        }
    }

    public async Task<IReadOnlyList<string>> ListAppsAsync(CancellationToken ct) =>
        (await RunAsync("/usr/bin/osascript", ["-e", "tell application \"System Events\" to get name of every process whose background only is false"], ct).ConfigureAwait(false))
            .Split(", ", StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);

    public Task FocusAppAsync(string app, CancellationToken ct) => RunAsync("/usr/bin/open", ["-a", app], ct);

    private static async Task<string> RunAsync(string file, IReadOnlyList<string> args, CancellationToken ct)
    {
        var psi = new ProcessStartInfo(file) { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
        foreach (var a in args)
            psi.ArgumentList.Add(a);
        using var p = Process.Start(psi) ?? throw new InvalidOperationException($"could not start {file}");
        var output = await p.StandardOutput.ReadToEndAsync(ct).ConfigureAwait(false);
        var error = await p.StandardError.ReadToEndAsync(ct).ConfigureAwait(false);
        await p.WaitForExitAsync(ct).ConfigureAwait(false);
        return p.ExitCode == 0 ? output.Trim() : throw new InvalidOperationException($"{Path.GetFileName(file)} failed: {error.Trim()}");
    }
}
