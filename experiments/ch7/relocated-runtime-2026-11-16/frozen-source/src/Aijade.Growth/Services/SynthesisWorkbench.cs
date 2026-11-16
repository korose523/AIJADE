using System.Text.Json.Nodes;

using Aijade.Memory.Contracts;
using Aijade.Memory.Development;

namespace Aijade.Growth.Services;

// §48.6: a quest, its source records and a synthesised payload become a KnowledgeArtifact whose sources come from the
// records (§6 traceability) and whose evidence-graph ref encodes the de-duplicated independent-origin count.

/// <param name="QuestRef">The quest the artefact answers.</param>
/// <param name="Kind">Artefact kind (learning_note, …).</param>
/// <param name="Payload">The synthesised payload.</param>
/// <param name="SourceRecords">Backing sources; at least one.</param>
/// <param name="TrustedTypes">Source types marked trusted.</param>
public sealed record SynthesizeInput(string QuestRef, string Kind, JsonNode? Payload, IReadOnlyList<SourceRecord> SourceRecords, IReadOnlyList<string>? TrustedTypes = null);

public sealed class SynthesisWorkbench(GrowthPorts ports, string agentId, string userScope)
{
    public const string Kind = "knowledge_artifact";

    public async Task<KnowledgeArtifact> SynthesizeAsync(SynthesizeInput input, CancellationToken cancellationToken = default)
    {
        if (input.SourceRecords.Count == 0)
            throw new InvalidOperationException("KnowledgeArtifact requires ≥1 source (v7 §6)");
        var trusted = (input.TrustedTypes ?? []).ToHashSet(StringComparer.Ordinal);
        var sources = input.SourceRecords.Select(s => new SourceRef(s.Id, trusted.Contains(s.SourceType))).ToList();
        var indep = Ael.IndependentOriginCount(input.SourceRecords);
        var evidenceGraphRef = $"evg:indep={indep}:{string.Join(",", input.SourceRecords.Select(s => s.Id))}";
        var artifact = new KnowledgeArtifact(ports.IdGen.NewId("ka"), agentId, userScope, input.Kind, input.QuestRef, input.Payload, evidenceGraphRef,
            sources, ports.Scheduler.Now());
        var check = ContractValidationV8.Validate(artifact);
        if (!check.Ok)
            throw new InvalidOperationException($"KnowledgeArtifact rejected: {check.Reason}");
        await ports.Storage.PutAsync(Kind, artifact.Id, artifact, cancellationToken).ConfigureAwait(false);
        return artifact;
    }

    public Task<KnowledgeArtifact?> GetAsync(string id, CancellationToken cancellationToken = default) =>
        ports.Storage.GetAsync<KnowledgeArtifact>(Kind, id, cancellationToken);
}
