"""Selfie vectors (ADR-003, migration batch 2; not part of the shared companion contract), made by MOSAIC's own code, so
that AIJADE's ports take a picture when and as MOSAIC does:
  - when: `due` of ai-python/mosaic/life/share.py (with its hour and night window from mosaic/life/model.py), ported in
    src/Aijade.Client/Companion/Selfies.cs. MOSAIC is read-only from this repository: both modules are loaded from their
    files under stand-in packages, and no bytecode is written. The modules use the local time zone, so run with TZ set.
  - where her phone is: SelfieShot.Frame of host-dotnet/Mosaic.Scene.Core/SelfieShot.cs, ported in
    tools/mmd-bundle/selfie-shot.js. The file is copied into a temporary project outside both repositories, compiled and
    run (needs a .NET SDK: DOTNET, default `dotnet`). World metres, y up, right-handed, as in MOSAIC.

    TZ=Asia/Seoul python3 -B -I configs/companion/generate_selfie_vectors.py <MOSAIC> configs/companion/selfie-vectors.json

The due cases cover each rule in MOSAIC's order and its edges (the hours, the owner nearby, two a day, three hours apart,
chance); every case has her settled somewhere, a rule AIJADE's stage has no counterpart for, except one that records what
MOSAIC says when she is not. The frame cases cover her standing with her head turned, without eyes, reclined below and
above the 35° limit, lying on her back, and eyes too close to tell apart.
"""
import hashlib, importlib.util, json, math, os, shutil, subprocess, sys, tempfile, time, types
sys.dont_write_bytecode = True
mosaic, out = sys.argv[1], sys.argv[2]
if not os.environ.get("TZ"):
    sys.exit("set TZ (for example TZ=Asia/Seoul): MOSAIC's hours are local")
time.tzset()
life = os.path.join(mosaic, "ai-python", "mosaic", "life")
shot_cs = os.path.join(mosaic, "host-dotnet", "Mosaic.Scene.Core", "SelfieShot.cs")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


for package in ("mosaic", "mosaic.life"):
    stand_in = types.ModuleType(package)
    stand_in.__path__ = []
    sys.modules[package] = stand_in
model = load("mosaic.life.model", os.path.join(life, "model.py"))
sys.modules["mosaic.life"].model = model
share = load("mosaic.life.share", os.path.join(life, "share.py"))


class Fixed:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


def at(h, m=0, day=3):
    return time.mktime((2026, 11, day, h, m, 0, 0, 0, -1))


NOW = at(15)
SETTLED = "settled half an hour before"
on = dict(share.DEFAULTS, channel="qq")
cases = [
    ("all clear", on, [], NOW, 3600, 0.01, SETTLED),
    ("not this minute", on, [], NOW, 3600, 0.5, SETTLED),
    ("the chance's edge", on, [], NOW, 3600, 0.05, SETTLED),
    ("before ten", on, [], at(9, 59), 3600, 0.01, SETTLED),
    ("at ten", on, [], at(10, 0), 3600, 0.01, SETTLED),
    ("at half past nine in the evening", on, [], at(21, 30), 3600, 0.01, SETTLED),
    ("at night", on, [], at(23, 30), 3600, 0.01, SETTLED),
    ("the owner was here ten minutes ago", on, [], NOW, 600, 0.01, SETTLED),
    ("the owner left exactly thirty minutes ago", on, [], NOW, 1800, 0.01, SETTLED),
    ("the owner has not been seen", on, [], NOW, None, 0.01, SETTLED),
    ("two sent today", on, [at(10, 30), at(13, 40)], NOW, 3600, 0.01, SETTLED),
    ("one sent two hours ago", on, [at(13, 0)], NOW, 3600, 0.01, SETTLED),
    ("one sent three hours ago", on, [at(12, 0)], NOW, 3600, 0.01, SETTLED),
    ("no channel", dict(share.DEFAULTS), [], NOW, 3600, 0.01, SETTLED),
    ("off", None, [], NOW, 3600, 0.01, SETTLED),
    ("not settled anywhere (MOSAIC only)", on, [], NOW, 3600, 0.01, "arrived a minute before"),
]
due = []
for name, s, taken, now, owner_ago, chance, activity in cases:
    st = dict(events=[dict(at=t, kind="selfie") for t in taken],
              activity=dict(arrived=True, name="sofa", start=now - (1800 if activity == SETTLED else 60)))
    ok, why = share.due(s, st, now, owner_ago, Fixed(chance))
    due.append(dict(name=name, on=s is not None and s["channel"] != "none", takenS=[t - NOW for t in taken], nowS=now - NOW,
                    ownerAgoS=owner_ago, random=chance, settled=name != "not settled anywhere (MOSAIC only)", due=ok, why=why))


def v(x, y, z):
    return [round(x, 6), round(y, 6), round(z, 6)]


# Her eyes 6 cm apart, facing +z (her left eye at +x, as in a right-handed world when she faces +z).
turn = math.radians(30)
frames = [
    dict(name="standing", head=v(0, 1.52, 0), left=v(0.03, 1.58, 0.07), right=v(-0.03, 1.58, 0.07), body=v(0, 0, 1), neck=v(0, 1.42, -0.01)),
    dict(name="head turned 30 degrees", head=v(0, 1.52, 0), left=v(0.03 * math.cos(turn) + 0.07 * math.sin(turn), 1.58, -0.03 * math.sin(turn) + 0.07 * math.cos(turn)),
         right=v(-0.03 * math.cos(turn) + 0.07 * math.sin(turn), 1.58, 0.03 * math.sin(turn) + 0.07 * math.cos(turn)), body=v(0, 0, 1), neck=v(0, 1.42, -0.01)),
    dict(name="no eyes", head=v(0, 1.52, 0), left=None, right=None, body=v(1, 0.2, 1), neck=None),
    dict(name="eyes too close", head=v(0, 1.52, 0), left=v(0.0002, 1.58, 0.07), right=v(-0.0002, 1.58, 0.07), body=v(0, 0, 1), neck=v(0, 1.42, -0.01)),
    dict(name="reclined 30 degrees", head=v(0, 1.0 + 0.1 * math.cos(math.radians(30)), -0.1 * math.sin(math.radians(30))), left=v(0.03, 1.12, 0.02),
         right=v(-0.03, 1.12, 0.02), body=v(0, 0, 1), neck=v(0, 1.0, 0)),
    dict(name="reclined 40 degrees", head=v(0, 1.0 + 0.1 * math.cos(math.radians(40)), -0.1 * math.sin(math.radians(40))), left=v(0.03, 1.11, 0.0),
         right=v(-0.03, 1.11, 0.0), body=v(0, 0, 1), neck=v(0, 1.0, 0)),
    # on her back, head toward +z, face up: her left is -x
    dict(name="lying on her back", head=v(0, 0.55, 0.1), left=v(-0.03, 0.6, 0.12), right=v(0.03, 0.6, 0.12), body=v(0, 0, 1), neck=v(0, 0.55, 0.0)),
    dict(name="no eyes and facing straight up", head=v(0, 1.52, 0), left=None, right=None, body=v(0, 1, 0), neck=None),
]

program = r'''
using System.Numerics;
using System.Text.Json;
using Mosaic.Scene.Core;

var input = JsonDocument.Parse(File.ReadAllText(args[0])).RootElement;
Vector3? V(JsonElement a) => a.ValueKind == JsonValueKind.Null ? null : new Vector3(a[0].GetSingle(), a[1].GetSingle(), a[2].GetSingle());
double[] A(Vector3 v) => [Math.Round(v.X, 6), Math.Round(v.Y, 6), Math.Round(v.Z, 6)];
var results = new List<object>();
foreach (var c in input.GetProperty("frames").EnumerateArray())
{
    try
    {
        var (camera, look, facing, up) = SelfieShot.Frame(V(c.GetProperty("head"))!.Value, V(c.GetProperty("left")), V(c.GetProperty("right")),
            V(c.GetProperty("body"))!.Value, V(c.GetProperty("neck")));
        results.Add(new { camera = A(camera), look = A(look), facing = A(facing), up = A(up), error = (string?)null });
    }
    catch (ArgumentException e)
    {
        results.Add(new { camera = (double[]?)null, look = (double[]?)null, facing = (double[]?)null, up = (double[]?)null, error = (string?)e.Message });
    }
}
Console.Out.Write(JsonSerializer.Serialize(new { results, constants = new { SelfieShot.Arm, SelfieShot.Above, SelfieShot.Aside, SelfieShot.FovDegrees,
    SelfieShot.FaceDrop, SelfieShot.UprightDegrees, SelfieShot.Width, SelfieShot.Height } }));
'''
project = '''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>
  <Nullable>enable</Nullable><NoWarn>CS1591</NoWarn></PropertyGroup>
</Project>
'''
work = tempfile.mkdtemp(prefix="selfie-vectors-")
try:
    shutil.copyfile(shot_cs, os.path.join(work, "SelfieShot.cs"))
    open(os.path.join(work, "Program.cs"), "w", encoding="utf-8").write(program)
    open(os.path.join(work, "SelfieVectors.csproj"), "w", encoding="utf-8").write(project)
    json.dump(dict(frames=frames), open(os.path.join(work, "input.json"), "w", encoding="utf-8"))
    run = subprocess.run([os.environ.get("DOTNET", "dotnet"), "run", "-c", "Release", "--", os.path.join(work, "input.json")],
                         cwd=work, capture_output=True, text=True, timeout=600)
    if run.returncode != 0:
        sys.exit(run.stdout[-3000:] + run.stderr[-3000:])
    shot = json.loads(run.stdout[run.stdout.index('{"results"'):])
finally:
    shutil.rmtree(work, ignore_errors=True)


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


doc = dict(
    note="Generated by configs/companion/generate_selfie_vectors.py from MOSAIC's mosaic/life/share.py (due) and "
         "Mosaic.Scene.Core/SelfieShot.cs (Frame); AIJADE's ports are src/Aijade.Client/Companion/Selfies.cs and "
         "tools/mmd-bundle/selfie-shot.js (ADR-003).",
    source=dict(share=dict(file="ai-python/mosaic/life/share.py", sha256=sha(os.path.join(life, "share.py"))),
                model=dict(file="ai-python/mosaic/life/model.py", sha256=sha(os.path.join(life, "model.py"))),
                shot=dict(file="host-dotnet/Mosaic.Scene.Core/SelfieShot.cs", sha256=sha(shot_cs)),
                readOn=time.strftime("%Y-%m-%d")),
    timeZone=os.environ["TZ"], now=dict(epoch=NOW, local="2026-11-03 15:00"),
    rules=dict(perDay=share.DEFAULTS["per_day"], fromHour=share.DEFAULTS["from_hour"], toHour=share.DEFAULTS["to_hour"],
               minGapHours=share.DEFAULTS["min_gap_hours"], ownerAwayMin=share.DEFAULTS["owner_away_min"],
               chancePerMinute=share.DEFAULTS["chance_per_minute"], night=list(model.NIGHT)),
    due=due,
    frame=dict(constants=shot["constants"], cases=[dict(c, expected=r) for c, r in zip(frames, shot["results"])]),
)
json.dump(doc, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(due), "due cases,", len(frames), "frames")
