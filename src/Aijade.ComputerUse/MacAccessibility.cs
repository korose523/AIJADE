using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace Aijade.ComputerUse;

// macOS accessibility captures for mode=ax / som: the frontmost (or named) app's focused window is walked through the
// Accessibility API (AXUIElement), and its actionable elements — buttons, fields, links, menus, checkboxes … — are
// numbered with their frames in screen points. For som the numbers are drawn onto the screenshot with CoreGraphics (frames
// and seven-segment digits, so no font is needed). Needs the Accessibility permission for the process running the server.
public sealed partial class MacDesktop
{
    private const string ApplicationServices = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices";
    private const string ImageIO = "/System/Library/Frameworks/ImageIO.framework/ImageIO";

    [StructLayout(LayoutKind.Sequential)]
    private struct CGSize
    {
        public double Width, Height;
    }

    [LibraryImport(ApplicationServices)]
    [return: MarshalAs(UnmanagedType.U1)]
    private static partial bool AXIsProcessTrusted();

    [LibraryImport(ApplicationServices)]
    private static partial IntPtr AXUIElementCreateApplication(int pid);

    [LibraryImport(ApplicationServices)]
    private static partial int AXUIElementCopyAttributeValue(IntPtr element, IntPtr attribute, out IntPtr value);

    [LibraryImport(ApplicationServices)]
    private static partial int AXUIElementSetAttributeValue(IntPtr element, IntPtr attribute, IntPtr value);

    [LibraryImport(ApplicationServices)]
    [return: MarshalAs(UnmanagedType.U1)]
    private static partial bool AXValueGetValue(IntPtr value, int type, out CGPoint point);

    [LibraryImport(ApplicationServices, EntryPoint = "AXValueGetValue")]
    [return: MarshalAs(UnmanagedType.U1)]
    private static partial bool AXValueGetSize(IntPtr value, int type, out CGSize size);

    [LibraryImport(CoreFoundation)]
    private static unsafe partial IntPtr CFStringCreateWithCharacters(IntPtr alloc, char* chars, nint length);

    [LibraryImport(CoreFoundation)]
    private static partial nint CFStringGetLength(IntPtr s);

    [LibraryImport(CoreFoundation)]
    private static unsafe partial void CFStringGetCharacters(IntPtr s, CFRange range, char* buffer);

    [LibraryImport(CoreFoundation)]
    private static partial nuint CFGetTypeID(IntPtr obj);

    [LibraryImport(CoreFoundation)]
    private static partial nuint CFStringGetTypeID();

    [LibraryImport(CoreFoundation)]
    private static partial nuint CFArrayGetTypeID();

    [LibraryImport(CoreFoundation)]
    private static partial nint CFArrayGetCount(IntPtr array);

    [LibraryImport(CoreFoundation)]
    private static partial IntPtr CFArrayGetValueAtIndex(IntPtr array, nint index);

    [LibraryImport(CoreFoundation)]
    private static partial IntPtr CFRetain(IntPtr obj);

    [LibraryImport(CoreFoundation)]
    private static unsafe partial IntPtr CFDataCreate(IntPtr alloc, byte* bytes, nint length);

    [LibraryImport(CoreFoundation)]
    private static partial IntPtr CFDataCreateMutable(IntPtr alloc, nint capacity);

    [LibraryImport(CoreFoundation)]
    private static partial nint CFDataGetLength(IntPtr data);

    [LibraryImport(CoreFoundation)]
    private static partial IntPtr CFDataGetBytePtr(IntPtr data);

    [StructLayout(LayoutKind.Sequential)]
    private struct CFRange(nint location, nint length)
    {
        public nint Location = location;
        public nint Length = length;
    }

    [LibraryImport(ImageIO)]
    private static partial IntPtr CGImageSourceCreateWithData(IntPtr data, IntPtr options);

    [LibraryImport(ImageIO)]
    private static partial IntPtr CGImageSourceCreateImageAtIndex(IntPtr source, nint index, IntPtr options);

    [LibraryImport(ImageIO)]
    private static partial IntPtr CGImageDestinationCreateWithData(IntPtr data, IntPtr type, nint count, IntPtr options);

    [LibraryImport(ImageIO)]
    private static partial void CGImageDestinationAddImage(IntPtr destination, IntPtr image, IntPtr properties);

    [LibraryImport(ImageIO)]
    [return: MarshalAs(UnmanagedType.U1)]
    private static partial bool CGImageDestinationFinalize(IntPtr destination);

    [LibraryImport(CoreGraphics)]
    private static partial nuint CGImageGetWidth(IntPtr image);

    [LibraryImport(CoreGraphics)]
    private static partial nuint CGImageGetHeight(IntPtr image);

    [LibraryImport(CoreGraphics)]
    private static partial IntPtr CGColorSpaceCreateDeviceRGB();

    [LibraryImport(CoreGraphics)]
    private static partial void CGColorSpaceRelease(IntPtr space);

    [LibraryImport(CoreGraphics)]
    private static partial IntPtr CGBitmapContextCreate(IntPtr data, nuint width, nuint height, nuint bitsPerComponent, nuint bytesPerRow, IntPtr space, uint bitmapInfo);

    [LibraryImport(CoreGraphics)]
    private static partial IntPtr CGBitmapContextCreateImage(IntPtr context);

    [LibraryImport(CoreGraphics)]
    private static partial void CGContextRelease(IntPtr context);

    [LibraryImport(CoreGraphics)]
    private static partial void CGImageRelease(IntPtr image);

    [LibraryImport(CoreGraphics)]
    private static partial void CGContextDrawImage(IntPtr context, CGRect rect, IntPtr image);

    [LibraryImport(CoreGraphics)]
    private static partial void CGContextSetRGBStrokeColor(IntPtr context, double r, double g, double b, double a);

    [LibraryImport(CoreGraphics)]
    private static partial void CGContextSetRGBFillColor(IntPtr context, double r, double g, double b, double a);

    [LibraryImport(CoreGraphics)]
    private static partial void CGContextStrokeRectWithWidth(IntPtr context, CGRect rect, double width);

    [LibraryImport(CoreGraphics)]
    private static partial void CGContextFillRect(IntPtr context, CGRect rect);

    private const int AXValueCGPointType = 1;
    private const int AXValueCGSizeType = 2;
    private const int AXErrorSuccess = 0;
    private const uint PremultipliedLastAlpha = 1;

    /// <summary>Roles worth acting on; containers and static text are walked but not numbered.</summary>
    private static readonly HashSet<string> ActionableRoles = new(StringComparer.Ordinal)
    {
        "AXButton", "AXTextField", "AXTextArea", "AXSearchField", "AXSecureTextField", "AXCheckBox", "AXRadioButton", "AXPopUpButton", "AXComboBox",
        "AXLink", "AXMenuItem", "AXMenuButton", "AXMenuBarItem", "AXSlider", "AXIncrementor", "AXDisclosureTriangle", "AXTab", "AXCell", "AXRow", "AXImage",
    };

    private const int MaxElements = 200;
    private const int MaxDepth = 25;

    private readonly List<IntPtr> lastHandles = [];

    private static unsafe IntPtr CfString(string s)
    {
        fixed (char* p = s)
            return CFStringCreateWithCharacters(IntPtr.Zero, p, s.Length);
    }

    private static unsafe string? ToStringOrNull(IntPtr cf)
    {
        if (cf == IntPtr.Zero || CFGetTypeID(cf) != CFStringGetTypeID())
            return null;
        var length = CFStringGetLength(cf);
        var buffer = new char[length];
        fixed (char* p = buffer)
            CFStringGetCharacters(cf, new CFRange(0, length), p);
        return new string(buffer);
    }

    /// <summary>Copy one attribute (the caller releases a non-zero result).</summary>
    private static IntPtr Copy(IntPtr element, string attribute)
    {
        var name = CfString(attribute);
        try
        {
            return AXUIElementCopyAttributeValue(element, name, out var value) == AXErrorSuccess ? value : IntPtr.Zero;
        }
        finally
        {
            CFRelease(name);
        }
    }

    private static string? Text(IntPtr element, string attribute)
    {
        var v = Copy(element, attribute);
        if (v == IntPtr.Zero)
            return null;
        try
        {
            return ToStringOrNull(v);
        }
        finally
        {
            CFRelease(v);
        }
    }

    private static (double X, double Y, double W, double H)? Frame(IntPtr element)
    {
        var pos = Copy(element, "AXPosition");
        var size = Copy(element, "AXSize");
        try
        {
            return pos != IntPtr.Zero && size != IntPtr.Zero && AXValueGetValue(pos, AXValueCGPointType, out var p) && AXValueGetSize(size, AXValueCGSizeType, out var s)
                ? (p.X, p.Y, s.Width, s.Height) : null;
        }
        finally
        {
            if (pos != IntPtr.Zero)
                CFRelease(pos);
            if (size != IntPtr.Zero)
                CFRelease(size);
        }
    }

    public async Task<IReadOnlyList<UiElement>> ElementsAsync(string? app, CancellationToken ct)
    {
        if (!AXIsProcessTrusted())
            throw new InvalidOperationException("accessibility capture needs the Accessibility permission for the process running this server (System Settings › Privacy & Security › Accessibility)");
        var pid = await PidAsync(app, ct).ConfigureAwait(false);
        ReleaseHandles();
        var root = AXUIElementCreateApplication(pid);
        if (root == IntPtr.Zero)
            throw new InvalidOperationException($"could not open the accessibility tree of process {pid}");
        var found = new List<UiElement>();
        try
        {
            // The focused window holds what the user is looking at; the menu bar is added after it.
            foreach (var start in new[] { "AXFocusedWindow", "AXMenuBar" })
            {
                var top = Copy(root, start);
                if (top == IntPtr.Zero)
                    continue;
                try
                {
                    Walk(top, 0, found);
                }
                finally
                {
                    CFRelease(top);
                }
            }
        }
        finally
        {
            CFRelease(root);
        }
        return found;
    }

    private void Walk(IntPtr element, int depth, List<UiElement> found)
    {
        if (found.Count >= MaxElements || depth > MaxDepth)
            return;
        var role = Text(element, "AXRole") ?? "";
        if (ActionableRoles.Contains(role) && Frame(element) is { W: > 1, H: > 1 } f)
        {
            var name = new[] { Text(element, "AXTitle"), Text(element, "AXDescription"), Text(element, "AXValue"), Text(element, "AXPlaceholderValue"), Text(element, "AXHelp") }
                .FirstOrDefault(s => !string.IsNullOrWhiteSpace(s)) ?? "";
            name = name.ReplaceLineEndings(" ").Trim();
            if (name.Length > 60)
                name = name[..57] + "…";
            lastHandles.Add(CFRetain(element));
            found.Add(new UiElement(found.Count + 1, role.StartsWith("AX", StringComparison.Ordinal) ? role[2..] : role, name, f.X, f.Y, f.W, f.H));
        }
        var children = Copy(element, "AXChildren");
        if (children == IntPtr.Zero)
            return;
        try
        {
            if (CFGetTypeID(children) != CFArrayGetTypeID())
                return;
            var n = CFArrayGetCount(children);
            for (nint i = 0; i < n && found.Count < MaxElements; i++)
                Walk(CFArrayGetValueAtIndex(children, i), depth + 1, found);
        }
        finally
        {
            CFRelease(children);
        }
    }

    private void ReleaseHandles()
    {
        foreach (var h in lastHandles)
            CFRelease(h);
        lastHandles.Clear();
    }

    public void SetValue(int index, string value)
    {
        if (index < 1 || index > lastHandles.Count)
            throw new ArgumentException($"element {index} is not in the last capture");
        var name = CfString("AXValue");
        var text = CfString(value);
        try
        {
            var err = AXUIElementSetAttributeValue(lastHandles[index - 1], name, text);
            if (err != AXErrorSuccess)
                throw new InvalidOperationException($"the element did not accept a value (AXError {err}); click it and type instead");
        }
        finally
        {
            CFRelease(text);
            CFRelease(name);
        }
    }

    private static async Task<int> PidAsync(string? app, CancellationToken ct)
    {
        // lsappinfo needs no extra permission; "front" is the application the user is working in.
        var asn = app is { Length: > 0 } ? app : await RunAsync("/usr/bin/lsappinfo", ["front"], ct).ConfigureAwait(false);
        var info = await RunAsync("/usr/bin/lsappinfo", ["info", "-only", "pid", asn], ct).ConfigureAwait(false);
        var m = System.Text.RegularExpressions.Regex.Match(info, "\"pid\"\\s*=\\s*(\\d+)");
        return m.Success ? int.Parse(m.Groups[1].Value, System.Globalization.CultureInfo.InvariantCulture)
            : throw new InvalidOperationException(app is null ? "could not find the frontmost application" : $"application '{app}' is not running");
    }

    // ---- som overlay -------------------------------------------------------------------------------------------------

    // Seven-segment digits: segments a b c d e f g (top, top-right, bottom-right, bottom, bottom-left, top-left, middle).
    private static readonly string[] Segments = ["abcdef", "bc", "abged", "abgcd", "fgbc", "afgcd", "afgedc", "abc", "abcdefg", "abcdfg"];

    public unsafe byte[] Annotate(byte[] png, IReadOnlyList<UiElement> elements)
    {
        IntPtr data, source = IntPtr.Zero, image = IntPtr.Zero, space = IntPtr.Zero, ctx = IntPtr.Zero, outImage = IntPtr.Zero, outData = IntPtr.Zero, dest = IntPtr.Zero, type = IntPtr.Zero;
        fixed (byte* p = png)
            data = CFDataCreate(IntPtr.Zero, p, png.Length);
        try
        {
            source = CGImageSourceCreateWithData(data, IntPtr.Zero);
            image = source == IntPtr.Zero ? IntPtr.Zero : CGImageSourceCreateImageAtIndex(source, 0, IntPtr.Zero);
            if (image == IntPtr.Zero)
                throw new InvalidOperationException("the screenshot could not be decoded for the overlay");
            var w = CGImageGetWidth(image);
            var h = CGImageGetHeight(image);
            space = CGColorSpaceCreateDeviceRGB();
            ctx = CGBitmapContextCreate(IntPtr.Zero, w, h, 8, 0, space, PremultipliedLastAlpha);
            CGContextDrawImage(ctx, new CGRect { X = 0, Y = 0, Width = w, Height = h }, image);
            foreach (var e in elements)
            {
                // CoreGraphics' origin is bottom-left; element frames are top-left screen points (the screenshot is in points).
                var y = h - e.Y - e.Height;
                CGContextSetRGBStrokeColor(ctx, 1, 0.15, 0.3, 0.9);
                CGContextStrokeRectWithWidth(ctx, new CGRect { X = e.X, Y = y, Width = e.Width, Height = e.Height }, 2);
                DrawLabel(ctx, e.Index, e.X, h - e.Y);
            }
            outImage = CGBitmapContextCreateImage(ctx);
            outData = CFDataCreateMutable(IntPtr.Zero, 0);
            type = CfString("public.png");
            dest = CGImageDestinationCreateWithData(outData, type, 1, IntPtr.Zero);
            CGImageDestinationAddImage(dest, outImage, IntPtr.Zero);
            if (!CGImageDestinationFinalize(dest))
                throw new InvalidOperationException("the annotated screenshot could not be encoded");
            var bytes = new byte[CFDataGetLength(outData)];
            Marshal.Copy(CFDataGetBytePtr(outData), bytes, 0, bytes.Length);
            return bytes;
        }
        finally
        {
            foreach (var cf in new[] { dest, type, outData, source, data })
            {
                if (cf != IntPtr.Zero)
                    CFRelease(cf);
            }
            if (outImage != IntPtr.Zero)
                CGImageRelease(outImage);
            if (ctx != IntPtr.Zero)
                CGContextRelease(ctx);
            if (space != IntPtr.Zero)
                CGColorSpaceRelease(space);
            if (image != IntPtr.Zero)
                CGImageRelease(image);
        }
    }

    /// <summary>A filled tag with the number in white seven-segment digits, anchored at the element's top-left corner.</summary>
    private static void DrawLabel(IntPtr ctx, int number, double left, double top)
    {
        const double dw = 7, dh = 12, gap = 2, pad = 2, t = 1.6;
        var digits = number.ToString(System.Globalization.CultureInfo.InvariantCulture);
        var width = (digits.Length * (dw + gap)) - gap + (2 * pad);
        var height = dh + (2 * pad);
        CGContextSetRGBFillColor(ctx, 1, 0.15, 0.3, 0.92);
        CGContextFillRect(ctx, new CGRect { X = left, Y = top - height, Width = width, Height = height });
        CGContextSetRGBFillColor(ctx, 1, 1, 1, 1);
        var x = left + pad;
        var bottom = top - height + pad;
        foreach (var ch in digits)
        {
            foreach (var seg in Segments[ch - '0'])
            {
                var r = seg switch
                {
                    'a' => new CGRect { X = x, Y = bottom + dh - t, Width = dw, Height = t },
                    'b' => new CGRect { X = x + dw - t, Y = bottom + (dh / 2), Width = t, Height = dh / 2 },
                    'c' => new CGRect { X = x + dw - t, Y = bottom, Width = t, Height = dh / 2 },
                    'd' => new CGRect { X = x, Y = bottom, Width = dw, Height = t },
                    'e' => new CGRect { X = x, Y = bottom, Width = t, Height = dh / 2 },
                    'f' => new CGRect { X = x, Y = bottom + (dh / 2), Width = t, Height = dh / 2 },
                    _ => new CGRect { X = x, Y = bottom + (dh / 2) - (t / 2), Width = dw, Height = t },
                };
                CGContextFillRect(ctx, r);
            }
            x += dw + gap;
        }
    }
}
