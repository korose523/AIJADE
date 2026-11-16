namespace Aijade.Core.Random;

/// <summary>
/// Mulberry32: a small seedable PRNG. Bit-identical to the JavaScript implementation the earlier experiments used
/// (Math.imul / &gt;&gt;&gt; 0 arithmetic), so seeded results reproduce across the two implementations.
/// </summary>
public sealed class Mulberry32(uint seed)
{
    private uint _a = seed;

    public double Next()
    {
        unchecked
        {
            _a += 0x6D2B79F5;
            var t = (_a ^ (_a >> 15)) * (1 | _a);
            t = (t + ((t ^ (t >> 7)) * (61 | t))) ^ t;
            return (t ^ (t >> 14)) / 4294967296.0;
        }
    }

    /// <summary>The generator as a function, for APIs that take a <c>Func&lt;double&gt;</c>.</summary>
    public Func<double> AsFunc() => Next;
}
