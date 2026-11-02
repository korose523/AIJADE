using System.Text.Json;

using Aijade.Client.Companion;

namespace Aijade.Tests;

/// <summary>
/// The mouth from the text (ADR-003, migration batch 1): the port of MOSAIC's aligned tracks, case by case against the
/// vectors its own module made (configs/companion/viseme-vectors.json).
/// </summary>
public class LipSyncTests
{
    private static readonly string Root = RqcReanalysisTests.RepoRoot();

    [Fact]
    public void Every_case_is_shaped_as_MOSAICs_module_shapes_it()
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "configs", "companion", "viseme-vectors.json")));
        var v = doc.RootElement;
        var constants = v.GetProperty("constants");
        Assert.Equal(LipSync.FrameHz, constants.GetProperty("frameHz").GetInt32());
        Assert.Equal((constants.GetProperty("closureBeforeS").GetDouble(), constants.GetProperty("closureAfterS").GetDouble()), (LipSync.ClosureBeforeS, LipSync.ClosureAfterS));
        Assert.Equal(constants.GetProperty("lipInitials").EnumerateObject().ToDictionary(p => p.Name, p => p.Value.GetDouble()).OrderBy(p => p.Key, StringComparer.Ordinal),
            LipSync.LipInitials.OrderBy(p => p.Key, StringComparer.Ordinal));
        var finals = constants.GetProperty("finalShapes").EnumerateObject().ToDictionary(p => p.Name,
            p => p.Value.EnumerateArray().Select(s => (s.GetProperty("vowels").GetString()!, s.GetProperty("share").GetDouble())).ToArray());
        Assert.Equal(finals.Keys.Order(StringComparer.Ordinal), LipSync.FinalShapes.Keys.Order(StringComparer.Ordinal));
        foreach (var (final, shapes) in finals)
            Assert.Equal(shapes, LipSync.FinalShapes[final]);
        var cases = 0;
        foreach (var c in v.GetProperty("cases").EnumerateArray())
        {
            var text = c.GetProperty("text").GetString();
            var rows = c.GetProperty("characters").EnumerateArray().Select(r => new AlignedCharacter(r.GetProperty("char").GetString()!,
                r.GetProperty("startS").GetDouble(), r.GetProperty("endS").GetDouble(), r.GetProperty("initial").GetString()!, r.GetProperty("final").GetString()!)).ToList();
            var plan = LipSync.Plan(rows, c.GetProperty("frames").GetInt32());
            var expected = c.GetProperty("vowels").EnumerateArray()
                .Select(f => f.ValueKind == JsonValueKind.Null ? null : f.EnumerateArray().Select(x => x.GetDouble()).ToArray()).ToList();
            Assert.Equal(expected.Count, plan.Vowels.Count);
            for (var k = 0; k < expected.Count; k++)
                Assert.True(expected[k] is null ? plan.Vowels[k] is null : plan.Vowels[k] is { } w && w.SequenceEqual(expected[k]!), $"{text}: frame {k}");
            Assert.Equal(c.GetProperty("lips").EnumerateArray().Select(l => new LipClosure(l.GetProperty("frame").GetInt32(), l.GetProperty("value").GetDouble())), plan.Lips);
            cases++;
        }
        Assert.Equal(10, cases);
    }

    [Fact]
    public void An_aligned_reply_lasts_as_many_frames_as_its_audio_and_only_a_wav_is_aligned()
    {
        var plan = LipSync.Plan(new SpeechAlignment(0.5, [new("你", 0, .25, "n", "i"), new("好", .25, .5, "h", "ao"), new("？", -1, .1, "", "")]));
        Assert.Equal((60, 30), (plan.FrameHz, plan.Vowels.Count));
        Assert.Equal([0, 1, 0, 0, 0], plan.Vowels[0]!); // i: the lips spread
        Assert.Empty(plan.Lips);
        Assert.True(LipSync.IsWav("RIFF\0\0\0\0WAVEfmt "u8));
        Assert.False(LipSync.IsWav("OggS\0\0\0\0\0\0\0\0"u8));
        Assert.False(LipSync.IsWav("RIFF"u8));
    }
}
