using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Dynamics;

namespace Aijade.Memory.Pgc;

/// <summary>
/// PGC results in their JSON shape (snake_case keys, fixed key order). This is the form stored in
/// pgc_write_plans.write_plan and hashed by replay checks, so it must not change.
/// </summary>
public static class PgcJson
{
    public static JsonObject Gate(PlasticityGate g) => new()
    {
        ["consolidationGain"] = g.ConsolidationGain,
        ["decayMultiplier"] = g.DecayMultiplier,
        ["retrievalNoise"] = g.RetrievalNoise,
        ["moodCongruenceWeight"] = g.MoodCongruenceWeight,
        ["socialBonus"] = g.SocialBonus,
        ["explorationTemperature"] = g.ExplorationTemperature,
    };

    public static JsonObject State(PgcState4 s) => new() { ["a"] = s.A, ["c"] = s.C, ["d"] = s.D, ["f"] = s.F };

    public static JsonObject Components(PgcStateComponents c) => new()
    {
        ["plasticity"] = Gate(c.Plasticity),
        ["evidence_strength"] = c.EvidenceStrength,
        ["contradiction_severity"] = c.ContradictionSeverity,
        ["evidence_uncertainty"] = c.EvidenceUncertainty,
        ["persona_shift_risk"] = c.PersonaShiftRisk,
    };

    public static JsonObject V6(PgcV6State v) => new()
    {
        ["tau"] = WireName.Of(v.Tau),
        ["s"] = State(v.S),
        ["rho0"] = v.Rho0,
        ["kappa"] = v.Kappa,
        ["dot"] = v.Dot,
        ["w_prime"] = v.WPrime,
        ["w"] = v.W,
        ["w_max_global"] = v.WMaxGlobal,
        ["w_max_at_f"] = v.WMaxAtF,
        ["commit_possible"] = v.CommitPossible,
        ["commit_reason"] = WireName.Of(v.CommitReason),
        ["fatigue_deferred"] = v.FatigueDeferred,
        ["contradiction_level"] = WireName.Of(v.ContradictionLevel),
    };

    public static JsonObject Snapshot(PgcStateSnapshot s)
    {
        var o = new JsonObject { ["pgc_state_id"] = s.PgcStateId, ["components"] = Components(s.Components) };
        if (s.PgcPolicyVersion is not null)
            o["pgc_policy_version"] = s.PgcPolicyVersion;
        if (s.V6 is not null)
            o["v6"] = V6(s.V6);
        return o;
    }

    public static JsonObject Entry(PgcWritePlanEntry e) => new()
    {
        ["memory_write_id"] = e.MemoryWriteId,
        ["decision"] = WireName.Of(e.Decision),
        ["final_intensity"] = e.FinalIntensity,
        ["reason_codes"] = new JsonArray(e.ReasonCodes.Select(c => (JsonNode?)WireName.Of(c)).ToArray()),
        ["expected_tests"] = new JsonArray(e.ExpectedTests.Select(t => (JsonNode?)t).ToArray()),
        ["pgc_state_snapshot"] = Snapshot(e.PgcStateSnapshot),
    };

    public static JsonObject Result(PgcDecisionResult r)
    {
        var report = new JsonObject();
        if (r.ContradictionReport.ConflictingEvidenceIds is { } ids)
            report["conflicting_evidence_ids"] = new JsonArray(ids.Select(i => (JsonNode?)i).ToArray());
        report["severity"] = r.ContradictionReport.Severity;
        return new JsonObject
        {
            ["pgc_state_id"] = r.PgcStateId,
            ["write_plan"] = new JsonArray(r.WritePlan.Select(e => (JsonNode?)Entry(e)).ToArray()),
            ["contradiction_report"] = report,
        };
    }
}
