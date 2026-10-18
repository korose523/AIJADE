using System.Text.RegularExpressions;

namespace Aijade.Core.Js;

/// <summary>
/// JavaScript (non-Unicode-mode) regular-expression semantics, spelled out for .NET.
/// The memory kernel's tokenisation is defined by these semantics (the recorded golden outputs depend on them), and .NET's
/// defaults differ: JS <c>\b</c>, <c>\w</c> and <c>\d</c> are ASCII-only,
/// JS <c>\s</c> is a fixed set of Unicode spaces (with U+FEFF, without U+0085), and <c>/i</c> folds ASCII only.
/// </summary>
public static class JsText
{
    /// <summary>Members of JS <c>\s</c>, for use inside a character class.</summary>
    public const string SpaceChars = "\\t\\n\\v\\f\\r \\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff";

    /// <summary>JS <c>\s</c> as a standalone class.</summary>
    public const string Space = "[" + SpaceChars + "]";

    /// <summary>JS <c>\w</c> members (ASCII).</summary>
    public const string WordChars = "A-Za-z0-9_";

    /// <summary>JS <c>\b</c>: a boundary between an ASCII word character and anything else.</summary>
    public const string Boundary = "(?:(?<=[" + WordChars + "])(?![" + WordChars + "])|(?<![" + WordChars + "])(?=[" + WordChars + "]))";

    /// <summary>Options matching a JS literal; <paramref name="ignoreCase"/> mirrors the <c>i</c> flag.</summary>
    public static RegexOptions Options(bool ignoreCase) =>
        RegexOptions.CultureInvariant | (ignoreCase ? RegexOptions.IgnoreCase : RegexOptions.None);

    private static readonly Regex Spaces = new(Space + "+", Options(false));

    /// <summary><c>text.split(/\s+/)</c>, including the leading empty element JS produces for leading whitespace.</summary>
    public static string[] SplitOnSpace(string text) => Spaces.Split(text);

    /// <summary><c>text.toLowerCase()</c>. Invariant lower-casing; identical to JS for every character the corpora contain.</summary>
    public static string Lower(string text) => text.ToLowerInvariant();

    /// <summary><c>text.trim()</c> with the JS whitespace set (JS also trims line terminators, which are in the set).</summary>
    public static string Trim(string text)
    {
        int start = 0, end = text.Length;
        while (start < end && IsSpace(text[start]))
            start++;
        while (end > start && IsSpace(text[end - 1]))
            end--;
        return text[start..end];
    }

    /// <summary>Membership in JS <c>\s</c>: U+0009–U+000D, U+0020, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000, U+FEFF.</summary>
    public static bool IsSpace(char c) => (int)c is (>= 0x09 and <= 0x0D) or 0x20 or 0xA0 or 0x1680
        or (>= 0x2000 and <= 0x200A) or 0x2028 or 0x2029 or 0x202F or 0x205F or 0x3000 or 0xFEFF;
}
