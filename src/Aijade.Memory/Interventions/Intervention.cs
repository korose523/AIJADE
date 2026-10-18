using Aijade.Core.Js;
using Aijade.Core.Random;
using Aijade.Memory.Contracts;
using Aijade.Memory.Experiments;

namespace Aijade.Memory.Interventions;

// v7 §38 unified intervention API. An ablation is declared as a plan (switch overrides + bypasses) instead of a code
// edit; resolving it with a fixed seed yields the full effective switch map and a deterministic fingerprint, so "these
// two runs used the same configuration" is provable. Unknown switches are rejected so a typo can never take silent effect.
// Pure; it only describes a configuration and never changes default memory durability / salience (H2c guard).

public enum InterventionGroup
{
    MemoryBaseline,
    Hac,
    Dgm,
    Cdi,
}

public sealed record InterventionPoint(string Id, InterventionGroup Group, string Description, bool DefaultOn);

/// <summary>A baseline or ablation. <see cref="Switches"/> are overrides of the defaults; bypass keys must be point ids.</summary>
public sealed record InterventionPlan(
    string Id, string Name, string Description, IReadOnlyDictionary<string, bool> Switches, IReadOnlyDictionary<string, string>? Bypass = null);

/// <summary>Opt-in product configuration: only when enabled does a store hold an intervention (H2c).</summary>
public sealed record InterventionConfig(bool Enabled, double Seed = 0, InterventionPlan? Plan = null);

/// <summary>Effective switches (defaults ⊕ overrides), bypasses, seed and fingerprint. Same (plan, seed) ⇒ same fingerprint.</summary>
public sealed record ResolvedIntervention(
    string PlanId, OrderedDictionary<string, bool> Switches, OrderedDictionary<string, string> Bypass, double Seed, string Fingerprint)
{
    /// <summary>Unknown points count as disabled (never silently allowed).</summary>
    public bool IsEnabled(string pointId) => Switches.GetValueOrDefault(pointId);

    public string? BypassOf(string pointId) => Bypass.GetValueOrDefault(pointId);
}

public sealed record RegisteredIntervention(ExperimentManifest Manifest, ResolvedIntervention Resolved);

public sealed class InterventionException(string message) : Exception(message);

public static class Interventions
{
    /// <summary>The single authoritative list of switches. Defaults = the full mechanism; ablations / anti-patterns default off.</summary>
    public static IReadOnlyList<InterventionPoint> Points { get; } =
    [
        // §38.1 memory baselines
        new("long_term_memory", InterventionGroup.MemoryBaseline, "长期记忆（关闭 = B0 无长期记忆）", true),
        new("memory_window", InterventionGroup.MemoryBaseline, "滑动窗口（B1）", false),
        new("vector_write_all", InterventionGroup.MemoryBaseline, "向量检索 + 全写入（B2）", false),
        new("salience_threshold", InterventionGroup.MemoryBaseline, "即时重要性阈值 / 内容显著性门控（B3）", true),
        new("llm_reflection", InterventionGroup.MemoryBaseline, "LLM 反思式记忆（B4）", false),
        new("memory_budget", InterventionGroup.MemoryBaseline, "固定预算多类记忆（B5）", false),

        // §38.2 HAC ablations
        new("hac_state", InterventionGroup.Hac, "内生状态 z_t（关闭 = 去除内生状态）", true),
        new("hac_homeostatic_error", InterventionGroup.Hac, "稳态误差 e_t（关闭 = 去除稳态误差）", true),
        new("hac_goal_utility", InterventionGroup.Hac, "未来目标效用（关闭 = 去除未来目标效用）", true),
        new("hac_active_replay", InterventionGroup.Hac, "主动回放（§9.4）", true),
        new("hac_retrieval_noise", InterventionGroup.Hac, "检索退化代价 ξ（§9.5；关闭 = 去除噪声代价）", true),
        new("hac_fix_transition", InterventionGroup.Hac, "固定状态转移矩阵（消融：A/B/C 不再演化）", false),
        new("hac_random_write", InterventionGroup.Hac, "随机同预算写入（对照：保留条数相同但随机选）", false),

        // §38.3 DGM ablations
        new("dgm_single_store", InterventionGroup.Dgm, "退化为单一向量库（消融）", false),
        new("dgm_dual_graph", InterventionGroup.Dgm, "经历图与信念图分离（关闭 = 不分离）", true),
        new("dgm_counter_evidence", InterventionGroup.Dgm, "反证边（关闭 = 无反证）", true),
        new("dgm_source_reliability", InterventionGroup.Dgm, "来源可靠度（关闭 = 无可靠度）", true),
        new("dgm_llm_commit", InterventionGroup.Dgm, "LLM 直接提交信念（反模式消融，默认关闭）", false),

        // §38.4 CDI ablations
        new("cdi_identity", InterventionGroup.Cdi, "身份层演化（关闭 = 静态人格）", true),
        new("cdi_constraint", InterventionGroup.Cdi, "‖Δp‖≤ε 等约束（关闭 = 自由人格演化）", true),
        new("cdi_prompt_only", InterventionGroup.Cdi, "仅角色提示词累积（消融）", false),
        new("cdi_shadow_eval", InterventionGroup.Cdi, "影子评测（关闭 = 无影子评测）", true),
    ];

    private static readonly Dictionary<string, InterventionPoint> PointIndex = Points.ToDictionary(p => p.Id);

    public static IReadOnlyDictionary<string, bool> DefaultSwitches { get; } = new OrderedDictionary<string, bool>(Points.Select(p => KeyValuePair.Create(p.Id, p.DefaultOn)));

    private static OrderedDictionary<string, bool> S(params (string Id, bool On)[] s) => new(s.Select(x => KeyValuePair.Create(x.Id, x.On)));

    /// <summary>§38.1 memory baselines B0–B5 and the full model A1.</summary>
    public static IReadOnlyList<InterventionPlan> BaselinePlans { get; } =
    [
        new("B0", "B0 无长期记忆", "旁路全部长期记忆", S(("long_term_memory", false))),
        new("B1", "B1 滑动窗口", "仅保留最近窗口内的内容", S(("long_term_memory", false), ("memory_window", true)),
            new OrderedDictionary<string, string> { ["long_term_memory"] = "window(8)" }),
        new("B2", "B2 向量检索 + 全写入", "不筛选，全量写入后检索", S(("vector_write_all", true), ("salience_threshold", false))),
        new("B3", "B3 即时重要性阈值", "按即时重要性阈值筛选", S(("salience_threshold", true))),
        new("B4", "B4 LLM 反思式记忆", "由 LLM 反思决定保留", S(("llm_reflection", true))),
        new("B5", "B5 固定预算多类记忆", "多类记忆 + 固定存储预算", S(("memory_budget", true))),
        new("A1", "A1 HAC 完整模型", "HAC 全开（我们的完整机制）—— 显式钉住全量配置，作为消融的对照基准", S(
            ("hac_state", true), ("hac_homeostatic_error", true), ("hac_goal_utility", true), ("hac_active_replay", true),
            ("hac_retrieval_noise", true), ("hac_fix_transition", false), ("hac_random_write", false))),
    ];

    /// <summary>§38.2 HAC ablations.</summary>
    public static IReadOnlyList<InterventionPlan> HacAblationPlans { get; } =
    [
        new("hac-no-state", "去除内生状态", "冻结/移除 z_t", S(("hac_state", false))),
        new("hac-no-error", "去除稳态误差", "e_t 不再驱动写入门控", S(("hac_homeostatic_error", false))),
        new("hac-no-goal", "去除未来目标效用", "U_i 去掉未来目标项", S(("hac_goal_utility", false))),
        new("hac-no-replay", "去除主动回放", "不做 §9.4 主动回放", S(("hac_active_replay", false))),
        new("hac-no-noise", "去除检索噪声代价", "关闭 §9.5 检索退化代价", S(("hac_retrieval_noise", false))),
        new("hac-fix-transition", "固定状态转移", "A/B/C 固定不演化", S(("hac_fix_transition", true))),
        new("hac-random-write", "随机同预算写入", "保留条数相同但随机选择（需固定种子）", S(("hac_random_write", true))),
    ];

    /// <summary>§38.3 DGM ablations.</summary>
    public static IReadOnlyList<InterventionPlan> DgmAblationPlans { get; } =
    [
        new("dgm-single-store", "单一向量库", "退化为单一向量库", S(("dgm_single_store", true))),
        new("dgm-no-separation", "经历与信念不分离", "关闭双图分离", S(("dgm_dual_graph", false))),
        new("dgm-no-counter", "无反证边", "不接受/不记录反证", S(("dgm_counter_evidence", false))),
        new("dgm-no-reliability", "无来源可靠度", "来源一律同等可信", S(("dgm_source_reliability", false))),
        new("dgm-llm-commit", "LLM 直接提交信念", "反模式：绕过验证器直接入库", S(("dgm_llm_commit", true))),
    ];

    /// <summary>§38.4 CDI ablations.</summary>
    public static IReadOnlyList<InterventionPlan> CdiAblationPlans { get; } =
    [
        new("cdi-static", "静态人格", "身份层不演化", S(("cdi_identity", false))),
        new("cdi-free", "自由人格演化", "去掉漂移界等约束", S(("cdi_constraint", false))),
        new("cdi-prompt-only", "仅角色提示词累积", "退化为提示词堆叠", S(("cdi_prompt_only", true))),
        new("cdi-no-shadow", "CDI 无影子评测", "不做影子评测即提交", S(("cdi_shadow_eval", false))),
        new("cdi-full", "CDI 完整机制", "三层身份 + 约束 + 影子评测 —— 显式钉住全量配置，作为消融的对照基准", S(
            ("cdi_identity", true), ("cdi_constraint", true), ("cdi_shadow_eval", true), ("cdi_prompt_only", false))),
    ];

    public static IReadOnlyList<InterventionPlan> AllAblationPlans { get; } = [.. BaselinePlans, .. HacAblationPlans, .. DgmAblationPlans, .. CdiAblationPlans];

    /// <summary>Order-independent serialization: keys sorted, so switch order never changes the fingerprint.</summary>
    private static string Canonical(InterventionPlan plan, IReadOnlyDictionary<string, bool> switches, double seed)
    {
        var sw = string.Join(",", switches.Keys.Order(StringComparer.Ordinal).Select(k => $"{k}={(switches[k] ? 1 : 0)}"));
        var bypass = plan.Bypass ?? new Dictionary<string, string>();
        var bp = string.Join(",", bypass.Keys.Order(StringComparer.Ordinal).Select(k => $"{k}={bypass[k]}"));
        return $"{plan.Id}|{sw}|{bp}|seed={JsFormat.Number(seed)}";
    }

    /// <summary>Rejects a missing id, an empty override map, and unknown switch or bypass points. Never throws.</summary>
    public static Validation Validate(InterventionPlan plan)
    {
        if (string.IsNullOrEmpty(plan.Id))
            return Validation.Fail("InterventionPlan requires an id");
        if (plan.Switches.Count == 0)
            return Validation.Fail("InterventionPlan must change ≥1 switch (an ablation must ablate something)");
        foreach (var id in plan.Switches.Keys)
        {
            if (!PointIndex.ContainsKey(id))
                return Validation.Fail($"Unknown intervention point \"{id}\"");
        }
        foreach (var id in (plan.Bypass ?? new Dictionary<string, string>()).Keys)
        {
            if (!PointIndex.ContainsKey(id))
                return Validation.Fail($"Unknown bypass point \"{id}\"");
        }
        return Validation.Pass;
    }

    public static ResolvedIntervention Resolve(InterventionPlan plan, double seed = 0)
    {
        var v = Validate(plan);
        if (!v.Ok)
            throw new InterventionException($"InterventionPlan \"{plan.Id}\" invalid: {v.Reason}");
        if (!double.IsFinite(seed))
            throw new InterventionException("Intervention requires a finite seed (reproducibility)");
        var switches = new OrderedDictionary<string, bool>(DefaultSwitches);
        foreach (var (k, on) in plan.Switches)
            switches[k] = on;
        var bypass = new OrderedDictionary<string, string>(plan.Bypass ?? new Dictionary<string, string>());
        return new ResolvedIntervention(plan.Id, switches, bypass, seed, JsFormat.Fnv1a(Canonical(plan, switches, seed)));
    }

    /// <summary>Seeded RNG for randomized ablations (e.g. hac_random_write); the seed is taken modulo 2^32 as in JS.</summary>
    public static Func<double> Rng(double seed) => new Mulberry32(JsFormat.ToUint32(seed)).AsFunc();

    /// <summary>Register the plan as a §38 ExperimentManifest condition, so an ablation is declared, registered and reproducible.</summary>
    public static RegisteredIntervention Register(InterventionPlan plan, ExperimentRegistry registry, double seed = 0, IReadOnlyList<string>? metrics = null)
    {
        var resolved = Resolve(plan, seed);
        var manifest = ExperimentManifests.Build(new ManifestSpec(
            $"intervention:{plan.Id}",
            plan.Name,
            [new ExperimentCondition(plan.Id, plan.Description, new Dictionary<string, object?>
            {
                ["switches"] = resolved.Switches,
                ["bypass"] = resolved.Bypass,
                ["fingerprint"] = resolved.Fingerprint,
            })],
            metrics ?? ["intervention.fingerprint"],
            Seed: seed,
            Notes: $"§38 intervention plan \"{plan.Id}\" ({plan.Description}). Fingerprint {resolved.Fingerprint} — identical (plan, seed) ⇒ identical configuration."));
        registry.Register(manifest);
        return new RegisteredIntervention(manifest, resolved);
    }
}
