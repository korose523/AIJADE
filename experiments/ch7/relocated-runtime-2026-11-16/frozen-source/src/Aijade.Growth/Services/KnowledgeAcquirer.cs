using Aijade.Memory.Contracts;

namespace Aijade.Growth.Services;

// §48 AEL: raw, untrusted search hits are quarantined into persisted SourceRecords (content hash to de-duplicate
// reposts, default quality dimensions, empty upstream lineage). With an LLM port, the hits are also distilled into a
// brief persisted as an extra llm_brief record whose lineage names every hit it was built from.

/// <param name="Query">Search query.</param>
/// <param name="SourceTypes">Restrict the search to these source types.</param>
/// <param name="MaxSources">Cap on how many hits become records.</param>
/// <param name="Quality">Quality dimensions for every hit (default <see cref="KnowledgeAcquirer.DefaultQuality"/>).</param>
/// <param name="TrustedTypes">Source types marked licence "trusted".</param>
/// <param name="UseLlmBrief">Ask the LLM port (when injected) for a brief over the hits.</param>
public sealed record AcquireInput(
    string Query, IReadOnlyList<string>? SourceTypes = null, int? MaxSources = null, SourceQuality? Quality = null,
    IReadOnlyList<string>? TrustedTypes = null, bool UseLlmBrief = false);

public sealed class KnowledgeAcquirer(GrowthPorts ports)
{
    public const string Kind = "source_record";

    /// <summary>Default quality dimensions of a freshly acquired source.</summary>
    public static SourceQuality DefaultQuality { get; } = new(0.6, 0.7, 0.6, 0.7, 0.5);

    private static SourceRecord Checked(SourceRecord r, string what)
    {
        var check = ContractValidationV8.Validate(r);
        return check.Ok ? r : throw new InvalidOperationException($"{what} rejected: {check.Reason}");
    }

    public async Task<IReadOnlyList<SourceRecord>> AcquireAsync(AcquireInput input, CancellationToken cancellationToken = default)
    {
        var hits = await ports.RequireSearch.SearchAsync(input.Query, input.SourceTypes ?? [], cancellationToken).ConfigureAwait(false);
        var cap = input.MaxSources ?? hits.Count;
        var quality = input.Quality ?? DefaultQuality;
        var trusted = (input.TrustedTypes ?? []).ToHashSet(StringComparer.Ordinal);
        var records = new List<SourceRecord>();
        foreach (var hit in hits.Take(Math.Max(0, cap)))
        {
            var record = Checked(new SourceRecord(
                ports.IdGen.NewId("src"), hit.Locator, hit.SourceType, quality, [], GrowthUtil.ContentHashOf(hit.Content), ports.Scheduler.Now(),
                trusted.Contains(hit.SourceType) ? "trusted" : null), "SourceRecord");
            await ports.Storage.PutAsync(Kind, record.Id, record, cancellationToken).ConfigureAwait(false);
            records.Add(record);
        }

        if (records.Count > 0 && input.UseLlmBrief && ports.Llm is { } llm)
        {
            var brief = await llm.CompleteAsync(BuildBriefPrompt(input.Query, records), cancellationToken).ConfigureAwait(false);
            var briefId = ports.IdGen.NewId("llm");
            var briefRecord = Checked(new SourceRecord(
                briefId, $"aijade://llm-brief/{briefId}", "llm_brief", quality, records.Select(r => r.Id).ToList(), GrowthUtil.ContentHashOf(brief),
                ports.Scheduler.Now()), "LLM brief SourceRecord");
            await ports.Storage.PutAsync(Kind, briefRecord.Id, briefRecord, cancellationToken).ConfigureAwait(false);
            records.Add(briefRecord);
        }
        return records;
    }

    public Task<SourceRecord?> GetAsync(string id, CancellationToken cancellationToken = default) =>
        ports.Storage.GetAsync<SourceRecord>(Kind, id, cancellationToken);

    public Task<IReadOnlyList<SourceRecord>> ListAsync(CancellationToken cancellationToken = default) =>
        ports.Storage.QueryAsync<SourceRecord>(Kind, _ => true, cancellationToken);

    /// <summary>The brief prompt: a concise factual synthesis of the retrieved sources, inventing none.</summary>
    public static string BuildBriefPrompt(string question, IReadOnlyList<SourceRecord> records)
    {
        var bullets = string.Join("\n", records.Where(r => r.SourceType != "llm_brief").Select(r => $"- ({r.SourceType}) {r.ContentHash}: see {r.Locator}"));
        return string.Join("\n",
            "You are AIJADE's knowledge acquirer. Given the research question and the",
            "retrieved raw sources, write a concise factual brief (3-5 sentences) that",
            "captures the key verified points. Do not invent sources or claims.",
            "",
            $"Research question: {question}",
            "",
            "Retrieved sources:",
            bullets.Length > 0 ? bullets : "(none)");
    }
}
