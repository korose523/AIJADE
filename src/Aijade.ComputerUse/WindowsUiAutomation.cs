using System.Globalization;
using System.Text;
using System.Text.Json;

namespace Aijade.ComputerUse;

/// <summary>
/// The Windows accessibility capture as Windows PowerShell scripts over the UI Automation client assemblies that ship with
/// Windows (the same route as the screenshot), and the parsing of their output. Kept free of Windows APIs so that the
/// scripts and the parser can be tested on any platform. Strings from the caller (an application name, a value to set)
/// reach a script only base64-encoded, never as script text.
/// </summary>
public static class WindowsUiAutomation
{
    public const int MaxElements = 200;

    /// <summary>UI Automation control types a user can act on (the counterpart of the macOS actionable roles).</summary>
    public static readonly IReadOnlyList<string> ActionableTypes =
    [
        "Button", "Edit", "CheckBox", "RadioButton", "ComboBox", "Hyperlink", "ListItem", "MenuItem", "TabItem", "TreeItem",
        "Slider", "SplitButton", "Document", "DataItem", "Spinner",
    ];

    private static string B64(string? s) => Convert.ToBase64String(Encoding.UTF8.GetBytes(s ?? ""));

    /// <summary>A single-quoted PowerShell literal (quotes doubled), for paths the server itself created.</summary>
    private static string Quote(string s) => "'" + s.Replace("'", "''", StringComparison.Ordinal) + "'";

    private const string Prelude =
        "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; " +
        "Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes; $A=[System.Windows.Automation.AutomationElement]; ";

    /// <summary>
    /// List the actionable, visible, enabled elements of the foreground window (or of <paramref name="app"/>'s main window) as
    /// JSON: {"window": handle, "elements": [{role, name, x, y, w, h, id}]}, in the order UI Automation returns them.
    /// </summary>
    public static string ElementsScript(string? app) =>
        Prelude +
        $"$app=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{B64(app)}')); " +
        "if ($app) { $p = Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and ($_.ProcessName -ieq $app -or $_.MainWindowTitle -like ('*' + $app + '*')) } | Select-Object -First 1; " +
        "if (-not $p) { throw ('no window for ''' + $app + '''') }; $h = $p.MainWindowHandle } " +
        "else { Add-Type 'using System; using System.Runtime.InteropServices; public static class AijadeFg { [DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow(); }'; $h = [AijadeFg]::GetForegroundWindow() }; " +
        "$root = $A::FromHandle($h); " +
        $"$types = @({string.Join(",", ActionableTypes.Select(t => $"'{t}'"))}); " +
        "$out = New-Object System.Collections.ArrayList; " +
        "foreach ($e in $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)) { " +
        $"if ($out.Count -ge {MaxElements}) {{ break }}; $c = $e.Current; $t = $c.ControlType.ProgrammaticName -replace '^ControlType\\.', ''; " +
        "if ($types -notcontains $t -or $c.IsOffscreen -or -not $c.IsEnabled) { continue }; $r = $c.BoundingRectangle; " +
        "if ($r.IsEmpty -or $r.Width -le 1 -or $r.Height -le 1) { continue }; " +
        "[void]$out.Add([pscustomobject]@{ role = $t; name = $c.Name; x = $r.X; y = $r.Y; w = $r.Width; h = $r.Height; id = ($e.GetRuntimeId() -join '.') }) }; " +
        "@{ window = [int64]$h; elements = $out } | ConvertTo-Json -Depth 4 -Compress";

    /// <summary>The window and the UI Automation runtime ids of a capture, in element order (what set_value needs).</summary>
    public sealed record Capture(long Window, IReadOnlyList<UiElement> Elements, IReadOnlyList<string> RuntimeIds);

    /// <summary>Parse the output of <see cref="ElementsScript"/>; elements are numbered from 1 and their names shortened as on macOS.</summary>
    public static Capture ParseElements(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        var window = root.TryGetProperty("window", out var w) && w.ValueKind == JsonValueKind.Number ? w.GetInt64() : 0;
        var elements = new List<UiElement>();
        var ids = new List<string>();
        if (root.TryGetProperty("elements", out var list))
        {
            // ConvertTo-Json writes a one-element collection as an object in some PowerShell versions
            var items = list.ValueKind == JsonValueKind.Array ? list.EnumerateArray().ToList() : list.ValueKind == JsonValueKind.Object ? [list] : [];
            foreach (var e in items)
            {
                double N(string name) => e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : 0;
                var (width, height) = (N("w"), N("h"));
                if (width <= 1 || height <= 1 || elements.Count >= MaxElements)
                    continue;
                var name = (e.TryGetProperty("name", out var n) && n.ValueKind == JsonValueKind.String ? n.GetString() ?? "" : "").ReplaceLineEndings(" ").Trim();
                if (name.Length > 60)
                    name = name[..57] + "…";
                var role = e.TryGetProperty("role", out var r) && r.ValueKind == JsonValueKind.String ? r.GetString() ?? "" : "";
                elements.Add(new UiElement(elements.Count + 1, role, name, N("x"), N("y"), width, height));
                ids.Add(e.TryGetProperty("id", out var id) && id.ValueKind == JsonValueKind.String ? id.GetString() ?? "" : "");
            }
        }
        return new Capture(window, elements, ids);
    }

    /// <summary>Set the value of the element with <paramref name="runtimeId"/> in <paramref name="window"/> through its ValuePattern.</summary>
    public static string SetValueScript(long window, string runtimeId, string value)
    {
        if (runtimeId.Length == 0 || !runtimeId.Split('.').All(p => int.TryParse(p, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out _)))
            throw new ArgumentException($"not a UI Automation runtime id: '{runtimeId}'", nameof(runtimeId));
        return Prelude +
            $"$root = $A::FromHandle([IntPtr]{window.ToString(CultureInfo.InvariantCulture)}); " +
            $"$id = [int[]]('{runtimeId}'.Split('.')); " +
            "$e = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, (New-Object System.Windows.Automation.PropertyCondition($A::RuntimeIdProperty, $id))); " +
            "if (-not $e) { throw 'the element is no longer there; capture again' }; " +
            $"$v = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{B64(value)}')); $p = $null; " +
            "if ($e.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$p)) { $p.SetValue($v) } " +
            "else { throw 'the element does not accept a value; click it and type instead' }";
    }

    /// <summary>Draw each element's frame and number onto the PNG at <paramref name="input"/> and save it to <paramref name="output"/>.</summary>
    public static string AnnotateScript(string input, string output, IReadOnlyList<UiElement> elements)
    {
        static string F(double d) => d.ToString("0.##", CultureInfo.InvariantCulture);
        // a flat list, five numbers per element: nested one-element arrays would be unrolled by PowerShell
        var boxes = string.Join(",", elements.Select(e => $"{e.Index},{F(e.X)},{F(e.Y)},{F(e.Width)},{F(e.Height)}"));
        return "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Drawing; " +
            $"$img = [System.Drawing.Image]::FromFile({Quote(input)}); $bmp = New-Object System.Drawing.Bitmap $img; $img.Dispose(); " +
            "$g = [System.Drawing.Graphics]::FromImage($bmp); $red = [System.Drawing.Color]::FromArgb(235, 255, 38, 77); " +
            "$pen = New-Object System.Drawing.Pen $red, 2; $brush = New-Object System.Drawing.SolidBrush $red; " +
            "$font = New-Object System.Drawing.Font 'Segoe UI', 9, ([System.Drawing.FontStyle]::Bold); " +
            $"$d = @({boxes}); " +
            "for ($k = 0; $k + 4 -lt $d.Count; $k += 5) { $x = [single]$d[$k + 1]; $y = [single]$d[$k + 2]; " +
            "$g.DrawRectangle($pen, $x, $y, [single]$d[$k + 3], [single]$d[$k + 4]); " +
            "$s = [string]$d[$k]; $size = $g.MeasureString($s, $font); $top = $y - $size.Height; if ($top -lt 0) { $top = $y }; " +
            "$g.FillRectangle($brush, $x, $top, $size.Width, $size.Height); $g.DrawString($s, $font, [System.Drawing.Brushes]::White, $x, $top) }; " +
            $"$g.Dispose(); $bmp.Save({Quote(output)}, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()";
    }
}
