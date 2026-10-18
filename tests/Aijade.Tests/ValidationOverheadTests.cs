using System.Diagnostics;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Server.V9;

namespace Aijade.Tests;

/// <summary>
/// P1 limitation 2, the cost of strict validation in isolation: a batch of envelopes is checked the way the v9 ingest route
/// checks them (envelope → v10 fields → per-topic payload), once as shipped (unknown keys rejected) and once in the liberal
/// mode of the same rules (unknown keys tolerated); JSON parsing alone is the floor. The behaviour on an unknown field is
/// always asserted; the timings are written to {AIJADE_EXPERIMENT_DIR}/validation-overhead.json when that is set.
/// </summary>
public class ValidationOverheadTests
{
    private const string Topic = "aijade.learning.constraint.opinion_evaluation";

    private static JsonObject Envelope(int i)
    {
        var id = $"bench-{i.ToString(CultureInfo.InvariantCulture)}";
        var payload = new JsonObject
        {
            ["evaluation_target"] = "bench-target",
            ["claims"] = new JsonArray(new JsonObject { ["claim_text"] = "bench claim", ["confidence"] = 0.5 }),
            ["uncertainty_notes"] = "bench run",
        };
        var inputHash = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(payload.ToJsonString() + id)));
        return new JsonObject
        {
            ["event_id"] = id, ["trace_id"] = $"trace-{id}", ["correlation_id"] = $"corr-{id}", ["timestamp"] = 1_760_000_000_000L + i,
            ["producer"] = "bench", ["origin_device"] = "bench-host", ["privacy_level"] = 1, ["evidence_refs"] = new JsonArray(),
            ["causal_context_refs"] = new JsonArray(), ["risk_score"] = 0.1, ["idempotency_key"] = $"idem-{id}", ["replay_mode"] = "live",
            ["risk_level"] = "low", ["tick"] = 1_000_000 + i, ["causality"] = new JsonObject { ["inputHash"] = inputHash }, ["topic"] = Topic,
            ["payload"] = payload,
        };
    }

    /// <summary>The ingest route's three checks; true when the envelope passes.</summary>
    private static bool Check(string text)
    {
        var env = JsonNode.Parse(text)!.AsObject();
        if (V9Boundary.Envelope.Validate(env).Count > 0)
            return false;
        var v10 = new JsonObject { ["tick"] = env["tick"]!.DeepClone(), ["causality"] = env["causality"]!.DeepClone() };
        return V9Boundary.V10Fields.Validate(v10).Count == 0 && V9Boundary.Payloads[Topic].Validate(env["payload"]!.AsObject()).Count == 0;
    }

    private static bool Liberal(Func<bool> f)
    {
        R.StrictRule.TolerateUnknownKeys = true;
        try
        {
            return f();
        }
        finally
        {
            R.StrictRule.TolerateUnknownKeys = false;
        }
    }

    [Fact]
    public async Task Strict_validation_rejects_unknown_fields_and_its_cost_is_measured()
    {
        var withExtra = Envelope(0);
        withExtra["payload"]!["rogue_field"] = 1;
        var extra = withExtra.ToJsonString();
        Assert.False(Check(extra));
        Assert.True(Liberal(() => Check(extra)));
        Assert.True(Check(Envelope(1).ToJsonString()));
        if (Environment.GetEnvironmentVariable("AIJADE_EXPERIMENT_DIR") is not { Length: > 0 } dir)
            return;

        const int Batch = 2000, Repeats = 31, Warmup = 5;
        var bodies = Enumerable.Range(0, Batch).Select(i => Envelope(i).ToJsonString()).ToArray();
        double PerEnvelopeUs(Func<string, bool> f)
        {
            var sw = Stopwatch.StartNew();
            foreach (var b in bodies)
            {
                if (!f(b))
                    throw new InvalidOperationException("a benchmark envelope failed validation");
            }
            return sw.Elapsed.TotalMicroseconds / Batch;
        }
        var samples = new Dictionary<string, List<double>> { ["json"] = [], ["strict"] = [], ["liberal"] = [] };
        for (var r = 0; r < Warmup + Repeats; r++)
        {
            var parseOnly = PerEnvelopeUs(b => JsonNode.Parse(b) is not null);
            var strict = PerEnvelopeUs(Check);
            var liberal = Liberal(() => { samples["liberal"].Add(PerEnvelopeUs(Check)); return true; });
            if (r < Warmup)
            {
                samples["liberal"].RemoveAt(samples["liberal"].Count - 1);
                continue;
            }
            samples["json"].Add(parseOnly);
            samples["strict"].Add(strict);
        }
        static double Median(List<double> xs)
        {
            var s = xs.Order().ToList();
            return s.Count % 2 == 1 ? s[s.Count / 2] : (s[(s.Count / 2) - 1] + s[s.Count / 2]) / 2;
        }
        var ingest = JsonNode.Parse(await File.ReadAllTextAsync(Path.Combine(dir, "ingest-sequential.json"), TestContext.Current.CancellationToken))!;
        var p50Ms = ingest["runs"]!["sequential"]!["p50"]!.GetValue<double>();
        double json = Median(samples["json"]), strictUs = Median(samples["strict"]), liberalUs = Median(samples["liberal"]);
        var report = new JsonObject
        {
            ["generatedBy"] = "tests/Aijade.Tests/ValidationOverheadTests.cs",
            ["runtime"] = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
            ["cpus"] = Environment.ProcessorCount,
            ["batch"] = Batch, ["repeats"] = Repeats, ["warmup"] = Warmup, ["topic"] = Topic,
            ["behaviourOnUnknownField"] = new JsonObject { ["strict"] = "rejects unknown field", ["liberal"] = "accepts unknown field" },
            ["perEnvelopeMedianUs"] = new JsonObject { ["jsonParse"] = json, ["strictCheck"] = strictUs, ["liberalCheck"] = liberalUs },
            ["validationOnlyUs"] = new JsonObject { ["strict"] = strictUs - json, ["liberal"] = liberalUs - json },
            ["strictMinusLiberalUs"] = strictUs - liberalUs,
            ["ingestP50Ms"] = p50Ms,
            ["shareOfIngestP50"] = new JsonObject { ["strictValidation"] = (strictUs - json) / 1000 / p50Ms, ["strictMinusLiberal"] = (strictUs - liberalUs) / 1000 / p50Ms },
        };
        Directory.CreateDirectory(dir);
        await File.WriteAllTextAsync(Path.Combine(dir, "validation-overhead.json"), JsFormat.Stringify(report, 2) + "\n", TestContext.Current.CancellationToken);
    }
}
