namespace Aijade.Memory.Kernel;


/// <summary>v10 endogenous state nodes S0..S8.</summary>
public enum CoreStateNode
{
    S0,
    S1,
    S2,
    S3,
    S4,
    S5,
    S6,
    S7,
    S8,
}

public static class CoreStateNodes
{
    /// <summary>
    /// Map an event topic plus real control-flow facts to its node. Deterministic, so the replay side can recompute it and
    /// detect drift. S8 ("actually persisted") appears only when a memory version was written; otherwise the commit
    /// stays at S6. S5 is reached whatever the PGC verdict was.
    /// </summary>
    public static CoreStateNode Derive(string topic, bool hasMemoryVersion = false)
    {
        if (topic.StartsWith("aijade.video.", StringComparison.Ordinal))
            return CoreStateNode.S2;
        if (topic.StartsWith("aijade.learning.proposed.", StringComparison.Ordinal))
            return CoreStateNode.S3;
        if (topic == "aijade.pgc.write_plan_ready")
            return CoreStateNode.S5;
        if (topic == "aijade.memory_tx.committed")
            return hasMemoryVersion ? CoreStateNode.S8 : CoreStateNode.S6;
        if (topic == "aijade.evidence.weave_candidate_ready")
            return CoreStateNode.S7;
        if (topic.StartsWith("aijade.evidence.", StringComparison.Ordinal))
            return CoreStateNode.S4;
        if (topic.StartsWith("aijade.active_learning.", StringComparison.Ordinal))
            return CoreStateNode.S1;
        return CoreStateNode.S0;
    }
}
