using System.Text.Json.Nodes;

namespace Aijade.ComputerUse;

// Which follows Hermes Agent's
// computer_use schema: a single tool with an action discriminator (cheap per turn, works with any tool-calling model).
// Safety model: read-only actions (capture, wait, list_apps) always run; every desktop-changing
// action is refused unless allowed — fail-closed. Allowing is configuration of whoever starts this server
// (AIJADE_COMPUTER_USE_ALLOW = "all" or a comma list such as "click,type,key"), never something the model can ask for.

public static class Actions
{
    public static readonly string[] All =
        ["capture", "click", "double_click", "right_click", "middle_click", "drag", "scroll", "type", "key", "set_value", "wait", "list_apps", "focus_app"];

    public static readonly HashSet<string> Safe = new(["capture", "wait", "list_apps"], StringComparer.Ordinal);

    public static readonly string[] Modifiers = ["cmd", "shift", "option", "alt", "ctrl", "fn", "win", "windows", "super", "meta"];
}

public sealed record ComputerResult(bool Ok, bool Safe, string Summary, byte[]? Png = null);

/// <summary>An actionable element from an accessibility capture; the frame is in screen points (origin top-left).</summary>
public sealed record UiElement(int Index, string Role, string Name, double X, double Y, double Width, double Height)
{
    public (int X, int Y) Center => ((int)Math.Round(X + (Width / 2)), (int)Math.Round(Y + (Height / 2)));

    public override string ToString() =>
        $"[{Index}] {Role}{(Name.Length > 0 ? $" \"{Name}\"" : "")} at ({(int)X}, {(int)Y}) {(int)Width}×{(int)Height}";
}

/// <summary>Who may do what: read-only always; others only when listed (or "all").</summary>
public sealed class ComputerUsePolicy(IReadOnlySet<string> allowed)
{
    public static ComputerUsePolicy FromEnvironment(string? value) =>
        new(value?.Trim() is { Length: > 0 } v
            ? v == "all" ? new HashSet<string>(Actions.All, StringComparer.Ordinal) : new HashSet<string>(v.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries), StringComparer.Ordinal)
            : new HashSet<string>(StringComparer.Ordinal));

    public bool Allows(string action) => Actions.Safe.Contains(action) || allowed.Contains(action);
}

/// <summary>The platform side: what the desktop can actually do. Coordinates are in screen points.</summary>
public interface IDesktop
{
    Task<(byte[] Png, int Width, int Height)> CaptureAsync(CancellationToken ct);

    void Click(int x, int y, string button, int count, IReadOnlyList<string> modifiers);

    void Drag(int fromX, int fromY, int toX, int toY);

    void Scroll(int x, int y, string direction, int amount);

    void Type(string text);

    void Key(string combo);

    Task<IReadOnlyList<string>> ListAppsAsync(CancellationToken ct);

    Task FocusAppAsync(string app, CancellationToken ct);

    /// <summary>
    /// The actionable elements of the frontmost window (or of <paramref name="app"/>), numbered from 1 in the order returned.
    /// The desktop keeps them until the next call, so <see cref="SetValue"/> can address them by number.
    /// </summary>
    Task<IReadOnlyList<UiElement>> ElementsAsync(string? app, CancellationToken ct) =>
        throw new PlatformNotSupportedException("accessibility captures (mode=ax / som) are not available on this platform; use mode=vision and coordinates");

    /// <summary>Draw each element's frame and number onto a screenshot taken at the same scale (points).</summary>
    byte[] Annotate(byte[] png, IReadOnlyList<UiElement> elements) => png;

    /// <summary>Set the value of element <paramref name="index"/> from the last <see cref="ElementsAsync"/> (e.g. a text field).</summary>
    void SetValue(int index, string value) =>
        throw new PlatformNotSupportedException("set_value needs an accessibility capture, which is not available on this platform");
}

public sealed class ComputerUseTool(IDesktop desktop, ComputerUsePolicy policy)
{
    public static JsonObject Schema() => new()
    {
        ["type"] = "object",
        ["properties"] = new JsonObject
        {
            ["action"] = new JsonObject { ["type"] = "string", ["enum"] = new JsonArray([.. Actions.All.Select(a => (JsonNode)a)]), ["description"] = "Which action to perform." },
            ["mode"] = new JsonObject { ["type"] = "string", ["enum"] = new JsonArray("som", "vision", "ax"), ["description"] = "Capture mode: som (screenshot with numbered element overlays), vision (screenshot), ax (numbered accessibility elements as text)." },
            ["app"] = new JsonObject { ["type"] = "string", ["description"] = "focus_app: the application name; capture with som / ax: whose window to read (default: the frontmost)." },
            ["element"] = new JsonObject { ["type"] = "integer", ["description"] = "1-based element number from the last capture(mode='som' or 'ax'), instead of coordinate." },
            ["from_element"] = new JsonObject { ["type"] = "integer", ["description"] = "drag: start element number." },
            ["to_element"] = new JsonObject { ["type"] = "integer", ["description"] = "drag: end element number." },
            ["coordinate"] = new JsonObject { ["type"] = "array", ["items"] = new JsonObject { ["type"] = "integer" }, ["minItems"] = 2, ["maxItems"] = 2, ["description"] = "[x, y] in screen points, as in the last capture." },
            ["button"] = new JsonObject { ["type"] = "string", ["enum"] = new JsonArray("left", "right", "middle") },
            ["modifiers"] = new JsonObject { ["type"] = "array", ["items"] = new JsonObject { ["type"] = "string", ["enum"] = new JsonArray([.. Actions.Modifiers.Select(m => (JsonNode)m)]) } },
            ["from_coordinate"] = new JsonObject { ["type"] = "array", ["items"] = new JsonObject { ["type"] = "integer" }, ["minItems"] = 2, ["maxItems"] = 2 },
            ["to_coordinate"] = new JsonObject { ["type"] = "array", ["items"] = new JsonObject { ["type"] = "integer" }, ["minItems"] = 2, ["maxItems"] = 2 },
            ["direction"] = new JsonObject { ["type"] = "string", ["enum"] = new JsonArray("up", "down", "left", "right") },
            ["amount"] = new JsonObject { ["type"] = "integer", ["description"] = "Scroll ticks (default 3)." },
            ["text"] = new JsonObject { ["type"] = "string", ["description"] = "type: the text to type; set_value: the element's new value." },
            ["keys"] = new JsonObject { ["type"] = "string", ["description"] = "key: a combo such as 'cmd+s' or 'escape'." },
            ["seconds"] = new JsonObject { ["type"] = "number", ["description"] = "wait: seconds, at most 30." },
        },
        ["required"] = new JsonArray("action"),
    };

    public const string Description =
        "Look at and operate the user's computer: action=capture returns a screenshot (coordinates are screen points); prefer " +
        "capture(mode='som') — numbered element overlays — then click(element=N) or set_value(element=N, text); click / double_click / " +
        "right_click / middle_click at a coordinate or element; drag; scroll; type text; key combos such as cmd+s; wait; list_apps; focus_app. " +
        "Actions that change the desktop run only if the user's configuration allows them.";

    /// <summary>A JSON number however it was built (parsed text, int, double).</summary>
    private static double? Number(JsonNode? n) =>
        n is JsonValue v && v.GetValueKind() == System.Text.Json.JsonValueKind.Number
            && double.TryParse(v.ToJsonString(), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var d) && double.IsFinite(d)
            ? d : null;

    private static (int X, int Y) Point(JsonObject a, string key) =>
        a[key] is JsonArray { Count: 2 } p && Number(p[0]) is { } x && Number(p[1]) is { } y ? ((int)x, (int)y)
            : throw new ArgumentException($"{key} must be [x, y]");

    /// <summary>Elements of the last som / ax capture, addressed by number until the next capture.</summary>
    private IReadOnlyList<UiElement> elements = [];

    private UiElement Element(JsonObject a, string key)
    {
        if (Number(a[key]) is not { } n || n != Math.Floor(n))
            throw new ArgumentException($"{key} must be an element number");
        if (elements.Count == 0)
            throw new ArgumentException($"{key} refers to an accessibility capture; run capture(mode='som' or 'ax') first");
        return n >= 1 && n <= elements.Count ? elements[(int)n - 1]
            : throw new ArgumentException($"{key} {n} is not in the last capture (1–{elements.Count})");
    }

    /// <summary>A point given either as a coordinate or as an element number (its centre).</summary>
    private (int X, int Y) Target(JsonObject a, string coordinateKey, string elementKey) =>
        a[elementKey] is not null ? Element(a, elementKey).Center : Point(a, coordinateKey);

    public async Task<ComputerResult> RunAsync(JsonObject a, CancellationToken ct)
    {
        var action = a["action"]?.GetValue<string>() ?? "";
        if (!Actions.All.Contains(action))
            return new(false, false, $"invalid computer_use params: action must be one of {string.Join(", ", Actions.All)}");
        var safe = Actions.Safe.Contains(action);
        if (!policy.Allows(action))
            return new(false, false, $"blocked: non-safe computer_use action \"{action}\" requires approval (not allowed by AIJADE_COMPUTER_USE_ALLOW)");
        try
        {
            var modifiers = (a["modifiers"] as JsonArray ?? []).Select(m => m!.GetValue<string>()).ToList();
            switch (action)
            {
                case "capture":
                    var mode = a["mode"]?.GetValue<string>() ?? "vision";
                    if (mode is not ("vision" or "som" or "ax"))
                        return new(false, true, $"capture mode '{mode}' is not supported; use som, vision or ax");
                    if (mode == "vision")
                    {
                        var (png, w, h) = await desktop.CaptureAsync(ct).ConfigureAwait(false);
                        return new(true, true, $"screenshot {w}x{h} points", png);
                    }
                    elements = []; // a failed capture must not leave stale numbers behind
                    elements = await desktop.ElementsAsync(a["app"]?.GetValue<string>(), ct).ConfigureAwait(false);
                    var listing = elements.Count == 0 ? "no actionable elements found" : string.Join("\n", elements);
                    if (mode == "ax")
                        return new(true, true, $"{elements.Count} elements\n{listing}");
                    var (shot, sw, sh) = await desktop.CaptureAsync(ct).ConfigureAwait(false);
                    return new(true, true, $"screenshot {sw}x{sh} points with {elements.Count} numbered elements\n{listing}", desktop.Annotate(shot, elements));
                case "click" or "double_click" or "right_click" or "middle_click":
                    var (x, y) = Target(a, "coordinate", "element");
                    var button = action switch { "right_click" => "right", "middle_click" => "middle", _ => a["button"]?.GetValue<string>() ?? "left" };
                    desktop.Click(x, y, button, action == "double_click" ? 2 : 1, modifiers);
                    return new(true, false, $"{action} at ({x}, {y})");
                case "drag":
                    var (fx, fy) = Target(a, "from_coordinate", "from_element");
                    var (tx, ty) = Target(a, "to_coordinate", "to_element");
                    desktop.Drag(fx, fy, tx, ty);
                    return new(true, false, $"dragged ({fx}, {fy}) → ({tx}, {ty})");
                case "scroll":
                    var (sx, sy) = a["coordinate"] is null && a["element"] is null ? (-1, -1) : Target(a, "coordinate", "element");
                    var direction = a["direction"]?.GetValue<string>() ?? "down";
                    var amount = Math.Clamp((int)(Number(a["amount"]) ?? 3), 1, 50);
                    desktop.Scroll(sx, sy, direction, amount);
                    return new(true, false, $"scrolled {direction} {amount}");
                case "type":
                    var text = a["text"]?.GetValue<string>() ?? throw new ArgumentException("text is required");
                    desktop.Type(text);
                    return new(true, false, $"typed {text.Length} characters");
                case "key":
                    var keys = a["keys"]?.GetValue<string>() ?? throw new ArgumentException("keys is required");
                    desktop.Key(keys);
                    return new(true, false, $"pressed {keys}");
                case "set_value":
                    var target = Element(a, "element");
                    var value = a["text"]?.GetValue<string>() ?? throw new ArgumentException("text is required");
                    desktop.SetValue(target.Index, value);
                    return new(true, false, $"set the value of [{target.Index}] {target.Role} ({value.Length} characters)");
                case "wait":
                    var seconds = Math.Clamp(Number(a["seconds"]) ?? 1, 0, 30);
                    await Task.Delay(TimeSpan.FromSeconds(seconds), ct).ConfigureAwait(false);
                    return new(true, true, $"waited {seconds} s");
                case "list_apps":
                    return new(true, true, string.Join("\n", await desktop.ListAppsAsync(ct).ConfigureAwait(false)));
                case "focus_app":
                    var app = a["app"]?.GetValue<string>() ?? throw new ArgumentException("app is required");
                    await desktop.FocusAppAsync(app, ct).ConfigureAwait(false);
                    return new(true, false, $"focused {app}");
                default:
                    return new(false, safe, $"{action} is not supported by this server");
            }
        }
        catch (Exception e) when (e is ArgumentException or InvalidOperationException or PlatformNotSupportedException or System.ComponentModel.Win32Exception)
        {
            return new(false, safe, e.Message);
        }
    }
}

/// <summary>Key combos ("cmd+shift+s", "escape", "f5") split into modifiers and the main key.</summary>
public static class KeyCombo
{
    public static (IReadOnlyList<string> Modifiers, string Key) Parse(string combo)
    {
        var parts = combo.ToLowerInvariant().Split('+', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length == 0)
            throw new ArgumentException("empty key combo");
        var mods = parts[..^1].Select(m => m switch { "command" => "cmd", "control" => "ctrl", "opt" => "option", _ => m }).ToList();
        foreach (var m in mods)
        {
            if (!Actions.Modifiers.Contains(m))
                throw new ArgumentException($"unknown modifier '{m}'");
        }
        return (mods, parts[^1] switch { "esc" => "escape", "return" => "enter", "del" => "delete", _ => parts[^1] });
    }
}
