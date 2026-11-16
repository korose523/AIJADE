namespace Aijade.Research.MemoryEval;

/// <summary>
/// Per-conversation work on the thread pool. Each conversation builds its own store, so the work items share no mutable
/// state; results come back in input order, so every aggregate is summed in exactly the order of a sequential run and the
/// artefacts stay byte-identical.
/// </summary>
internal static class ParallelMap
{
    public static TOut[] Map<TIn, TOut>(IReadOnlyList<TIn> items, Func<TIn, int, TOut> f)
    {
        var results = new TOut[items.Count];
        Parallel.For(0, items.Count, i => results[i] = f(items[i], i));
        return results;
    }
}
