using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Chat;
using Aijade.Client.Companion;
using Aijade.Memory.Development;

namespace Aijade.Tests;

/// <summary>
/// The companion contract shared with MOSAIC's companion (configs/companion/contract.json, docs/COMPANION-CONTRACT.md,
/// ADR-002): the product code must hold the contract's persona, expression names and initiative rule, and the initiative rule
/// must give the decisions MOSAIC's implementation gave on the vectors it generated. Non-research line only.
/// </summary>
public class CompanionContractTests
{
    private static readonly string Root = RqcReanalysisTests.RepoRoot();

    private static JsonElement Load(string name)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "configs", "companion", name)));
        return doc.RootElement.Clone();
    }

    [Fact]
    public void The_default_persona_is_the_contract_persona()
    {
        var persona = Load("contract.json").GetProperty("persona");
        Assert.Equal(ChatOrchestrator.DefaultPersona, persona.GetProperty("prompt").GetString());
        Assert.StartsWith("You are " + persona.GetProperty("names")[0].GetString(), ChatOrchestrator.DefaultPersona, StringComparison.Ordinal);
    }

    [Fact]
    public void The_expression_names_and_their_mapping_cover_the_stage_vocabulary()
    {
        var expressions = Load("contract.json").GetProperty("expressions");
        var table = expressions.GetProperty("aijade").GetProperty("table").EnumerateObject().ToList();
        Assert.Equal(Expressions.Table.Keys.Order(StringComparer.Ordinal), table.Select(p => p.Name).Order(StringComparer.Ordinal));
        foreach (var e in table)
        {
            var axes = e.Value.EnumerateObject().ToDictionary(a => a.Name, a => a.Value.GetDouble(), StringComparer.Ordinal);
            Assert.All(axes.Keys, a => Assert.NotNull(typeof(PartialExpression).GetProperty(char.ToUpperInvariant(a[0]) + a[1..])));
            foreach (var property in typeof(PartialExpression).GetProperties().Where(x => x.PropertyType == typeof(double?)))
            {
                var key = char.ToLowerInvariant(property.Name[0]) + property.Name[1..];
                Assert.Equal(axes.TryGetValue(key, out var v) ? v : null, (double?)property.GetValue(Expressions.Table[e.Name]));
            }
        }
        var mosaic = expressions.GetProperty("mosaic").GetProperty("emotions").EnumerateArray().Select(x => x.GetString()).ToHashSet();
        var toMosaic = expressions.GetProperty("aijadeToMosaic").EnumerateObject().ToList();
        Assert.Equal(Expressions.Table.Keys.Order(StringComparer.Ordinal), toMosaic.Select(p => p.Name).Order(StringComparer.Ordinal));
        Assert.All(toMosaic, p => Assert.Contains(p.Value.GetString(), mosaic));
        Assert.All(expressions.GetProperty("mosaicToAijade").EnumerateObject(), p =>
        {
            Assert.Contains(p.Name, mosaic);
            if (p.Value.ValueKind != JsonValueKind.Null)
                Assert.Contains(p.Value.GetString()!, Expressions.Table.Keys);
        });
    }

    [Fact]
    public void The_initiative_parameters_and_words_are_the_contract_values()
    {
        var c = Load("contract.json").GetProperty("initiative").GetProperty("params");
        var w = c.GetProperty("weights");
        var expected = new InitiativeParams(c.GetProperty("quiet_min_s").GetDouble(), c.GetProperty("quiet_full_s").GetDouble(),
            c.GetProperty("cooldown_s").GetDouble(), c.GetProperty("per_hour").GetInt32(), c.GetProperty("hush_s").GetDouble(),
            c.GetProperty("recent_s").GetDouble(), c.GetProperty("night")[0].GetInt32(), c.GetProperty("night")[1].GetInt32(),
            c.GetProperty("threshold").GetDouble(), new InitiativeWeights(w.GetProperty("relevance").GetDouble(),
                w.GetProperty("novelty").GetDouble(), w.GetProperty("social").GetDouble(), w.GetProperty("context").GetDouble(),
                w.GetProperty("interrupt").GetDouble(), w.GetProperty("frequency").GetDouble()));
        Assert.Equal(expected, InitiativeParams.Default);

        var vectors = Load("initiative-vectors.json");
        Assert.True(JsonNode.DeepEquals(JsonNode.Parse(c.GetRawText()), JsonNode.Parse(vectors.GetProperty("params").GetRawText())),
            "the contract's initiative parameters differ from those the vectors were generated with");
        Assert.Equal(vectors.GetProperty("leaving").EnumerateArray().Select(x => x.GetString()), Initiative.Leaving);
        Assert.Equal(vectors.GetProperty("hush").EnumerateArray().Select(x => x.GetString()), Initiative.Hush);
    }

    [Fact]
    public void The_initiative_rule_decides_as_mosaic_did_on_every_vector()
    {
        var vectors = Load("initiative-vectors.json").GetProperty("vectors").EnumerateArray().ToList();
        Assert.NotEmpty(vectors);
        foreach (var v in vectors)
        {
            var name = v.GetProperty("name").GetString();
            var turns = v.GetProperty("turns").EnumerateArray().Select(t => new InitiativeTurn(t.GetProperty("created").GetDouble(),
                t.GetProperty("input").GetString(), t.GetProperty("kind").GetString() == "proactive")).ToList();
            var got = Initiative.Decide(turns, v.GetProperty("now").GetDouble(), v.GetProperty("hour").GetInt32());
            var e = v.GetProperty("expected");
            Assert.True(e.GetProperty("speak").GetBoolean() == got.Speak, $"{name}: speak");
            Assert.True(e.GetProperty("reason").GetString() == got.Reason, $"{name}: reason {got.Reason}");
            Assert.True(e.GetProperty("followUp").ValueKind == JsonValueKind.Null ? got.FollowUp is null
                : e.GetProperty("followUp").GetString() == got.FollowUp, $"{name}: follow-up");
            if (e.GetProperty("score").ValueKind == JsonValueKind.Null)
                Assert.Null(got.Score);
            else
                Assert.True(Math.Abs(e.GetProperty("score").GetDouble() - got.Score!.Value) <= 5e-4, $"{name}: score {got.Score}");
            foreach (var part in e.GetProperty("parts").EnumerateObject())
                Assert.True(Math.Abs(part.Value.GetDouble() - got.Parts[part.Name]) <= 5e-4, $"{name}: {part.Name}");
        }
    }
}
