using Aijade.Memory.Contracts;

namespace Aijade.Growth.Services;

// §50.1: a deterministic V_share from eight utility components (five lift it, three cost it), then one of four channels.
// A full share needs the high threshold and a non-quiet hour; otherwise the decision degrades (light hint, next chat,
// diary) so the agent never over-shares.

public sealed record ShareDecision(ShareCandidate Candidate, bool Quiet);

public sealed class SharingPolicy(GrowthPorts ports, string agentId, string userScope)
{
    public const string Kind = "share_candidate";
    private const double FullShare = 0.6;
    private const double LightHint = 0.35;
    private const double NextChat = 0.15;

    /// <summary>V_share = clamp01(Σ positive weights · value − Σ negative weights · cost); each weight set sums to 1.</summary>
    public static double ComputeShareScore(ShareUtility u)
    {
        var pos = (0.25 * u.Relevance) + (0.2 * u.Novelty) + (0.2 * u.RelationalValue) + (0.15 * u.Timeliness) + (0.2 * u.Uncertainty);
        var neg = (0.4 * u.Interruption) + (0.4 * u.PrivacyRisk) + (0.2 * u.Repetition);
        return Math.Min(1, Math.Max(0, pos - neg));
    }

    /// <summary>Quiet hours: 23:00–07:00 local, when the agent should not actively broadcast.</summary>
    public static bool IsQuietHour(double nowMs, TimeZoneInfo? zone = null)
    {
        var hour = GrowthUtil.LocalHour(nowMs, zone);
        return hour >= 23 || hour < 7;
    }

    public async Task<ShareDecision> ScoreShareAsync(string contentRef, ShareUtility utility, CancellationToken cancellationToken = default)
    {
        var score = ComputeShareScore(utility);
        var now = ports.Scheduler.Now();
        var quiet = IsQuietHour(now, ports.Zone);
        var channel = score >= FullShare && !quiet ? "full_share"
            : score >= LightHint && !quiet ? "light_hint"
            : score >= NextChat ? "next_chat"
            : "diary";
        var candidate = new ShareCandidate(ports.IdGen.NewId("sc"), agentId, userScope, contentRef, utility, score, channel, now);
        var check = ContractValidationV8.Validate(candidate);
        if (!check.Ok)
            throw new InvalidOperationException($"ShareCandidate rejected: {check.Reason}");
        await ports.Storage.PutAsync(Kind, candidate.Id, candidate, cancellationToken).ConfigureAwait(false);
        return new ShareDecision(candidate, quiet);
    }
}
