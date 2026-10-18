using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Beliefs;
using Aijade.Memory.Model;
using Aijade.Memory.Pgc;
using Aijade.Memory.V9;

namespace Aijade.Tests;

/// <summary>The PGC gate and the MemoryTx engine must equal the recorded golden data on the same batches.</summary>
public class PgcTxTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "pgc-tx-golden.json"))).RootElement;

    private static List<string> Strings(JsonElement a) => a.EnumerateArray().Select(x => x.GetString()!).ToList();

    private static Belief ParseBelief(JsonElement b) => new(b.GetProperty("id").GetString()!, b.GetProperty("proposition").GetString()!, b.GetProperty("scope").GetString()!,
        b.GetProperty("confidence").GetDouble(), b.GetProperty("logit").GetDouble(), Strings(b.GetProperty("evidenceIds")), Strings(b.GetProperty("counterEvidenceIds")),
        b.GetProperty("validFrom").GetDouble(), null, System.Enum.Parse<BeliefStatus>(b.GetProperty("status").GetString()!, true),
        System.Enum.Parse<BeliefOwner>(b.GetProperty("owner").GetString()!, true), 0, 0, b.GetProperty("supportLogit").GetDouble(), b.GetProperty("counterLogit").GetDouble());

    private static EvidenceEntry ParseRecord(JsonElement r) => new(r.GetProperty("id").GetString()!, r.GetProperty("reliability").GetDouble(), r.GetProperty("likelihood").GetDouble());

    private static ContentSalience Salience(JsonElement s) => new(s.GetProperty("salience").GetDouble(), s.GetProperty("socialSalience").GetDouble(), s.GetProperty("novelty").GetDouble());

    internal static PgcCandidateWrite ParseCandidate(JsonElement c) => new(c.GetProperty("memory_write_id").GetString()!,
        WireName.Parse<MemoryKind>(c.GetProperty("memory_kind").GetString()!), JsonNode.Parse(c.GetProperty("candidate_payload").GetRawText()),
        Strings(c.GetProperty("evidence_ids")), c.GetProperty("proposed_intensity").GetDouble(),
        c.TryGetProperty("claim_ids", out var ids) ? Strings(ids) : null, c.TryGetProperty("salience", out var s) ? Salience(s) : null);

    private static PgcState4 State(JsonElement s) => new(s.GetProperty("a").GetDouble(), s.GetProperty("c").GetDouble(), s.GetProperty("d").GetDouble(), s.GetProperty("f").GetDouble());

    internal static PgcReadContext ParseContext(JsonElement c) => new(c.GetProperty("now").GetDouble(), [],
        EvidenceRecords: c.TryGetProperty("evidence_records", out var r) ? r.EnumerateArray().Select(ParseRecord).ToList() : null,
        Beliefs: c.TryGetProperty("beliefs", out var b) ? b.EnumerateArray().Select(ParseBelief).ToList() : null,
        V6State: c.TryGetProperty("pgc_v6_state", out var s) ? State(s) : null);

    private static readonly List<PgcCandidateWrite> Candidates = Golden.GetProperty("cands").EnumerateArray().Select(ParseCandidate).ToList();

    private static readonly List<PgcReadContext> Contexts = Golden.GetProperty("ctxs").EnumerateArray().Select(ParseContext).ToList();

    private static readonly string[] PolicyVersions = ["pgc_policy_v1", "pgc_policy_neutral"];

    private static List<PgcDecisionResult> Decisions() =>
        Contexts.SelectMany(ctx => PolicyVersions.Select(v => PgcGate.Decide(new PgcInput("s1", "t1", Candidates, ctx, v)))).ToList();

    [Fact]
    public void Write_plans_are_byte_identical_to_the_original()
    {
        foreach (var (expected, actual) in Golden.GetProperty("decisions").EnumerateArray().Zip(Decisions()))
            Assert.Equal(expected.GetRawText(), JsFormat.Stringify(PgcJson.Result(actual)));
        var strictPolicy = PgcGate.DefaultPolicyV1 with { Version = "strict", RequireEvidenceRecordsForSufficiency = true };
        foreach (var (expected, cand) in Golden.GetProperty("strict").EnumerateArray().Zip(Candidates))
            Assert.Equal(expected.GetRawText(), JsFormat.Stringify(PgcJson.Entry(PgcGate.DecideCandidate(cand, Contexts[0], strictPolicy))));
    }

    [Fact]
    public void Write_plan_event_reproduces_the_original_policy_version_segment()
    {
        var envelope = new JsonObject
        {
            ["event_id"] = "evt_p", ["trace_id"] = "t1", ["correlation_id"] = "t1", ["timestamp"] = 1_700_000_000_001, ["producer"] = "pgc",
            ["origin_device"] = "dev", ["privacy_level"] = 0, ["evidence_refs"] = new JsonArray(), ["causal_context_refs"] = new JsonArray(),
            ["risk_score"] = 0, ["idempotency_key"] = "k", ["replay_mode"] = "live", ["risk_level"] = "low",
        };
        Assert.Equal(Golden.GetProperty("planEvent").GetString(), JsFormat.Stringify(PgcGate.BuildWritePlanReadyEvent(Decisions()[0], envelope)));
    }

    [Fact]
    public void W_max_bounds_match_the_original()
    {
        var c1 = Golden.GetProperty("case1");
        Tau[] taus = [Tau.Episodic, Tau.Affective, Tau.Procedural, Tau.Semantic];
        PgcV6Params Params(double kappa) => new(taus.ToDictionary(t => t, t => c1.GetProperty("rho0_by_tau").GetProperty(WireName.Of(t)).GetDouble()), kappa,
            taus.ToDictionary(t => t, t => State(c1.GetProperty("alpha_by_tau").GetProperty(WireName.Of(t)))));
        var actual = taus.SelectMany(t => new[]
        {
            PgcGate.ComputeV6WMaxBounds(t), PgcGate.ComputeV6WMaxBounds(t, null, 0.73), PgcGate.ComputeV6WMaxBounds(t, Params(0.5), 0.4), PgcGate.ComputeV6WMaxBounds(t, Params(1.6), 0.9),
        });
        foreach (var (e, a) in Golden.GetProperty("bounds").EnumerateArray().Zip(actual))
        {
            Assert.Equal(e.GetProperty("w_max_global").GetDouble(), a.WMaxGlobal);
            Assert.Equal(e.GetProperty("w_max_at_f").ValueKind == JsonValueKind.Null ? null : e.GetProperty("w_max_at_f").GetDouble(), a.WMaxAtF);
        }
    }

    internal static MemoryPayload ParsePayload(JsonElement p)
    {
        var n = p.GetProperty("normalized_payload");
        var a = n.GetProperty("attributes");
        return new MemoryPayload(p.GetProperty("memory_write_id").GetString()!,
            new NormalizedPayload(WireName.Parse<MemoryKind>(n.GetProperty("memory_kind").GetString()!), JsonNode.Parse(n.GetProperty("content_object").GetRawText()),
                new MemoryPayloadAttributes(Strings(a.GetProperty("tags")), Strings(a.GetProperty("source_claim_ids")),
                    a.TryGetProperty("risk_level", out var r) ? r.GetString() : null, a.TryGetProperty("salience", out var s) ? Salience(s) : null),
                n.TryGetProperty("embedding_input_text", out var e) ? e.GetString() : null),
            p.GetProperty("evidence_pack_id").GetString()!, Strings(p.GetProperty("evidence_ids")),
            new Provenance(p.GetProperty("provenance").GetProperty("source").GetString()!, p.GetProperty("provenance").GetProperty("actor").GetString()!));
    }

    [Fact]
    public void Transactions_match_the_original()
    {
        var payloads = Golden.GetProperty("payloads").EnumerateArray().Select(ParsePayload).ToList();
        var engine = new MemoryTxEngine(GatingCoefficients.Default, time: new FixedTime(1_700_000_000_000));
        var decisions = Decisions();
        var expected = Golden.GetProperty("txs").EnumerateArray().ToArray();
        for (var i = 0; i < decisions.Count; i++)
        {
            var policy = new TxPolicy(i % 2 == 0 ? TxAtomicity.PerWrite : TxAtomicity.Bundle, 3 + (i % 3));
            var ctx = i == 4 ? new MemoryTxEnvelopeContext("phone", 2, 0.37, Tick: 9, CausalityInputHash: "h9") : null;
            var r = engine.Commit(new MemoryTxInput("s1", $"t{i}", decisions[i].WritePlan, payloads, policy, EnvelopeContext: ctx));
            var e = expected[i].GetProperty("result");
            Assert.Equal(e.GetProperty("tx_id").GetString(), r.TxId);
            Assert.Equal(e.GetProperty("status").GetString(), WireName.Of(r.Status));
            Assert.Equal(e.GetProperty("committed").EnumerateArray().Select(c => (c.GetProperty("memory_version_id").GetString(), c.GetProperty("gating").GetProperty("content_hash").GetString())),
                r.Committed.Select(c => ((string?)c.MemoryVersionId, c.Gating.ContentHash)));
            Assert.Equal(e.GetProperty("rejected").EnumerateArray().Select(c => (c.GetProperty("memory_write_id").GetString(), c.GetProperty("reason").GetString())),
                r.Rejected.Select(c => ((string?)c.MemoryWriteId, (string?)c.Reason)));
            Assert.Equal(e.GetProperty("throttled").EnumerateArray().Select(c => (c.GetProperty("memory_write_id").GetString(), c.GetProperty("decision").GetString())),
                r.Throttled.Select(c => ((string?)c.MemoryWriteId, (string?)WireName.Of(c.Decision))));
            foreach (var (eg, g) in e.GetProperty("committed").EnumerateArray().Concat(e.GetProperty("rejected").EnumerateArray()).Select(x => x.GetProperty("gating"))
                .Zip(r.Committed.Select(c => c.Gating).Concat(r.Rejected.Select(c => c.Gating))))
            {
                Assert.Equal(eg.GetProperty("w").ValueKind == JsonValueKind.Null ? null : eg.GetProperty("w").GetDouble(), g.W);
                Assert.Equal(eg.GetProperty("commit_reason").ValueKind == JsonValueKind.Null ? null : eg.GetProperty("commit_reason").GetString(), g.CommitReason is { } cr ? WireName.Of(cr) : null);
            }
            Assert.Equal(e.GetProperty("audit_log").GetProperty("events").EnumerateArray().Select(a => a.GetProperty("afterHash").GetString()), r.AuditLog.Select(a => a.AfterHash));
            Assert.Equal(e.GetProperty("events")[0].GetRawText(), JsFormat.Stringify(r.Events[0]));
            var versions = expected[i].GetProperty("versions").EnumerateArray().ToArray();
            var actualVersions = engine.GetVersionsForTx(r.TxId);
            Assert.Equal(versions.Length, actualVersions.Count);
            foreach (var (ev, av) in versions.Zip(actualVersions))
            {
                Assert.Equal(ev.GetProperty("durability").GetDouble(), av.Durability);
                Assert.Equal(ev.GetProperty("intensity").GetDouble(), av.Intensity);
                Assert.Equal(ev.GetProperty("pgcStateId").GetString(), av.PgcStateId);
                Assert.Equal(ev.TryGetProperty("riskLevel", out var rl) ? rl.GetString() : null, av.RiskLevel);
            }
        }
        // Idempotent: the same transaction id returns the first result and creates nothing.
        var again = engine.Commit(new MemoryTxInput("s1", "t1", decisions[1].WritePlan, payloads, new TxPolicy(TxAtomicity.Bundle, 4)));
        Assert.Same(again, engine.Commit(new MemoryTxInput("s1", "t1", [], [], new TxPolicy(TxAtomicity.PerWrite, 1))));
    }

    [Fact]
    public void Gate_requires_a_capability_token_and_versions_always_carry_evidence()
    {
        var engine = new MemoryTxEngine(gate: new Aijade.Memory.Kernel.MemoryWriteGate(new NullSigner(), []));
        Assert.Throws<Aijade.Memory.Kernel.MemoryWriteDeniedException>(() => engine.Commit(new MemoryTxInput("s", "t", [], [], new TxPolicy(TxAtomicity.PerWrite, 1))));
        var plain = new MemoryTxEngine();
        var payloads = Golden.GetProperty("payloads").EnumerateArray().Select(ParsePayload).ToList();
        plain.Commit(new MemoryTxInput("s", "t", Decisions()[2].WritePlan, payloads, new TxPolicy(TxAtomicity.PerWrite, 99)));
        Assert.All(plain.GetVersionsForTx("tx_s_t"), v => Assert.True(v.EvidencePackId.Length > 0 && v.EvidenceIds.Count > 0));
    }

    private sealed class NullSigner : Aijade.Memory.Kernel.ICapabilityTokenSigner
    {
        public Task<string> SignAsync(Aijade.Memory.Kernel.CapabilityClaims claims, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<Aijade.Memory.Kernel.CapabilityClaims> VerifyAsync(string token, CancellationToken cancellationToken = default) => throw new NotSupportedException();
    }
}

/// <summary>Replays the recorded PGC inputs for other golden tests.</summary>
internal static class PgcTxTestsAccess
{
    public static PgcDecisionResult Decide(JsonElement pipeline, int context, string policy) => PgcGate.Decide(new PgcInput("s1", "t1",
        pipeline.GetProperty("cands").EnumerateArray().Select(PgcTxTests.ParseCandidate).ToList(),
        PgcTxTests.ParseContext(pipeline.GetProperty("ctxs")[context]), policy));

    public static List<MemoryPayload> Payloads(JsonElement pipeline) => pipeline.GetProperty("payloads").EnumerateArray().Select(PgcTxTests.ParsePayload).ToList();
}
