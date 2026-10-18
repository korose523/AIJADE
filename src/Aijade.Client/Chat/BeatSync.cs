namespace Aijade.Client.Chat;

// Beat sync: the stage moves with the music the user is playing. The browser supplies the low-frequency energy of the
// audio (kick drum and bass) once per animation frame; this detector finds onsets against an adaptive threshold and
// estimates the tempo from the spacing of recent beats. Kept free of browser code so it can be tested with synthetic audio.

public sealed record BeatSyncParameters
{
    /// <summary>How far above the recent average (in standard deviations) energy must jump to count as a beat.</summary>
    public double Sensitivity { get; init; } = 1.5;

    /// <summary>Minimum time between beats (250 ms = 240 BPM).</summary>
    public double RefractoryMs { get; init; } = 250;

    /// <summary>Length of the energy history the threshold adapts to.</summary>
    public double WindowMs { get; init; } = 1000;

    /// <summary>Energy (0–255 scale of the analyser) below which nothing counts: silence and room noise.</summary>
    public double MinEnergy { get; init; } = 40;

    public double MinBpm { get; init; } = 60;

    public double MaxBpm { get; init; } = 200;
}

/// <summary>One detected beat: when, how pronounced (0–1), and the tempo estimate at that moment.</summary>
public sealed record Beat(double AtMs, double Strength, double? Bpm, double Confidence);

public sealed class BeatDetector(BeatSyncParameters? parameters = null)
{
    private const int IntervalHistory = 16;
    private readonly Queue<(double At, double Energy)> window = new();
    private readonly List<double> intervals = [];
    private double sum;
    private double sumSquares;
    private double? lastBeat;

    public BeatSyncParameters Parameters { get; } = parameters ?? new BeatSyncParameters();

    public double? Bpm { get; private set; }

    /// <summary>Share of recent beat intervals within 10 % of the tempo: near 1 for steady music, low for noise.</summary>
    public double Confidence { get; private set; }

    public int BeatCount { get; private set; }

    /// <summary>Feed one frame of low-band energy; returns the beat when this frame is one.</summary>
    public Beat? Feed(double atMs, double energy)
    {
        while (window.Count > 0 && window.Peek().At < atMs - Parameters.WindowMs)
        {
            var (_, old) = window.Dequeue();
            sum -= old;
            sumSquares -= old * old;
        }
        Beat? beat = null;
        if (window.Count >= 8)
        {
            var mean = sum / window.Count;
            var sd = Math.Sqrt(Math.Max(0, (sumSquares / window.Count) - (mean * mean)));
            var threshold = mean + (Parameters.Sensitivity * Math.Max(sd, 1));
            if (energy >= Parameters.MinEnergy && energy > threshold && (lastBeat is null || atMs - lastBeat >= Parameters.RefractoryMs))
            {
                if (lastBeat is { } previous)
                    AddInterval(atMs - previous);
                lastBeat = atMs;
                BeatCount++;
                beat = new Beat(atMs, Math.Clamp((energy - mean) / (4 * Math.Max(sd, 1)), 0, 1), Bpm, Confidence);
            }
        }
        window.Enqueue((atMs, energy));
        sum += energy;
        sumSquares += energy * energy;
        return beat;
    }

    private void AddInterval(double ms)
    {
        intervals.Add(ms);
        if (intervals.Count > IntervalHistory)
            intervals.RemoveAt(0);
        var sorted = intervals.Order().ToList();
        var median = sorted[sorted.Count / 2];
        // Fold into the musical range: a detector that catches every other beat (or every off-beat too) still reads right.
        var bpm = 60000 / median;
        while (bpm < Parameters.MinBpm)
            bpm *= 2;
        while (bpm > Parameters.MaxBpm)
            bpm /= 2;
        Bpm = intervals.Count >= 3 ? Math.Round(bpm, 1) : null;
        Confidence = intervals.Count(i => Math.Abs(i - median) <= median * 0.1) / (double)intervals.Count;
    }

    public void Reset()
    {
        window.Clear();
        intervals.Clear();
        sum = sumSquares = 0;
        lastBeat = null;
        Bpm = null;
        Confidence = 0;
        BeatCount = 0;
    }
}
