using Aijade.Memory.Model;
using Aijade.Core.Js;

namespace Aijade.Memory;


/// <summary>
/// The minimal LLM surface the memory kernel needs. An adapter over the model substrate implements it, so the kernel
/// keeps no model dependency. The dynamics experiments never need an LLM: <see cref="LexicalDistiller"/> is the default.
/// </summary>
public interface ILlmClient
{
    Task<string> GenerateAsync(string prompt, double temperature, int? maxTokens = null, CancellationToken cancellationToken = default);
}

/// <summary>A distiller that may call a model.</summary>
public interface IAsyncDistiller
{
    Task<IReadOnlyList<SemanticFact>> DistillAsync(IReadOnlyList<Episode> episodes, CancellationToken cancellationToken = default);
}

/// <summary>
/// LLM-backed distillation, one statement per line. Episodes the model leaves without a line keep their lexical form, and a
/// failed call falls back entirely, so a partial model failure never breaks consolidation.
/// </summary>
public sealed class LlmDistiller(ILlmClient client) : IAsyncDistiller
{
    private readonly LexicalDistiller _lexical = new();

    internal static string Prompt(IReadOnlyList<Episode> episodes) => string.Join("\n",
        "Distil the following conversation excerpts into concise, self-contained factual statements.",
        "Preserve names, dates, and relationships exactly. One statement per line.",
        "",
        string.Join("\n", episodes.Select(e => $"- {e.Content}")));

    public async Task<IReadOnlyList<SemanticFact>> DistillAsync(IReadOnlyList<Episode> episodes, CancellationToken cancellationToken = default)
    {
        var lexical = _lexical.Distill(episodes);
        string output;
        try
        {
            output = await client.GenerateAsync(Prompt(episodes), 0, 512, cancellationToken).ConfigureAwait(false);
        }
#pragma warning disable CA1031 // Any model failure falls back to the lexical facts.
        catch (Exception) when (!cancellationToken.IsCancellationRequested)
#pragma warning restore CA1031
        {
            return lexical;
        }
        var lines = output.Split('\n').Select(JsText.Trim).Where(l => l.Length > 0).ToList();
        if (lines.Count == 0)
            return lexical;
        return episodes.Select((e, i) => CopyWithContent(lexical[i], i < lines.Count ? lines[i] : e.Content)).ToList();
    }

    private static SemanticFact CopyWithContent(SemanticFact f, string content) => new()
    {
        Id = f.Id,
        Content = content,
        DerivedFrom = f.DerivedFrom,
        CreatedAt = f.CreatedAt,
        LastAccessedAt = f.LastAccessedAt,
        AccessCount = f.AccessCount,
        Confidence = f.Confidence,
        BaseStrength = f.BaseStrength,
        Durability = f.Durability,
        ContextTags = f.ContextTags,
        Salience = f.Salience,
        Affect = f.Affect,
        MemoryType = f.MemoryType,
        Status = f.Status,
        ValidTime = f.ValidTime,
    };
}
