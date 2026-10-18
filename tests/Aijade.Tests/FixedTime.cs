namespace Aijade.Tests;

/// <summary>A clock frozen at a Unix-millisecond instant, for byte-exact comparisons with recorded output.</summary>
internal sealed class FixedTime(long unixMs) : TimeProvider
{
    public override DateTimeOffset GetUtcNow() => DateTimeOffset.FromUnixTimeMilliseconds(unixMs);
}

/// <summary>A clock that moves only when told to.</summary>
internal sealed class ManualTime(long unixMs) : TimeProvider
{
    private long now = unixMs;

    public override DateTimeOffset GetUtcNow() => DateTimeOffset.FromUnixTimeMilliseconds(Interlocked.Read(ref now));

    public void Advance(TimeSpan by) => Interlocked.Add(ref now, (long)by.TotalMilliseconds);
}
