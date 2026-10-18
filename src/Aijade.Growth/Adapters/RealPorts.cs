namespace Aijade.Growth.Adapters;

// A production port bundle with graceful degradation: durable file storage under <dataDir>/storage, corpus retrieval,
// HMAC-SHA256 signing, the wall clock with a persistent token-bucket ledger, and an Ollama / OpenAI-compatible LLM.
// File storage is the real store of the growth services.

/// <param name="DataDir">Root for file storage and the scheduler ledger (default AIJADE_DATA_DIR, else the temp directory).</param>
/// <param name="SigningSecret">Signing secret (default AIJADE_SIGNING_SECRET).</param>
/// <param name="Http">HTTP client for the LLM adapter.</param>
/// <param name="LlmBaseUrl">LLM endpoint override.</param>
/// <param name="LlmModel">LLM model override.</param>
/// <param name="StubLlm">Use the deterministic stub LLM (tests / offline).</param>
/// <param name="LlmInstance">A pre-built LLM port (overrides the other LLM options).</param>
/// <param name="Budgets">Per-scope budgets (default: growth_loop, 50 per hour).</param>
/// <param name="SearchCorpus">Corpus to seed retrieval with.</param>
/// <param name="SearchDir">A directory of documents to seed retrieval with.</param>
public sealed record RealPortsOptions(
    string? DataDir = null, string? SigningSecret = null, HttpClient? Http = null, string? LlmBaseUrl = null, string? LlmModel = null,
    bool StubLlm = false, ILlmPort? LlmInstance = null, IReadOnlyDictionary<string, BudgetPolicy>? Budgets = null,
    IReadOnlyList<CorpusItem>? SearchCorpus = null, string? SearchDir = null);

public static class RealPorts
{
    public static GrowthPorts Create(RealPortsOptions? options = null)
    {
        var o = options ?? new RealPortsOptions();
        var dataDir = o.DataDir ?? Environment.GetEnvironmentVariable("AIJADE_DATA_DIR") ?? Path.Combine(Path.GetTempPath(), "aijade-growth");
        var storage = new FileStorageAdapter(Path.Combine(dataDir, "storage"));
        var search = new HashedVectorSearch(o.SearchCorpus, o.SearchDir);
        var signing = new CryptoSigningAdapter(o.SigningSecret);
        var scheduler = new SystemSchedulerAdapter(
            o.Budgets ?? new Dictionary<string, BudgetPolicy> { ["growth_loop"] = new(50, 50.0 / 3600) },
            Path.Combine(dataDir, "scheduler-ledger.json"));
        var llm = o.LlmInstance ?? (o.StubLlm
            ? new StubLlm()
            : ChatLlmAdapter.CreateDefault(o.Http ?? throw new ArgumentException("an HttpClient is required for the real LLM adapter", nameof(options)), o.LlmBaseUrl, o.LlmModel));
        return new GrowthPorts(storage, scheduler, search, signing, llm);
    }

    public static GrowthLoop CreateGrowthLoop(RealPortsOptions options, string agentId, string userScope) => new(Create(options), agentId, userScope);
}
