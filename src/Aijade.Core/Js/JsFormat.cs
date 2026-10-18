using System.Globalization;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Aijade.Core.Js;

/// <summary>
/// Byte-exact equivalents of the JavaScript primitives that content hashes and fingerprints depend on:
/// <c>Number.prototype.toString</c>, <c>JSON.stringify</c> for strings, canonical JSON (keys sorted), SHA-256 and FNV-1a.
/// Stored hashes and fingerprints are defined over these forms, so they must not change.
/// </summary>
public static class JsFormat
{
    /// <summary>ECMAScript Number::toString(10): shortest round-trip digits, JS exponent rules, "-0" printed as "0".</summary>
    public static string Number(double x)
    {
        if (double.IsNaN(x))
            return "NaN";
        if (double.IsPositiveInfinity(x))
            return "Infinity";
        if (double.IsNegativeInfinity(x))
            return "-Infinity";
        if (x == 0)
            return "0";
        if (x < 0)
            return "-" + Number(-x);

        // Shortest round-trip digits from .NET ("R"), re-laid-out with JavaScript's rules.
        var shortest = x.ToString("R", CultureInfo.InvariantCulture);
        string digits;
        int exponent; // value = 0.d1d2…dk × 10^exponent, i.e. JS's "n"
        var e = shortest.IndexOfAny(['E', 'e']);
        var mantissa = e >= 0 ? shortest[..e] : shortest;
        var exp10 = e >= 0 ? int.Parse(shortest[(e + 1)..], CultureInfo.InvariantCulture) : 0;
        var dot = mantissa.IndexOf('.', StringComparison.Ordinal);
        var intPart = dot >= 0 ? mantissa[..dot] : mantissa;
        var fracPart = dot >= 0 ? mantissa[(dot + 1)..] : "";
        digits = (intPart + fracPart).TrimStart('0');
        var leadingZeros = (intPart + fracPart).Length - digits.Length;
        exponent = intPart.Length - leadingZeros + exp10;
        digits = digits.TrimEnd('0');
        if (digits.Length == 0)
            return "0";

        var k = digits.Length;
        var n = exponent;
        if (k <= n && n <= 21)
            return digits + new string('0', n - k);
        if (0 < n && n <= 21)
            return digits[..n] + "." + digits[n..];
        if (-6 < n && n <= 0)
            return "0." + new string('0', -n) + digits;
        var sign = n - 1 >= 0 ? "+" : "-";
        var tail = k > 1 ? "." + digits[1..] : "";
        return digits[0] + tail + "e" + sign + Math.Abs(n - 1).ToString(CultureInfo.InvariantCulture);
    }

    /// <summary>
    /// <c>Number.prototype.toFixed(digits)</c> for |x| &lt; 1e21: rounds the exact binary value, a tie going to the larger
    /// magnitude, and keeps the sign of a negative value that rounds to zero ("-0.0"), as JavaScript does.
    /// </summary>
    public static string ToFixed(double x, int digits)
    {
        if (double.IsNaN(x))
            return "NaN";
        if (double.IsInfinity(x) || Math.Abs(x) >= 1e21)
            return Number(x);
        // |x| = mantissa · 2^exponent exactly; n = round(|x| · 10^digits), a tie going up, computed in exact integers.
        var bits = BitConverter.DoubleToInt64Bits(Math.Abs(x));
        var rawExponent = (int)((bits >> 52) & 0x7FF);
        var mantissa = new BigInteger(bits & 0xFFFFFFFFFFFFFL);
        if (rawExponent != 0)
            mantissa += BigInteger.One << 52;
        var exponent = (rawExponent == 0 ? 1 : rawExponent) - 1075;
        var scaled = mantissa * BigInteger.Pow(10, digits);
        BigInteger n;
        if (exponent >= 0)
        {
            n = scaled << exponent;
        }
        else
        {
            var divisor = BigInteger.One << -exponent;
            n = BigInteger.DivRem(scaled, divisor, out var remainder);
            if (remainder * 2 >= divisor)
                n += 1;
        }
        var text = n.ToString(CultureInfo.InvariantCulture);
        if (digits > 0)
        {
            text = text.PadLeft(digits + 1, '0');
            text = text[..^digits] + "." + text[^digits..];
        }
        return x < 0 ? "-" + text : text;
    }

    /// <summary>JSON.stringify(number): non-finite values become "null".</summary>
    public static string JsonNumber(double x) => double.IsFinite(x) ? Number(x) : "null";

    /// <summary>JSON.stringify(string) (ES2019 well-formed: lone surrogates escaped).</summary>
    public static string JsonString(string s)
    {
        var sb = new StringBuilder(s.Length + 2);
        sb.Append('"');
        for (var i = 0; i < s.Length; i++)
        {
            var c = s[i];
            switch (c)
            {
                case '"': sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                case '\b': sb.Append("\\b"); break;
                case '\f': sb.Append("\\f"); break;
                case '\n': sb.Append("\\n"); break;
                case '\r': sb.Append("\\r"); break;
                case '\t': sb.Append("\\t"); break;
                default:
                    if (c < 0x20)
                    {
                        sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                    }
                    else if (char.IsHighSurrogate(c) && i + 1 < s.Length && char.IsLowSurrogate(s[i + 1]))
                    {
                        sb.Append(c).Append(s[++i]);
                    }
                    else if (char.IsSurrogate(c))
                    {
                        sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                    }
                    else
                    {
                        sb.Append(c);
                    }
                    break;
            }
        }
        return sb.Append('"').ToString();
    }

    /// <summary>
    /// Canonical JSON: object keys sorted by UTF-16 code unit (as JS's default sort), arrays kept in order,
    /// primitives as JSON.stringify writes them.
    /// </summary>
    public static string CanonicalJson(JsonNode? node)
    {
        switch (node)
        {
            case null:
                return "null";
            case JsonObject obj:
                {
                    var keys = obj.Select(kv => kv.Key).ToList();
                    keys.Sort(string.CompareOrdinal);
                    return "{" + string.Join(",", keys.Select(k => JsonString(k) + ":" + CanonicalJson(obj[k]))) + "}";
                }
            case JsonArray arr:
                return "[" + string.Join(",", arr.Select(CanonicalJson)) + "]";
            case JsonValue value:
                return value.GetValueKind() switch
                {
                    JsonValueKind.String => JsonString(value.GetValue<string>()),
                    JsonValueKind.Number => JsonNumber(double.Parse(value.ToJsonString(), CultureInfo.InvariantCulture)),
                    JsonValueKind.True => "true",
                    JsonValueKind.False => "false",
                    _ => "null",
                };
            default:
                return "null";
        }
    }

    /// <summary>
    /// <c>JSON.stringify(value, null, indent)</c>: keys in insertion order, JS number and string formatting, and the same
    /// layout (empty containers stay <c>{}</c> / <c>[]</c>; <c>indent = 0</c> is the compact form).
    /// </summary>
    public static string Stringify(JsonNode? node, int indent = 0)
    {
        var sb = new StringBuilder();
        Write(node, sb, indent, 0);
        return sb.ToString();
    }

    private static void Write(JsonNode? node, StringBuilder sb, int indent, int depth)
    {
        void Break(int level)
        {
            if (indent > 0)
                sb.Append('\n').Append(' ', indent * level);
        }

        switch (node)
        {
            case JsonObject obj:
                if (obj.Count == 0)
                {
                    sb.Append("{}");
                    return;
                }
                sb.Append('{');
                var first = true;
                foreach (var (key, value) in obj)
                {
                    if (!first)
                        sb.Append(',');
                    first = false;
                    Break(depth + 1);
                    sb.Append(JsonString(key)).Append(indent > 0 ? ": " : ":");
                    Write(value, sb, indent, depth + 1);
                }
                Break(depth);
                sb.Append('}');
                return;
            case JsonArray arr:
                if (arr.Count == 0)
                {
                    sb.Append("[]");
                    return;
                }
                sb.Append('[');
                for (var i = 0; i < arr.Count; i++)
                {
                    if (i > 0)
                        sb.Append(',');
                    Break(depth + 1);
                    Write(arr[i], sb, indent, depth + 1);
                }
                Break(depth);
                sb.Append(']');
                return;
            default:
                sb.Append(node is JsonValue ? CanonicalJson(node) : "null");
                return;
        }
    }

    public static string Sha256Hex(string input) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(input)));

    /// <summary>sha256(canonicalJson(payload)).</summary>
    public static string ContentHash(JsonNode? payload) => Sha256Hex(CanonicalJson(payload));

    /// <summary>
    /// The FNV-1a variant written as <c>h = (h * 0x01000193) &gt;&gt;&gt; 0</c> in JavaScript: the product is a double (above 2^53 it
    /// loses low bits) before ToUint32, so the result differs from true FNV-1a. Identity signatures depend on it.
    /// </summary>
    public static string Fnv1aJsDouble(string input)
    {
        var h = 0x811C9DC5u;
        foreach (var c in input)
        {
            h ^= c;
            h = ToUint32((double)h * 16777619.0);
        }
        return h.ToString("x8", CultureInfo.InvariantCulture);
    }

    /// <summary>ECMAScript ToUint32 (<c>x &gt;&gt;&gt; 0</c>): truncate toward zero, then modulo 2^32; NaN and ±∞ give 0.</summary>
    public static uint ToUint32(double x)
    {
        if (!double.IsFinite(x))
            return 0;
        var r = Math.IEEERemainder(Math.Truncate(x), 4294967296.0);
        if (r < 0)
            r += 4294967296.0;
        return (uint)r;
    }

    /// <summary>FNV-1a 32-bit over UTF-16 code units, as 8 lower-case hex digits.</summary>
    public static string Fnv1a(string input)
    {
        unchecked
        {
            var h = 0x811C9DC5u;
            foreach (var c in input)
            {
                h ^= c;
                h *= 0x01000193u;
            }
            return h.ToString("x8", CultureInfo.InvariantCulture);
        }
    }
}
