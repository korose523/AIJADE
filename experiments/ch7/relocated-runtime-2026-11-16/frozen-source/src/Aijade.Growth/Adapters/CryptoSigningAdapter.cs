using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Core.Js;

namespace Aijade.Growth.Adapters;

// HMAC-SHA256 over the canonical (key-sorted) JSON of the payload, replacing the FNV-1a stand-in for real runs.

public sealed class CryptoSigningAdapter : ISigningPort
{
    public const string DevSecret = "aijade-growth-dev-secret";
    private readonly byte[] key;

    /// <param name="secret">The shared secret; defaults to AIJADE_SIGNING_SECRET, then to a development secret.</param>
    public CryptoSigningAdapter(string? secret = null)
    {
        var resolved = secret ?? Environment.GetEnvironmentVariable("AIJADE_SIGNING_SECRET");
        UsingDevSecret = string.IsNullOrEmpty(resolved);
        key = Encoding.UTF8.GetBytes(UsingDevSecret ? DevSecret : resolved!);
    }

    /// <summary>True when the development fallback secret is in use; production deployments must set AIJADE_SIGNING_SECRET.</summary>
    public bool UsingDevSecret { get; }

    public string Sign(JsonNode payload) =>
        Convert.ToHexStringLower(HMACSHA256.HashData(key, Encoding.UTF8.GetBytes(JsFormat.CanonicalJson(payload))));

    public bool Verify(JsonNode payload, string signature)
    {
        byte[] given;
        try
        {
            given = Convert.FromHexString(signature);
        }
        catch (FormatException)
        {
            return false;
        }
        var expected = Convert.FromHexString(Sign(payload));
        return CryptographicOperations.FixedTimeEquals(expected, given);
    }
}
