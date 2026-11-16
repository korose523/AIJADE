namespace Aijade.Client.Companion;

/// <summary>One character of a spoken reply as MOSAIC's align server times it: start and end in seconds, strict pinyin initial and final.</summary>
public sealed record AlignedCharacter(string Character, double StartS, double EndS, string Initial, string Final);

/// <summary>A reply's alignment: the length of its audio and its timed Chinese characters, in order.</summary>
public sealed record SpeechAlignment(double DurationS, IReadOnlyList<AlignedCharacter> Characters);

/// <summary>A lip closure from <see cref="Frame"/> on (0 opens the lips again).</summary>
public readonly record struct LipClosure(int Frame, double Value);

/// <summary>
/// What the stage plays beside the audio: per frame of <see cref="FrameHz"/> the vowel shape weights (a, i, u, e, o; null
/// outside the timed characters) and the lip closures. Frame k takes effect at (k + 1) / FrameHz seconds into the audio, as
/// MOSAIC's behaviour plan times its events.
/// </summary>
public sealed record LipSyncPlan(int FrameHz, IReadOnlyList<double[]?> Vowels, IReadOnlyList<LipClosure> Lips);

/// <summary>
/// The mouth from the text (ADR-003, migration batch 1): MOSAIC's aligned tracks (tools/behavior_plan_from_audio.py),
/// ported case by case against the vectors its own module made (configs/companion/viseme-vectors.json). Each pinyin final
/// is a short sequence of vowel shapes (a medial glide, the nucleus, an off-glide), smoothed over three frames, and b/p/m
/// close the lips (f half) at the start of their syllable. The stage splits the speech level across あいうえお by these
/// weights and shows ん for a closure, as MOSAIC's renderer client does.
/// </summary>
public static class LipSync
{
    public const int FrameHz = 60;
    public const double ClosureBeforeS = .03, ClosureAfterS = .05;

    /// <summary>Vowel shapes per strict pinyin final, in order, with their share of the syllable; several vowels in one shape mix equally.</summary>
    public static IReadOnlyDictionary<string, (string Vowels, double Share)[]> FinalShapes { get; } = new Dictionary<string, (string, double)[]>(StringComparer.Ordinal)
    {
        ["a"] = [("a", 1)], ["o"] = [("o", 1)], ["e"] = [("e", 1)], ["i"] = [("i", 1)], ["u"] = [("u", 1)], ["v"] = [("ui", 1)], ["er"] = [("ae", 1)],
        ["ai"] = [("a", .6), ("i", .4)], ["ei"] = [("e", .6), ("i", .4)], ["ao"] = [("a", .6), ("o", .4)], ["ou"] = [("o", .6), ("u", .4)],
        ["an"] = [("a", 1)], ["en"] = [("e", 1)], ["ang"] = [("a", 1)], ["eng"] = [("e", 1)], ["ong"] = [("o", 1)],
        ["ia"] = [("i", .3), ("a", .7)], ["ie"] = [("i", .3), ("e", .7)], ["iao"] = [("i", .25), ("a", .45), ("o", .3)], ["iou"] = [("i", .25), ("o", .45), ("u", .3)],
        ["ian"] = [("i", .3), ("e", .7)], ["in"] = [("i", 1)], ["iang"] = [("i", .3), ("a", .7)], ["ing"] = [("i", 1)], ["iong"] = [("i", .3), ("o", .7)],
        ["ua"] = [("u", .3), ("a", .7)], ["uo"] = [("u", .3), ("o", .7)], ["uai"] = [("u", .25), ("a", .45), ("i", .3)], ["uei"] = [("u", .25), ("e", .45), ("i", .3)],
        ["uan"] = [("u", .3), ("a", .7)], ["uen"] = [("u", .3), ("e", .7)], ["uang"] = [("u", .3), ("a", .7)], ["ueng"] = [("u", .3), ("e", .7)],
        ["ve"] = [("ui", .3), ("e", .7)], ["van"] = [("ui", .3), ("e", .7)], ["vn"] = [("ui", 1)],
    };

    /// <summary>Closure strength at the start of the syllable.</summary>
    public static IReadOnlyDictionary<string, double> LipInitials { get; } = new Dictionary<string, double>(StringComparer.Ordinal) { ["b"] = 1, ["p"] = 1, ["m"] = 1, ["f"] = .5 };

    public static double[] ShapeWeights(string vowels)
    {
        var w = new double[5];
        foreach (var v in vowels)
            w["aiueo".IndexOf(v, StringComparison.Ordinal)] += 1.0 / vowels.Length;
        return w;
    }

    /// <summary>The plan for audio of <paramref name="frames"/> frames; characters past its end are cut off.</summary>
    public static LipSyncPlan Plan(IReadOnlyList<AlignedCharacter> rows, int frames)
    {
        var track = new double[frames][];
        var lips = new List<LipClosure>();
        var prevMid = 0.0;
        foreach (var r in rows)
        {
            var (start, end) = (r.StartS, r.EndS);
            if (!(start >= 0) || !(end > start))
                continue; // not a timed character (the align server never returns one)
            var shapes = FinalShapes.GetValueOrDefault(r.Final);
            int lo = (int)(start * FrameHz), hi = Math.Min(frames, Math.Max((int)(start * FrameHz) + 1, (int)Math.Round(end * FrameHz)));
            var at = lo;
            foreach (var shape in shapes ?? [])
            {
                var stop = shape != shapes![^1] ? Math.Min(hi, at + Math.Max(1, (int)Math.Round(shape.Share * (hi - lo)))) : hi;
                for (var k = at; k < stop; k++)
                    track[k] = ShapeWeights(shape.Vowels);
                at = stop;
            }
            var strength = LipInitials.GetValueOrDefault(r.Initial) is > 0 and var s ? s : shapes is null && r.Initial.Length == 0 ? .5 : 0;
            if (strength > 0 && start * FrameHz < frames)
            {
                var a = (int)Math.Round(Math.Max(start - ClosureBeforeS, prevMid) * FrameHz); // never before the previous syllable's middle
                var b = Math.Max(a + 2, (int)Math.Round((start + (shapes is not null ? ClosureAfterS : end - start)) * FrameHz));
                if (lips.Count > 0 && lips[^1].Frame >= a)
                    lips.RemoveAt(lips.Count - 1); // the previous closure is still on: one longer closure
                lips.Add(new LipClosure(a, strength));
                lips.Add(new LipClosure(Math.Min(b, frames), 0));
            }
            prevMid = (start + end) / 2;
        }
        // Coarticulation: a centred mean over three frames (50 ms) of the timed frames.
        var vowels = new double[]?[frames];
        for (var k = 0; k < frames; k++)
        {
            if (track[k] is null)
                continue;
            var near = new[] { k - 1, k, k + 1 }.Where(j => j >= 0 && j < frames && track[j] is not null).Select(j => track[j]).ToList();
            var mean = new double[5];
            for (var c = 0; c < 5; c++)
            {
                var sum = 0.0;
                foreach (var w in near)
                    sum += w[c];
                mean[c] = sum / near.Count;
            }
            vowels[k] = mean;
        }
        return new LipSyncPlan(FrameHz, vowels, lips);
    }

    /// <summary>Whether the audio is a WAV file, the only kind the aligner takes (the local voice speaks WAV).</summary>
    public static bool IsWav(ReadOnlySpan<byte> audio) => audio.Length >= 12 && audio[..4].SequenceEqual("RIFF"u8) && audio.Slice(8, 4).SequenceEqual("WAVE"u8);

    /// <summary>The plan for an aligned reply: as many frames as its audio lasts.</summary>
    public static LipSyncPlan Plan(SpeechAlignment alignment) => Plan(alignment.Characters, (int)(alignment.DurationS * FrameHz));
}
