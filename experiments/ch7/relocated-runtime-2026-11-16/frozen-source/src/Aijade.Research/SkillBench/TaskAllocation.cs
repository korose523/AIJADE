using Aijade.Core.Random;

namespace Aijade.Research.SkillBench;

public static class TaskAllocation
{
    /// <summary>Repeated seeded permutation with a floor/ceiling exposure count for every task.</summary>
    public static IReadOnlyList<IReadOnlyList<BenchTask>> Balanced(
        IReadOnlyList<BenchTask> tasks, int trials, int slots, uint seed)
    {
        ArgumentNullException.ThrowIfNull(tasks);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(trials);
        if (slots <= 0 || slots > tasks.Count)
            throw new ArgumentOutOfRangeException(nameof(slots), "Slots must be positive and no larger than the pool.");
        if (tasks.Select(task => task.Id).Distinct(StringComparer.Ordinal).Count() != tasks.Count)
            throw new ArgumentException("Task identities must be unique.", nameof(tasks));
        var order = tasks.ToArray();
        var rng = new Mulberry32(seed);
        for (var i = 0; i < order.Length - 1; i++)
        {
            var j = i + (int)Math.Floor(rng.Next() * (order.Length - i));
            (order[i], order[j]) = (order[j], order[i]);
        }
        var result = new List<IReadOnlyList<BenchTask>>(trials);
        for (var trial = 0; trial < trials; trial++)
        {
            var row = new BenchTask[slots];
            for (var slot = 0; slot < slots; slot++)
                row[slot] = order[(int)(((long)trial * slots + slot) % order.Length)];
            result.Add(row);
        }
        return result;
    }
}
