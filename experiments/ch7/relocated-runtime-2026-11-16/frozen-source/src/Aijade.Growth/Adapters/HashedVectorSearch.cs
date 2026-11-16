using System.Text;

using Aijade.Core.Js;

namespace Aijade.Growth.Adapters;

// The retrieval port over a local corpus, an independent, dependency-free design: each document is embedded as a signed hashed bag of lower-cased word tokens and character trigrams (L2-normalised),
// a query is ranked by cosine similarity within the requested scopes (scope = source type), and ties keep corpus order.

/// <param name="Locator">Where the document lives (absolute path for a directory corpus).</param>
/// <param name="SourceType">Its source type, which is also its retrieval scope.</param>
/// <param name="Content">The document text.</param>
public sealed record CorpusItem(string Locator, string SourceType, string Content);

public sealed class HashedVectorSearch : ISearchPort
{
    public const int Dimensions = 512;

    private sealed record Entry(CorpusItem Item, float[] Vector);

    private readonly List<Entry> entries = [];
    private readonly int limit;
    private readonly double minSimilarity;
    private readonly TimeProvider time;
    private readonly Lock gate = new();

    /// <param name="corpus">Documents to seed.</param>
    /// <param name="searchDir">A directory of .md / .txt / .json files to seed (non-recursive).</param>
    /// <param name="limit">Maximum hits per search (default 8).</param>
    /// <param name="minSimilarity">Minimum cosine similarity for a hit (default: any positive similarity).</param>
    /// <param name="time">Clock stamped on hits.</param>
    public HashedVectorSearch(IEnumerable<CorpusItem>? corpus = null, string? searchDir = null, int limit = 8, double? minSimilarity = null, TimeProvider? time = null)
    {
        this.limit = limit;
        this.minSimilarity = minSimilarity ?? double.Epsilon;
        this.time = time ?? TimeProvider.System;
        if (searchDir is not null)
            SeedAll(CorpusFromDirectory(searchDir));
        if (corpus is not null)
            SeedAll(corpus);
    }

    /// <summary>The .md / .txt / .json files directly under <paramref name="dir"/>, in ordinal name order; empty files skipped.</summary>
    public static IReadOnlyList<CorpusItem> CorpusFromDirectory(string dir)
    {
        if (!Directory.Exists(dir))
            return [];
        var items = new List<CorpusItem>();
        foreach (var full in Directory.EnumerateFiles(dir).Order(StringComparer.Ordinal))
        {
            var lower = Path.GetFileName(full).ToLowerInvariant();
            var json = lower.EndsWith(".json", StringComparison.Ordinal);
            if (!json && !lower.EndsWith(".md", StringComparison.Ordinal) && !lower.EndsWith(".txt", StringComparison.Ordinal))
                continue;
            try
            {
                var content = JsText.Trim(File.ReadAllText(full));
                if (content.Length > 0)
                    items.Add(new CorpusItem(Path.GetFullPath(full), json ? "data" : "doc", content));
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException)
            {
                // Skip unreadable files.
            }
        }
        return items;
    }

    public int Count
    {
        get
        {
            lock (gate)
                return entries.Count;
        }
    }

    public void Seed(CorpusItem item)
    {
        var v = Embed(item.Content);
        lock (gate)
            entries.Add(new Entry(item, v));
    }

    private void SeedAll(IEnumerable<CorpusItem> items)
    {
        foreach (var it in items)
            Seed(it);
    }

    public Task<IReadOnlyList<RawHit>> SearchAsync(string query, IReadOnlyList<string> sourceTypes, CancellationToken cancellationToken = default)
    {
        var q = Embed(query);
        var scopes = sourceTypes.ToHashSet(StringComparer.Ordinal);
        List<Entry> snapshot;
        lock (gate)
            snapshot = [.. entries];
        var now = time.GetUtcNow().ToUnixTimeMilliseconds();
        IReadOnlyList<RawHit> hits = snapshot
            .Select((e, i) => (e, i, score: Dot(q, e.Vector)))
            .Where(x => (scopes.Count == 0 || scopes.Contains(x.e.Item.SourceType)) && x.score >= minSimilarity)
            .OrderByDescending(x => x.score).ThenBy(x => x.i)
            .Take(limit)
            .Select(x => new RawHit(x.e.Item.Locator, x.e.Item.SourceType, x.e.Item.Content, now))
            .ToList();
        return Task.FromResult(hits);
    }

    /// <summary>Signed feature hashing of word tokens and character trigrams, L2-normalised (a zero vector for empty text).</summary>
    public static float[] Embed(string text)
    {
        var v = new float[Dimensions];
        var lower = JsText.Lower(text);
        foreach (var token in JsText.SplitOnSpace(lower).Where(t => t.Length > 0))
        {
            Add(v, "w:" + token, 1f);
            var padded = $" {token} ";
            for (var i = 0; i + 3 <= padded.Length; i++)
                Add(v, string.Concat("c:", padded.AsSpan(i, 3)), 0.5f);
        }
        var norm = Math.Sqrt(v.Sum(x => (double)x * x));
        if (norm > 0)
        {
            for (var i = 0; i < v.Length; i++)
                v[i] = (float)(v[i] / norm);
        }
        return v;
    }

    private static void Add(float[] v, string feature, float weight)
    {
        var h = 2166136261u;
        foreach (var b in Encoding.UTF8.GetBytes(feature))
            h = unchecked((h ^ b) * 16777619u);
        v[h % Dimensions] += (h & 0x80000000u) != 0 ? -weight : weight;
    }

    private static double Dot(float[] a, float[] b)
    {
        double s = 0;
        for (var i = 0; i < a.Length; i++)
            s += a[i] * b[i];
        return s;
    }
}
