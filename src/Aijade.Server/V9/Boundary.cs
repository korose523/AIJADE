using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace Aijade.Server.V9;

// The HTTP boundary's own validation of the v9 / v10 event envelope and of every topic payload.
//
// Deliberately independent of the kernel's event schema (Aijade.Memory.Kernel.AijadeEvents): the contract-drift matrix
// can only detect drift between the two if they are two separate implementations of one contract. Do not "simplify" this
// into a call to the kernel validator. Every object is strict: a missing field, an empty required string, a wrong type or
// an unknown extra field is a 400 and nothing is written — an extra field must never be a way around the contract.

/// <summary>One validation finding: where and what.</summary>
public sealed record BoundaryIssue(string Path, string Message);

/// <summary>A boundary rule over a JSON value.</summary>
public abstract class Rule
{
    public abstract void Check(JsonNode? value, string path, List<BoundaryIssue> issues);

    public IReadOnlyList<BoundaryIssue> Validate(JsonNode? value)
    {
        var issues = new List<BoundaryIssue>();
        Check(value, "$", issues);
        return issues;
    }
}

public static class R
{
    private static bool IsNumber(JsonNode? v, out double d)
    {
        d = 0;
        if (v is JsonValue jv && jv.GetValueKind() == JsonValueKind.Number)
        {
            d = double.Parse(jv.ToJsonString(), CultureInfo.InvariantCulture);
            return double.IsFinite(d);
        }
        return false;
    }

    private static string? AsString(JsonNode? v) => v is JsonValue jv && jv.GetValueKind() == JsonValueKind.String ? jv.GetValue<string>() : null;

    private sealed class StrRule(int minLength, Regex? pattern) : Rule
    {
        public override void Check(JsonNode? value, string path, List<BoundaryIssue> issues)
        {
            if (AsString(value) is not { } s)
                issues.Add(new(path, "expected string"));
            else if (s.Length < minLength)
                issues.Add(new(path, $"expected length >= {minLength}"));
            else if (pattern is not null && !pattern.IsMatch(s))
                issues.Add(new(path, $"expected to match {pattern}"));
        }
    }

    private sealed class NumRule(bool integer, double? min, double? max) : Rule
    {
        public override void Check(JsonNode? value, string path, List<BoundaryIssue> issues)
        {
            if (!IsNumber(value, out var d))
                issues.Add(new(path, "expected number"));
            else if (integer && Math.Floor(d) != d)
                issues.Add(new(path, "expected integer"));
            else if (min is { } lo && d < lo)
                issues.Add(new(path, $"expected >= {lo.ToString(CultureInfo.InvariantCulture)}"));
            else if (max is { } hi && d > hi)
                issues.Add(new(path, $"expected <= {hi.ToString(CultureInfo.InvariantCulture)}"));
        }
    }

    private sealed class PickRule(IReadOnlyList<object> options) : Rule
    {
        public override void Check(JsonNode? value, string path, List<BoundaryIssue> issues)
        {
            var ok = options.Any(o => o switch
            {
                string s => AsString(value) == s,
                double n => IsNumber(value, out var d) && d == n,
                _ => false,
            });
            if (!ok)
                issues.Add(new(path, $"expected one of {string.Join("|", options.Select(o => Convert.ToString(o, CultureInfo.InvariantCulture)))}"));
        }
    }

    private sealed class ArrRule(Rule item, int minLength) : Rule
    {
        public override void Check(JsonNode? value, string path, List<BoundaryIssue> issues)
        {
            if (value is not JsonArray a)
            {
                issues.Add(new(path, "expected array"));
                return;
            }
            for (var i = 0; i < a.Count; i++)
                item.Check(a[i], $"{path}[{i}]", issues);
            if (a.Count < minLength)
                issues.Add(new(path, $"expected length >= {minLength}"));
        }
    }

    private sealed class RecordRule(Rule? item) : Rule
    {
        public override void Check(JsonNode? value, string path, List<BoundaryIssue> issues)
        {
            if (value is not JsonObject o)
            {
                issues.Add(new(path, "expected object"));
                return;
            }
            if (item is null)
                return;
            foreach (var (k, v) in o)
                item.Check(v, $"{path}.{k}", issues);
        }
    }

    /// <summary>
    /// An object rule: every declared field must satisfy its rule (optional fields may be absent). A strict object also refuses
    /// any other key; a loose one ignores extra keys.
    /// </summary>
    public sealed class StrictRule(IReadOnlyList<(string Name, Rule Rule, bool Optional)> fields, bool strict = true) : Rule
    {
        /// <summary>
        /// Measurement switch for the validation-overhead experiment (P1 limitation 2): on the current thread, unknown keys
        /// are tolerated instead of rejected, so the same rules can be timed in a liberal mode. Never set by the server.
        /// </summary>
        [ThreadStatic]
        internal static bool TolerateUnknownKeys;

        public IReadOnlyList<string> FieldNames { get; } = fields.Select(f => f.Name).ToList();

        public override void Check(JsonNode? value, string path, List<BoundaryIssue> issues)
        {
            if (value is not JsonObject o)
            {
                issues.Add(new(path, "expected object"));
                return;
            }
            foreach (var (name, rule, optional) in fields)
            {
                if (!o.ContainsKey(name))
                {
                    if (!optional)
                        issues.Add(new($"{path}.{name}", "required"));
                    continue;
                }
                rule.Check(o[name], $"{path}.{name}", issues);
            }
            foreach (var (key, _) in o)
            {
                if (strict && !TolerateUnknownKeys && !FieldNames.Contains(key))
                    issues.Add(new($"{path}.{key}", "unknown key"));
            }
        }
    }

    public static Rule Str(int minLength = 0) => new StrRule(minLength, null);

    public static Rule Pattern(Regex pattern) => new StrRule(0, pattern);

    public static Rule Num(double? min = null, double? max = null) => new NumRule(false, min, max);

    public static Rule Whole(double? min = null, double? max = null) => new NumRule(true, min, max);

    public static Rule Pick(params object[] options) => new PickRule(options);

    public static Rule Arr(Rule item, int minLength = 0) => new ArrRule(item, minLength);

    public static Rule Record(Rule? item = null) => new RecordRule(item);

    public static StrictRule Strict(params (string Name, Rule Rule, bool Optional)[] fields) => new(fields);

    public static StrictRule Loose(params (string Name, Rule Rule, bool Optional)[] fields) => new(fields, strict: false);

    public static (string, Rule, bool) Req(string name, Rule rule) => (name, rule, false);

    public static (string, Rule, bool) Opt(string name, Rule rule) => (name, rule, true);
}

public static partial class V9Boundary
{
    /// <summary>The persisted tick column is int32; anything above must be refused at the boundary, never leak as a 500.</summary>
    public const double Int32Max = 2_147_483_647;

    public static IReadOnlyList<string> Topics { get; } =
    [
        "aijade.active_learning.requested",
        "aijade.active_learning.completed",
        "aijade.evidence.weave_candidate_ready",
        "aijade.pgc.write_plan_ready",
        "aijade.memory_tx.committed",
        "aijade.persona.render_requested",
        "aijade.lpm.render_ready",
        "aijade.video.observation.webpage_text",
        "aijade.video.observation.video_transcript",
        "aijade.learning.proposed.shadow_params",
        "aijade.learning.proposed.evidence",
        "aijade.learning.constraint.opinion_evaluation",
    ];

    [GeneratedRegex("^S[0-8]$", RegexOptions.CultureInvariant)]
    private static partial Regex CoreStateNodePattern();

    private static readonly Rule NonEmpty = R.Str(1);
    private static readonly Rule NonNegInt = R.Whole(0);
    private static readonly Rule Tick = R.Whole(0, Int32Max);
    private static readonly Rule Confidence = R.Num(0, 1);
    private static readonly Rule Causality = R.Strict(R.Req("inputHash", NonEmpty));

    public static R.StrictRule Envelope { get; } = R.Strict(
        R.Req("event_id", NonEmpty),
        R.Req("trace_id", NonEmpty),
        R.Req("correlation_id", NonEmpty),
        R.Req("timestamp", NonNegInt),
        R.Req("producer", NonEmpty),
        R.Req("origin_device", NonEmpty),
        R.Req("privacy_level", R.Pick(0.0, 1.0, 2.0, 3.0)),
        R.Req("evidence_refs", R.Arr(R.Str())),
        R.Req("causal_context_refs", R.Arr(R.Str())),
        R.Req("risk_score", R.Num(0, 1)),
        R.Req("idempotency_key", NonEmpty),
        R.Req("replay_mode", R.Pick("live", "replay")),
        R.Req("risk_level", R.Pick("low", "medium", "high")),
        R.Opt("tick", Tick),
        R.Opt("causality", Causality),
        R.Opt("core_state_node", R.Pattern(CoreStateNodePattern())),
        R.Req("topic", R.Pick([.. Topics])),
        R.Req("payload", R.Record()));

    /// <summary>v10 fields that video / learning topics must carry.</summary>
    public static Rule V10Fields { get; } = R.Strict(R.Req("tick", Tick), R.Req("causality", Causality));

    public static Rule Replay { get; } = R.Strict(R.Req("tick", Tick), R.Req("inputHash", NonEmpty));

    /// <summary>Per-topic payload rules; field names and requiredness mirror the kernel contract, written independently.</summary>
    public static IReadOnlyDictionary<string, Rule> Payloads { get; } = new Dictionary<string, Rule>(StringComparer.Ordinal)
    {
        ["aijade.active_learning.requested"] = R.Strict(
            R.Req("session_id", NonEmpty), R.Req("trace_id", NonEmpty), R.Req("requested_at", NonNegInt), R.Opt("target", R.Str()),
            R.Req("quest_ref", NonEmpty),
            R.Req("resource_budget", R.Strict(R.Req("allocated", R.Num(0)), R.Req("spent", R.Num(0)), R.Req("unit", R.Pick("queries", "minutes", "usd", "tokens")))),
            // Non-empty stop conditions: "browsing without an end" must not even be expressible.
            R.Req("stop_conditions", R.Arr(NonEmpty, 1))),
        ["aijade.active_learning.completed"] = R.Strict(
            R.Req("session_id", NonEmpty), R.Req("trace_id", NonEmpty), R.Req("completed_at", NonNegInt), R.Opt("result_ref", R.Str()),
            R.Req("quest_ref", NonEmpty)),
        // graph_hash is the weave's content identity; a blank one would be a weave without a graph.
        ["aijade.evidence.weave_candidate_ready"] = R.Strict(
            R.Req("tx_id", NonEmpty), R.Req("weave_id", NonEmpty), R.Req("graph_hash", NonEmpty), R.Req("candidate_memory_write_ids", R.Arr(NonEmpty))),
        ["aijade.pgc.write_plan_ready"] = R.Strict(R.Req("pgc_state_id", NonEmpty), R.Req("write_plan_size", NonNegInt), R.Req("policy_version", NonEmpty)),
        ["aijade.memory_tx.committed"] = R.Strict(
            R.Req("tx_id", NonEmpty), R.Req("trace_id", NonEmpty), R.Req("committed_count", NonNegInt), R.Req("rejected_count", NonNegInt),
            R.Req("throttled_count", NonNegInt)),
        // The persona snapshot and intent refs are the only way the snapshot → intent → render chain can be traced back.
        ["aijade.persona.render_requested"] = R.Strict(R.Req("session_id", NonEmpty), R.Req("persona_snapshot_ref", NonEmpty), R.Req("intent_ref", NonEmpty)),
        // asset_version_hash is optional (resolved asynchronously), but when given it must be non-empty.
        ["aijade.lpm.render_ready"] = R.Strict(
            R.Req("session_id", NonEmpty), R.Req("render_ref", NonEmpty), R.Req("applied_params_hash", NonEmpty), R.Opt("asset_version_hash", NonEmpty)),
        ["aijade.video.observation.webpage_text"] = R.Strict(
            R.Req("session_id", NonEmpty), R.Req("source_url", NonEmpty), R.Req("content_hash", NonEmpty),
            R.Req("spans", R.Arr(R.Strict(R.Req("start_offset", NonNegInt), R.Req("end_offset", NonNegInt), R.Opt("label", NonEmpty)), 1)),
            R.Req("observation_text", NonEmpty)),
        ["aijade.video.observation.video_transcript"] = R.Strict(
            R.Req("session_id", NonEmpty), R.Req("video_id", NonEmpty), R.Req("transcript_hash", NonEmpty),
            R.Req("time_spans", R.Arr(R.Strict(R.Req("start_ms", NonNegInt), R.Req("end_ms", NonNegInt), R.Req("text", NonEmpty)), 1)),
            R.Req("caption_text", NonEmpty)),
        ["aijade.learning.proposed.shadow_params"] = R.Strict(
            R.Req("session_id", NonEmpty), R.Req("proposal_id", NonEmpty), R.Req("render_ref", NonEmpty), R.Req("applied_params_hash", NonEmpty),
            R.Req("asset_version_hash", NonEmpty), R.Req("input_hash", NonEmpty), R.Req("candidate_params", R.Record()), R.Req("confidence", Confidence)),
        ["aijade.learning.proposed.evidence"] = R.Strict(
            R.Req("session_id", NonEmpty), R.Req("proposal_id", NonEmpty), R.Req("render_ref", NonEmpty), R.Req("applied_params_hash", NonEmpty),
            R.Req("asset_version_hash", NonEmpty), R.Req("evidence_hash", NonEmpty), R.Req("claim_text", NonEmpty), R.Req("confidence", Confidence)),
        ["aijade.learning.constraint.opinion_evaluation"] = R.Strict(
            R.Req("evaluation_target", NonEmpty),
            R.Req("claims", R.Arr(R.Strict(R.Req("claim_text", NonEmpty), R.Req("confidence", Confidence)), 1)),
            R.Req("uncertainty_notes", NonEmpty)),
    };

    public static Rule Perception { get; } = R.Strict(
        R.Req("event_id", NonEmpty), R.Req("session_id", NonEmpty), R.Req("trace_id", NonEmpty), R.Req("correlation_id", NonEmpty),
        R.Req("timestamp", NonNegInt), R.Req("origin_device", NonEmpty), R.Req("privacy_level", R.Pick(0.0, 1.0, 2.0, 3.0)),
        R.Req("risk_score", R.Num(0)), R.Req("source", NonEmpty), R.Req("content", NonEmpty), R.Opt("stimulus_features", R.Record(R.Num())),
        R.Opt("risk_level", R.Pick("low", "medium", "high")));

    public static Rule PersonaDerive { get; } = R.Strict(
        R.Req("session_id", NonEmpty), R.Req("device_id", NonEmpty), R.Req("agent_id", NonEmpty), R.Req("user_scope", NonEmpty),
        R.Req("privacy_level", R.Whole(0, 3)), R.Opt("step_count", R.Whole(1)), R.Opt("duration", R.Whole(0)));

    /// <summary>Topics that carry the v10 tick and input hash as a requirement.</summary>
    public static bool RequiresV10(string topic) => topic.StartsWith("aijade.video.", StringComparison.Ordinal) || topic.StartsWith("aijade.learning.", StringComparison.Ordinal);

    /// <summary>Topics without a payload rule; must be empty, checked at startup (a new topic may not slip through unvalidated).</summary>
    public static IReadOnlyList<string> TopicsWithoutPayloadRule => Topics.Where(t => !Payloads.ContainsKey(t)).ToList();
}
