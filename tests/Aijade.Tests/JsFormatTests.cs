using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;

namespace Aijade.Tests;

/// <summary>Content hashes must be byte-identical to the recorded golden data.</summary>
public class JsFormatTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "js-format-golden.json"))).RootElement;

    [Fact]
    public void Numbers_print_as_javascript_does()
    {
        foreach (var pair in Golden.GetProperty("numbers").EnumerateArray())
            Assert.Equal(pair[1].GetString(), JsFormat.Number(pair[0].GetDouble()));
        Assert.Equal("0", JsFormat.Number(-0.0));
    }

    [Fact]
    public void Strings_are_escaped_as_json_stringify_does()
    {
        foreach (var pair in Golden.GetProperty("strings").EnumerateArray())
        {
            // System.Text.Json cannot materialise a lone surrogate; that case is asserted separately below.
            if (pair[0].GetRawText().Contains("\\ud800", StringComparison.OrdinalIgnoreCase))
                continue;
            Assert.Equal(pair[1].GetString(), JsFormat.JsonString(pair[0].GetString()!));
        }
        var lone = new string((char)0xD800, 1) + "lone";
        Assert.Equal("\"\\ud800lone\"", JsFormat.JsonString(lone));
    }

    [Fact]
    public void Canonical_json_and_content_hash_match()
    {
        foreach (var triple in Golden.GetProperty("canonical").EnumerateArray())
        {
            var node = JsonNode.Parse(triple[0].GetRawText());
            Assert.Equal(triple[1].GetString(), JsFormat.CanonicalJson(node));
            Assert.Equal(triple[2].GetString(), JsFormat.ContentHash(node));
        }
        Assert.Equal(Golden.GetProperty("sha").GetString(), JsFormat.Sha256Hex("aijade"));
    }

    [Fact]
    public void Fnv1a_matches()
    {
        foreach (var pair in Golden.GetProperty("fnv").EnumerateArray())
            Assert.Equal(pair[1].GetString(), JsFormat.Fnv1a(pair[0].GetString()!));
    }
}
