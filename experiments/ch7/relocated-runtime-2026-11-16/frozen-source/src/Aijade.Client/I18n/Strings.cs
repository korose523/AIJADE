using System.Text.Json;

namespace Aijade.Client.I18n;

// UI strings, one embedded JSON dictionary per locale, with English as the fallback for any missing key.

public sealed class Strings
{
    public static IReadOnlyList<(string Code, string Name)> Locales { get; } =
    [
        ("en", "English"), ("zh-Hans", "简体中文"), ("zh-Hant", "繁體中文"), ("ja", "日本語"), ("ko", "한국어"),
        ("es", "Español"), ("fr", "Français"), ("ru", "Русский"), ("vi", "Tiếng Việt"),
    ];

    private static readonly Dictionary<string, IReadOnlyDictionary<string, string>> Cache = new(StringComparer.Ordinal);

    private static IReadOnlyDictionary<string, string> Load(string locale)
    {
        lock (Cache)
        {
            if (Cache.TryGetValue(locale, out var d))
                return d;
            using var stream = typeof(Strings).Assembly.GetManifestResourceStream($"Aijade.Client.I18n.{locale}.json");
            d = stream is null ? new Dictionary<string, string>() : JsonSerializer.Deserialize<Dictionary<string, string>>(stream)!;
            Cache[locale] = d;
            return d;
        }
    }

    public string Locale { get; private set; } = "en";

    public event Action? Changed;

    /// <summary>Pick a supported locale for a requested one (exact, then language family, then English).</summary>
    public static string Resolve(string? requested)
    {
        if (string.IsNullOrEmpty(requested))
            return "en";
        if (Locales.Any(l => l.Code == requested))
            return requested;
        var lower = requested.ToLowerInvariant();
        if (lower.StartsWith("zh", StringComparison.Ordinal))
            return lower.Contains("tw", StringComparison.Ordinal) || lower.Contains("hk", StringComparison.Ordinal) || lower.Contains("hant", StringComparison.Ordinal) ? "zh-Hant" : "zh-Hans";
        var lang = lower.Split('-')[0];
        return Locales.FirstOrDefault(l => l.Code == lang).Code ?? "en";
    }

    public void SetLocale(string locale)
    {
        Locale = Resolve(locale);
        Changed?.Invoke();
    }

    public string this[string key] => Load(Locale).TryGetValue(key, out var v) ? v : Load("en").TryGetValue(key, out var en) ? en : key;

    public string Format(string key, params object[] args) => string.Format(System.Globalization.CultureInfo.InvariantCulture, this[key], args);

    public static IReadOnlyCollection<string> Keys(string locale) => Load(locale).Keys.ToList();
}
