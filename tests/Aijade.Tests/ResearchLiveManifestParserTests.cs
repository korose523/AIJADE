using System.Text.Json;
using System.Text.Json.Nodes;

namespace Aijade.Tests;

public class ResearchLiveManifestParserTests
{
    private static string KnownText()
    {
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null && !File.Exists(Path.Combine(root.FullName, "AIJADE.sln")) &&
               !Directory.Exists(Path.Combine(root.FullName, ".git")) && !File.Exists(Path.Combine(root.FullName, ".git")))
            root = root.Parent;
        return File.ReadAllText(Path.Combine(root?.FullName ?? throw new InvalidOperationException("Repository not found"),
            "experiments/ch7/live-manifest-known-input-v1.json"));
    }

    [Fact]
    public void Closed_known_manifest_contains_operational_inputs_and_balanced_pairs()
    {
        var manifest = ResearchLiveManifest.Read(KnownText());
        Assert.Equal(10, manifest.Cases.Count);
        Assert.Equal(5, manifest.Cases.Count(c => c.Conditions[0] == "C1"));
        Assert.Equal(5, manifest.Cases.Count(c => c.Conditions[0] == "C2"));
        Assert.All(manifest.Cases, c => Assert.StartsWith("u_", c.CaseId));
        Assert.True(JsonNode.DeepEquals(JsonNode.Parse(KnownText()), JsonSerializer.SerializeToNode(manifest, ResearchLiveManifest.Options)));
    }

    [Fact]
    public void Consistent_case_renaming_changes_no_input_operation_or_programme()
    {
        var source = JsonNode.Parse(KnownText())!.AsObject();
        var cases = source["cases"]!.AsArray();
        var aliases = cases.Select((c, i) => (Old: c!["caseId"]!.GetValue<string>(), New: "arbitrary_" + i)).ToDictionary(p => p.Old, p => p.New);
        foreach (var item in cases)
        {
            item!["caseId"] = aliases[item["caseId"]!.GetValue<string>()];
            item["operations"]!["receiptCaseId"] = aliases[item["operations"]!["receiptCaseId"]!.GetValue<string>()];
        }
        var renamed = ResearchLiveManifest.Read(source.ToJsonString());
        var original = ResearchLiveManifest.Read(KnownText());
        for (var i = 0; i < original.Cases.Count; i++)
        {
            var a = original.Cases[i]; var b = renamed.Cases[i];
            Assert.Equal(a.CodeSha256, b.CodeSha256); Assert.Equal(a.TaskId, b.TaskId); Assert.Equal(a.Conditions, b.Conditions);
            Assert.Equal(a.Operations with { ReceiptCaseId = aliases[a.Operations.ReceiptCaseId] }, b.Operations);
        }
    }

    [Fact]
    public void A_bounded_block_does_not_require_the_ten_development_names_or_count()
    {
        var root = JsonNode.Parse(KnownText())!.AsObject();
        var one = root["cases"]![0]!.DeepClone();
        one["caseId"] = "one_case"; one["operations"]!["receiptCaseId"] = "one_case";
        root["cases"] = new JsonArray(one);
        Assert.Single(ResearchLiveManifest.Read(root.ToJsonString()).Cases);
    }

    [Fact]
    public void Expected_labels_unknown_fields_and_duplicate_json_properties_are_refused()
    {
        foreach (var field in new[] { "expected", "expectedPromotion", "caseClass", "window", "qualified", "selfVerdict" })
        {
            var root = JsonNode.Parse(KnownText())!.AsObject();
            root["cases"]![0]![field] = "not a runtime input";
            Assert.Throws<InvalidDataException>(() => ResearchLiveManifest.Read(root.ToJsonString()));
        }
        var duplicate = "{\"schema\":\"aijade.ch7.live-case-manifest.v1\"," + KnownText()[1..];
        Assert.Throws<InvalidDataException>(() => ResearchLiveManifest.Read(duplicate));
        var unknownRoot = JsonNode.Parse(KnownText())!.AsObject(); unknownRoot["expectedC2"] = true;
        Assert.Throws<InvalidDataException>(() => ResearchLiveManifest.Read(unknownRoot.ToJsonString()));
    }

    [Fact]
    public void Missing_wrong_typed_unbound_and_heldout_inputs_are_refused()
    {
        Action<JsonObject>[] changes =
        [
            r => r["purpose"] = "heldout",
            r => r["schema"] = "other",
            r => r["cases"] = null,
            r => r["cases"] = new JsonArray(),
            r => r["cases"]![0] = null,
            r => r["cases"]![0]!["caseId"] = r["cases"]![1]!["caseId"]!.DeepClone(),
            r => r["cases"]![0]!["caseId"] = "unsafe/identity",
            r => r["cases"]![0]!["conditions"] = new JsonArray("C1", "C1"),
            r => r["cases"]![0]!["conditions"] = new JsonArray("C1", "C3"),
            r => r["cases"]![0]!["requestedAct"] = "1",
            r => r["cases"]![0]!["codeSha256"] = "not-a-hash",
            r => r["cases"]![0]!["operations"] = null,
            r => r["cases"]![0]!["operations"]!.AsObject().Remove("mapperActOverride"),
            r => r["cases"]![0]!["operations"]!["receiptCaseId"] = "missing_case",
            r => r["cases"]![0]!["operations"]!["execution"] = "assume_pass",
            r => r["cases"]![0]!["operations"]!["repeatOutcome"] = 1,
            r => r["cases"]![0]!["operations"]!["claimedStage"] = "invented",
            r => r["cases"]![0]!["operations"]!["mapperActOverride"] = "unsupported",
        ];
        foreach (var change in changes)
        {
            var root = JsonNode.Parse(KnownText())!.AsObject(); change(root);
            Assert.Throws<InvalidDataException>(() => ResearchLiveManifest.Read(root.ToJsonString()));
        }
        var unbalanced = JsonNode.Parse(KnownText())!.AsObject();
        foreach (var c in unbalanced["cases"]!.AsArray()) c!["conditions"] = new JsonArray("C1", "C2");
        Assert.Throws<InvalidDataException>(() => ResearchLiveManifest.Read(unbalanced.ToJsonString()));
    }
}
