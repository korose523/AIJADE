using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory;
using Aijade.Memory.Beliefs;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;

namespace Aijade.Growth.Services;

// §48 AEL: acquired sources are de-duplicated by shared origin, filtered to those that may count as independent
// evidence, graded into a claim confidence, folded into a Belief by one evidence transaction, and emitted as a ClaimMap
// whose claim names its support sources and is traced back to them through a small provenance graph.

/// <param name="Sources">The acquired sources.</param>
/// <param name="QuestRef">The quest the claim map belongs to.</param>
/// <param name="Proposition">The proposition verified (defaults to a synthesised label).</param>
/// <param name="LikelihoodPerSource">Likelihood contributed by each supporting source (default 1).</param>
public sealed record VerifyInput(IReadOnlyList<SourceRecord> Sources, string QuestRef, string? Proposition = null, double? LikelihoodPerSource = null);

/// <param name="ClaimMap">The emitted claim map.</param>
/// <param name="Belief">The belief after the evidence transaction.</param>
/// <param name="OriginClusters">Raw shared-origin cluster count.</param>
/// <param name="IndependentOriginCount">Independent-origin count (de-duplicated).</param>
/// <param name="EffectiveIndependentCount">Sources left after the independent-evidence filter.</param>
/// <param name="Confidence">Claim confidence in [0, 1].</param>
/// <param name="TraceChain">Provenance chain from the belief back through its sources.</param>
public sealed record VerifyResult(
    ClaimMap ClaimMap, Belief Belief, int OriginClusters, int IndependentOriginCount, int EffectiveIndependentCount, double Confidence,
    IReadOnlyList<ProvenanceNode> TraceChain);

public sealed class EpistemicVerifier(GrowthPorts ports, string agentId, string userScope)
{
    public const string ClaimKind = "claim_map";
    public const string BeliefKind = "belief";

    public static ContentOrigin OriginOf(string sourceType) => sourceType switch
    {
        "model" => ContentOrigin.Model,
        "tool" => ContentOrigin.Tool,
        "user" => ContentOrigin.User,
        "system" => ContentOrigin.System,
        _ => ContentOrigin.Web,
    };

    public async Task<VerifyResult> VerifyAsync(VerifyInput input, CancellationToken cancellationToken = default)
    {
        var sources = input.Sources;
        var clusters = Ael.SharedOriginClusters(sources);
        var indCount = Ael.IndependentOriginCount(sources);

        var credible = sources.Where(s =>
        {
            var origin = OriginOf(s.SourceType);
            return Ael.CanBeIndependentEvidence(origin, origin == ContentOrigin.Model);
        }).ToList();
        var credibleIds = credible.Select(s => s.Id).ToList();
        // At least one support ref, so the claim passes the §6 traceability gate.
        var supportRefs = credibleIds.Count > 0 ? credibleIds : sources.Select(s => s.Id).ToList();

        var agg = credible.Count > 0 ? credible : [.. sources];
        var n = agg.Count == 0 ? 1 : agg.Count;
        double rel = 0, ind = 0, dir = 0, rec = 0, rep = 0;
        foreach (var s in agg)
        {
            rel += s.Quality.Reliability;
            ind += s.Quality.Independence;
            dir += s.Quality.Directness;
            rec += s.Quality.Recency;
            rep += s.Quality.Reproducibility;
        }
        var confidence = Ael.EvidenceConfidence(new EvidenceQualities(rel / n, ind / n, dir / n, rec / n, rep / n, 0));

        var beliefId = ports.IdGen.NewId("b");
        var lk = input.LikelihoodPerSource ?? 1.0;
        var evidence = supportRefs.Select(id => new EvidenceEntry(id, sources.FirstOrDefault(s => s.Id == id)?.Quality.Reliability ?? 0.5, lk)).ToList();
        var belief = BeliefMath.Create(beliefId, input.Proposition ?? $"claim derived from {supportRefs.Count} source(s)", supportRefs,
            ports.Scheduler.Now(), BeliefConfig.Default);
        belief = BeliefMath.Apply(belief, ports.IdGen.NewId("rev"), ports.Scheduler.Now(), agentId, BeliefConfig.Default, evidence).Belief;

        var nodes = sources.Select(s => new ProvenanceNode(s.Id, ProvenanceKind.Episode, $"Source: {s.Locator}",
            new JsonObject { ["sourceType"] = s.SourceType, ["contentHash"] = s.ContentHash })).ToList();
        nodes.Add(new ProvenanceNode(belief.Id, ProvenanceKind.Belief, $"Belief: {belief.Proposition}", new JsonObject
        {
            ["proposition"] = belief.Proposition,
            ["status"] = WireName.Of(belief.Status),
            ["confidence"] = belief.Confidence,
        }));
        var edges = supportRefs.Select(id => new ProvenanceEdge(belief.Id, id, "evidenced-by")).ToList();
        var traceChain = Provenance.Trace(new ProvenanceGraph(nodes, edges), belief.Id);

        var claimMap = new ClaimMap(ports.IdGen.NewId("cm"), agentId, userScope, input.QuestRef,
            [new Claim(input.Proposition ?? $"derived claim over {supportRefs.Count} source(s)", "inference", supportRefs, [], confidence)],
            ports.Scheduler.Now());
        var check = ContractValidationV8.Validate(claimMap);
        if (!check.Ok)
            throw new InvalidOperationException($"ClaimMap rejected: {check.Reason}");

        await ports.Storage.PutAsync(ClaimKind, claimMap.Id, claimMap, cancellationToken).ConfigureAwait(false);
        await ports.Storage.PutAsync(BeliefKind, belief.Id, belief, cancellationToken).ConfigureAwait(false);
        return new VerifyResult(claimMap, belief, clusters.Count, indCount, credibleIds.Count, confidence, traceChain);
    }
}
