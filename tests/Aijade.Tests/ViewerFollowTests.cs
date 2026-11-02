using System.Text.Json;

using Jint;

namespace Aijade.Tests;

/// <summary>
/// The web stage's camera follow (ADR-003, migration batch 2): tools/mmd-bundle/viewer-follow.js, run in Jint on the
/// vectors MOSAIC's own ViewerFollow made (configs/companion/viewer-follow-vectors.json). MOSAIC computes in single
/// precision and the port in double, so positions are compared within 1 mm.
/// </summary>
public class ViewerFollowTests
{
    private static readonly string Root = RqcReanalysisTests.RepoRoot();

    private const string Runner = """
        import { ViewerFollow } from 'viewer-follow';
        export function run(json, metre) {
          const doc = JSON.parse(json), v = (a) => ({ x: a[0] * metre, y: a[1] * metre, z: a[2] * metre }), out = [];
          for (const c of doc.cases) {
            let now = c.roots[0][0], camera = v(doc.frame.camera);
            const f = new ViewerFollow(v(doc.frame.camera), v(doc.frame.look), v(c.roots[0].slice(1)), { clock: () => now, metre });
            out.push({ name: c.name, steps: c.roots.map(r => {
              now = r[0];
              const d = f.desired(camera, v(r.slice(1)));
              camera = d.camera;
              return [d.camera, d.look, f.forward, f.velocity].map(p => [p.x, p.y, p.z]);
            }) });
          }
          return JSON.stringify(out);
        }
        """;

    /// <summary>The port's steps for every case, in a world of <paramref name="metre"/> units to the metre.</summary>
    private static (JsonElement Ported, JsonElement Expected) Run(double metre)
    {
        var engine = new Engine();
        engine.Modules.Add("viewer-follow", File.ReadAllText(Path.Combine(Root, "tools", "mmd-bundle", "viewer-follow.js")));
        engine.Modules.Add("runner", Runner);
        var json = File.ReadAllText(Path.Combine(Root, "configs", "companion", "viewer-follow-vectors.json"));
        var ported = engine.Invoke(engine.Modules.Import("runner").Get("run"), json, metre).AsString();
        using var p = JsonDocument.Parse(ported);
        using var e = JsonDocument.Parse(json);
        return (p.RootElement.Clone(), e.RootElement.Clone());
    }

    [Fact]
    public void The_port_moves_the_camera_as_MOSAICs_class_does()
    {
        var (ported, expected) = Run(1);
        var cases = expected.GetProperty("cases").EnumerateArray().ToList();
        Assert.Equal(6, cases.Count);
        foreach (var (c, mine) in cases.Zip(ported.EnumerateArray()))
        {
            var name = c.GetProperty("name").GetString();
            var steps = c.GetProperty("expected").EnumerateArray().ToList();
            Assert.Equal(steps.Count, mine.GetProperty("steps").GetArrayLength());
            foreach (var (want, (got, k)) in steps.Zip(mine.GetProperty("steps").EnumerateArray().Select((s, i) => (s, i))))
            {
                var fields = new[] { "camera", "look", "forward", "velocity" };
                for (var f = 0; f < fields.Length; f++)
                {
                    var a = want.GetProperty(fields[f]).EnumerateArray().Select(x => x.GetDouble()).ToArray();
                    var b = got[f].EnumerateArray().Select(x => x.GetDouble()).ToArray();
                    Assert.True(a.Zip(b).All(p => Math.Abs(p.First - p.Second) < 1e-3), $"{name}, step {k}, {fields[f]}: MOSAIC {string.Join(',', a)}, port {string.Join(',', b)}");
                }
            }
        }
    }

    [Fact]
    public void In_an_MMD_scene_the_same_walk_gives_the_same_shot_at_its_scale()
    {
        // 12.5 units to the metre (MMD, 8 cm to the unit): the dead zone, walking speed and lead scale with the world, so every
        // position is the metre case times 12.5 and the view directions are the same.
        var (metres, _) = Run(1);
        var (units, _) = Run(12.5);
        foreach (var (m, u) in metres.EnumerateArray().Zip(units.EnumerateArray()))
        {
            foreach (var (sm, su) in m.GetProperty("steps").EnumerateArray().Zip(u.GetProperty("steps").EnumerateArray()))
            {
                for (var f = 0; f < 4; f++)
                {
                    var factor = f == 2 ? 1 : 12.5; // the view direction is a unit vector
                    var a = sm[f].EnumerateArray().Select(x => x.GetDouble() * factor).ToArray();
                    var b = su[f].EnumerateArray().Select(x => x.GetDouble()).ToArray();
                    Assert.True(a.Zip(b).All(p => Math.Abs(p.First - p.Second) < 1e-6 * 12.5), $"{m.GetProperty("name").GetString()}: {string.Join(',', a)} vs {string.Join(',', b)}");
                }
            }
        }
    }
}
