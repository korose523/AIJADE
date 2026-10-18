namespace Aijade.Growth.Pilot;

// §5.3 / Table 3 mechanism configurations: B0–B5 baselines, the full model A1, and the three ablations A1−HAC, A1−DGM and
// A1−CDI (the paper's HAC-abl / DGM-abl / CDI-abl rows).

/// <summary>Table 3 column 2: none (B0), sliding_window (B1), vector_allwrite (B2), importance_threshold (B3), llm_reflection (B4), fixed_budget (B5), hac_gated (A1).</summary>
public enum MemoryWriteStrategy
{
    None,
    SlidingWindow,
    VectorAllwrite,
    ImportanceThreshold,
    LlmReflection,
    FixedBudget,
    HacGated,
}

public sealed record MechanismConfig(
    string Id, string Label, MemoryWriteStrategy MemoryWrite, bool EndogenousState, bool DualGraphSeparation, bool IdentityConstraint, bool HacEnabled,
    bool DgmEnabled, bool CdiEnabled, string Focus);

public static class MechanismConfigs
{
    /// <summary>All pilot configurations in Table 3 order.</summary>
    public static IReadOnlyList<MechanismConfig> All { get; } =
    [
        new("B0", "无长期记忆", MemoryWriteStrategy.None, false, false, false, false, false, false, "无记忆下界"),
        new("B1", "滑动窗口", MemoryWriteStrategy.SlidingWindow, false, false, false, false, false, false, "窗口遗忘"),
        new("B2", "向量检索+全写入", MemoryWriteStrategy.VectorAllwrite, false, false, false, false, false, false, "无预算控制"),
        new("B3", "即时重要性阈值", MemoryWriteStrategy.ImportanceThreshold, false, false, false, false, false, false, "HAC 对照"),
        new("B4", "LLM 反思式记忆", MemoryWriteStrategy.LlmReflection, false, false, false, false, false, false, "反思式对照"),
        new("B5", "固定预算多类记忆", MemoryWriteStrategy.FixedBudget, false, false, false, false, false, false, "预算对照"),
        new("A1", "HAC 完整模型", MemoryWriteStrategy.HacGated, true, true, true, true, true, true, "完整模型"),
        new("A1-HAC", "A1 去除 HAC（回退固定预算）", MemoryWriteStrategy.FixedBudget, false, true, true, false, true, true, "去除 HAC 成分"),
        new("A1-DGM", "A1 去除 DGM（双图退化）", MemoryWriteStrategy.HacGated, true, false, true, true, false, true, "去除 DGM 成分"),
        new("A1-CDI", "A1 去除 CDI（静态人格）", MemoryWriteStrategy.HacGated, true, true, false, true, true, false, "去除 CDI 成分"),
    ];

    public static MechanismConfig Get(string id) => All.FirstOrDefault(c => c.Id == id) ?? throw new ArgumentException($"unknown mechanism config: {id}", nameof(id));
}
