using Aijade.Growth.Pilot;

namespace Aijade.Growth.Metrics;

// §5.4 identity / persona-constitution metrics, giving the CDI ablation a dedicated, falsifiable target. Pure functions
// over counts from the genuinely committed memory set, never from a config flag.

/// <param name="CommittedTotal">Committed memory entries.</param>
/// <param name="Destabilizing">Committed identity-destabilising entries (high-emotion, low-fact).</param>
/// <param name="CorePersona">Committed persona-core entries.</param>
/// <param name="RetainedSkills">Committed rare-skill entries.</param>
/// <param name="TotalSkills">Rare-skill statements the dataset presented (filled by the caller).</param>
public sealed record IdentityCounts(int CommittedTotal, int Destabilizing, int CorePersona, int RetainedSkills, int TotalSkills = 0);

public static class IdentityMetrics
{
    public static IdentityCounts Count(IEnumerable<MemoryMeta> committed)
    {
        int total = 0, destabilizing = 0, core = 0, skills = 0;
        foreach (var m in committed)
        {
            total++;
            if (m.Role is { } role && MemoryPolicies.DestabilizingRoles.Contains(role))
                destabilizing++;
            if (m.Role is { } r && MemoryPolicies.CorePersonaRoles.Contains(r))
                core++;
            if (m.Role == "lowfreq_highvalue")
                skills++;
        }
        return new IdentityCounts(total, destabilizing, core, skills);
    }

    /// <summary>ID = destabilizing / committed (0 when empty): the share of out-of-bounds drift in consolidated memory.</summary>
    public static double IdentityDrift(IdentityCounts c) => c.CommittedTotal <= 0 ? 0 : (double)c.Destabilizing / c.CommittedTotal;

    /// <summary>CS = max(0, 1 − destabilizing / core persona); 1 when there is no persona core.</summary>
    public static double CoreStability(IdentityCounts c) => c.CorePersona <= 0 ? 1 : Math.Max(0, 1 - ((double)c.Destabilizing / c.CorePersona));

    /// <summary>SR = retained rare skills / presented rare skills (0 when none were presented).</summary>
    public static double SkillRetention(IdentityCounts c) => c.TotalSkills <= 0 ? 0 : (double)c.RetainedSkills / c.TotalSkills;
}
