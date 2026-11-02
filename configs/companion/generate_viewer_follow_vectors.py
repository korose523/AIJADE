"""Viewer-follow vectors (ADR-003, migration batch 2; not part of the shared companion contract), made by MOSAIC's own
ViewerFollow class (host-dotnet/Mosaic.Scene.Core/ViewerFollow.cs), so that AIJADE's port for the web stage
(tools/mmd-bundle/viewer-follow.js) moves the camera as MOSAIC's renderer client does.

MOSAIC is read-only from this repository: the file is copied into a temporary project outside both repositories, compiled
and run on the scenarios below with a clock that steps 1/31 s, so that no threshold (1.2 s of walking away, for one)
falls exactly on a step, where single and double precision could cross it one step apart. Each step gives the class her root and the camera where the
previous step put it; the camera, the look point, the view direction and her smoothed velocity are recorded. The world is
in metres, y up, the camera framed 3 m in front of her, as MOSAIC frames it.

    python3 -B -I configs/companion/generate_viewer_follow_vectors.py <MOSAIC> configs/companion/viewer-follow-vectors.json

Needs a .NET SDK (DOTNET, default `dotnet`). MOSAIC computes in single precision, the port in double: the tests allow 1 mm.
"""
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time

mosaic, out = sys.argv[1], sys.argv[2]
source = os.path.join(mosaic, "host-dotnet", "Mosaic.Scene.Core", "ViewerFollow.cs")
DT = 1 / 31


def path(seconds, at):
    """Her root at each step of `seconds` seconds, from at(t)."""
    return [[round(k * DT, 6), *[round(c, 6) for c in at(k * DT)]] for k in range(int(round(seconds / DT)) + 1)]


scenarios = [
    # standing: her root sways 4 cm, breathing and shifting her weight; the camera holds
    dict(name="idle sway", roots=path(3, lambda t: (0.04 * math.sin(2 * math.pi * 0.7 * t), 0, 0.03 * math.sin(2 * math.pi * 0.45 * t)))),
    # a step to the side and stop: the camera follows sideways, then holds her centred
    dict(name="side step", roots=path(3, lambda t: (min(t, 1) * 0.3, 0, 0))),
    # "过来": she comes 1.2 m nearer (still inside the band), then 0.3 m more (past Near): only then does the camera back off
    dict(name="comes closer", roots=path(5, lambda t: (0, 0, min(t / 3, 1) * 1.2 + max(0, min((t - 3.5) / 1, 1)) * 0.3))),
    # walking away along the view for 5 s: the view leads her, then turns toward her side
    dict(name="walks away", roots=path(5, lambda t: (0, 0, -0.8 * t))),
    # walking sideways for 3 s at 1 m/s: the lead is capped at 0.6 m
    dict(name="walks sideways", roots=path(3, lambda t: (1.0 * t, 0, 0))),
    # a diagonal walk away and a stop: the turned view stays turned
    dict(name="walks away then stops", roots=path(6, lambda t: (0.4 * min(t, 4), 0, -0.6 * min(t, 4)))),
]
frame = dict(camera=[0, 1.5, 3], look=[0, 1.4, 0])

program = r'''
using System.Numerics;
using System.Text.Json;
using Mosaic.Scene.Core;

var input = JsonDocument.Parse(File.ReadAllText(args[0])).RootElement;
Vector3 V(JsonElement a) => new(a[0].GetSingle(), a[1].GetSingle(), a[2].GetSingle());
double[] A(Vector3 v) => [Math.Round(v.X, 6), Math.Round(v.Y, 6), Math.Round(v.Z, 6)];
var camera0 = V(input.GetProperty("frame").GetProperty("camera"));
var look0 = V(input.GetProperty("frame").GetProperty("look"));
var results = new List<object>();
foreach (var s in input.GetProperty("scenarios").EnumerateArray())
{
    var steps = s.GetProperty("roots").EnumerateArray().Select(r => (T: r[0].GetDouble(), Root: new Vector3(r[1].GetSingle(), r[2].GetSingle(), r[3].GetSingle()))).ToList();
    double now = steps[0].T;
    var follow = new ViewerFollow(camera0, look0, steps[0].Root, () => now);
    var camera = camera0;
    var outs = new List<object>();
    foreach (var (t, root) in steps)
    {
        now = t;
        var (at, look) = follow.Desired(camera, root);
        camera = at;
        outs.Add(new { camera = A(at), look = A(look), forward = A(follow.Forward), velocity = A(follow.Velocity) });
    }
    results.Add(new { name = s.GetProperty("name").GetString(), framed = Math.Round(follow.Framed, 6), steps = outs });
}
Console.Out.Write(JsonSerializer.Serialize(new { results }));
'''

project = '''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>
  <Nullable>enable</Nullable><NoWarn>CS1591</NoWarn></PropertyGroup>
</Project>
'''

work = tempfile.mkdtemp(prefix="viewer-follow-vectors-")
try:
    shutil.copyfile(source, os.path.join(work, "ViewerFollow.cs"))
    open(os.path.join(work, "Program.cs"), "w", encoding="utf-8").write(program)
    open(os.path.join(work, "ViewerFollowVectors.csproj"), "w", encoding="utf-8").write(project)
    json.dump(dict(frame=frame, scenarios=scenarios), open(os.path.join(work, "input.json"), "w", encoding="utf-8"))
    run = subprocess.run([os.environ.get("DOTNET", "dotnet"), "run", "-c", "Release", "--", os.path.join(work, "input.json")],
                         cwd=work, capture_output=True, text=True, timeout=600)
    if run.returncode != 0:
        sys.exit(run.stdout[-3000:] + run.stderr[-3000:])
    results = json.loads(run.stdout[run.stdout.index('{"results"'):])["results"]
finally:
    shutil.rmtree(work, ignore_errors=True)

doc = dict(
    note="Generated by configs/companion/generate_viewer_follow_vectors.py from MOSAIC's ViewerFollow; AIJADE's port is "
         "tools/mmd-bundle/viewer-follow.js (ADR-003).",
    source=dict(file="host-dotnet/Mosaic.Scene.Core/ViewerFollow.cs (MOSAIC working copy)",
                sha256=hashlib.sha256(open(source, "rb").read()).hexdigest(), readOn=time.strftime("%Y-%m-%d")),
    dt=round(DT, 9), frame=frame,
    cases=[dict(name=s["name"], roots=s["roots"], framed=r["framed"], expected=r["steps"]) for s, r in zip(scenarios, results)],
)
json.dump(doc, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(doc["cases"]), "cases")
