"""Stage vectors of the companion contract (docs/COMPANION-CONTRACT.md, 1.3.0), from MOSAIC's live-scene workbench.

What her body does after a reply on MOSAIC's home stage is decided by fixed words in the user's message
(LiveSceneCommands: ChatPlace, ChatMovement, ChatDance, ChatGesture). MOSAIC is read-only from this repository, so that file
is copied into a temporary project outside both repositories, compiled and run on the sentences below; its word lists are
read from the compiled copy by reflection. The spots come from MOSAIC's home layout. Two small pieces of its session service
are transcribed below, as the put-off rule was for 1.2.0: the spot words and what she goes there to do (HomePlaceWords,
HomePlaceDoing), and the order of the decisions (place, movement, dance, gesture).

    python3 -B -I configs/companion/generate_stage_vectors.py <MOSAIC> configs/companion/stage-vectors.json [read-on date]

Needs a .NET SDK (DOTNET, default `dotnet`).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

mosaic, out = sys.argv[1], sys.argv[2]
read_on = sys.argv[3] if len(sys.argv) > 3 else time.strftime("%Y-%m-%d")
commands_cs = os.path.join(mosaic, "src", "AijadeWorkbench.Application", "LiveScene", "LiveSceneCommands.cs")
home_json = os.path.join(mosaic, "configs", "scenes", "home-v1.json")

home = json.load(open(home_json, encoding="utf-8"))
spots = [dict(name=s["name"], label=s["label"], activity=s.get("activity"), room=s.get("room"), aliases=list(s.get("aliases", [])))
         for s in home["spots"]]
# HomePlaceWords: each spot's label, then its aliases; empty and repeated words left out, first occurrence kept.
places = list(dict.fromkeys(w for s in spots for w in [s["label"], *s["aliases"]] if w))
# HomePlaceDoing: each word -> "去" + label + 坐下 / 躺下休息 by the spot's activity; the first spot to name a word keeps it.
doing = {}
for s in spots:
    what = "去" + s["label"] + {"sit": "坐下", "lie": "躺下休息"}.get(s["activity"], "")
    for w in [s["label"], *s["aliases"]]:
        if w:
            doing.setdefault(w, what)

sentences = [
    # a spot in her home
    "去沙发坐会儿吧", "该睡觉了", "到床上躺着", "回卧室吧", "我们去打篮球吧", "陪我弹钢琴", "一起看电视吧", "快去吃饭",
    "去书桌前学习一会儿", "沙发好舒服", "院子里有什么", "我去睡觉了", "我要去游泳", "你别去厨房", "起来吧", "起床啦",
    # walking on the spot
    "过来一下好吗", "你别过来", "转一圈给我看", "转过身", "退后一点", "走开", "陪我散步", "离远点", "come here please",
    # dancing
    "跳个舞吧", "来段舞", "不要跳舞", "Can you dance?", "跳一下鹿鸣",
    # gestures, asked for or situational
    "给我鞠个躬", "挥挥手", "帮我带路", "理理头发", "谢谢你", "谢谢，再见", "你好呀", "你好像很开心", "晚上好！", "Hello there",
    # several at once, or none
    "过来跳个舞", "去沙发跳个舞", "今天好累", "你在哪呀", "抱抱我",
]

program = r'''
using System.Reflection;
using System.Text.Json;
using System.Text.RegularExpressions;
using AijadeWorkbench.Application.LiveScene;

var input = JsonDocument.Parse(File.ReadAllText(args[0])).RootElement;
var places = input.GetProperty("places").EnumerateArray().Select(p => p.GetString()!).ToArray();
var t = typeof(LiveSceneCommands);
object? Field(string name) => t.GetField(name, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)!.GetValue(null);
var greeting = (Regex)Field("Greeting")!;
var words = new Dictionary<string, object?>
{
    ["negations"] = Field("Negations"), ["selfGoing"] = Field("SelfGoing"), ["goWords"] = Field("GoWords"),
    ["invitations"] = Field("Invitations"), ["standUpWords"] = LiveSceneCommands.StandUpWords,
    ["movements"] = LiveSceneCommands.ChatMovements.Select(m => new { keywords = m.Keywords, script = m.Script }),
    ["danceKeywords"] = LiveSceneCommands.ChatDanceKeywords,
    ["gestures"] = LiveSceneCommands.ChatGestures.Select(g => new { keywords = g.Keywords, gesture = g.Gesture }),
    ["situationalGestures"] = LiveSceneCommands.SituationalGestures.Select(g => new { keywords = g.Keywords, gesture = g.Gesture }),
    ["greeting"] = new { pattern = greeting.ToString(), options = greeting.Options.ToString() },
    ["gestureNames"] = LiveSceneCommands.GestureNames,
    ["standUp"] = LiveSceneCommands.StandUp,
    ["goalWalks"] = LiveSceneCommands.GoalWalks,
};
var cases = input.GetProperty("sentences").EnumerateArray().Select(s => s.GetString()!).Select(s => new
{
    text = s,
    place = LiveSceneCommands.ChatPlace(s, places),
    movement = LiveSceneCommands.ChatMovement(s),
    dance = LiveSceneCommands.ChatDance(s),
    gesture = LiveSceneCommands.ChatGesture(s, situational: true),
    gestureAsked = LiveSceneCommands.ChatGesture(s, situational: false),
});
Console.Out.Write(JsonSerializer.Serialize(new { words, cases }, new JsonSerializerOptions { Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping }));
'''

project = '''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>
  <Nullable>enable</Nullable><NoWarn>CS1591</NoWarn></PropertyGroup>
</Project>
'''

work = tempfile.mkdtemp(prefix="stage-vectors-")
try:
    shutil.copyfile(commands_cs, os.path.join(work, "LiveSceneCommands.cs"))
    open(os.path.join(work, "Program.cs"), "w", encoding="utf-8").write(program)
    open(os.path.join(work, "StageVectors.csproj"), "w", encoding="utf-8").write(project)
    json.dump(dict(places=places, sentences=sentences), open(os.path.join(work, "input.json"), "w", encoding="utf-8"), ensure_ascii=False)
    run = subprocess.run([os.environ.get("DOTNET", "dotnet"), "run", "-c", "Release", "--", os.path.join(work, "input.json")],
                         cwd=work, capture_output=True, text=True, timeout=600)
    if run.returncode != 0:
        sys.exit(run.stdout[-3000:] + run.stderr[-3000:])
    result = json.loads(run.stdout[run.stdout.index('{"words"'):])
finally:
    shutil.rmtree(work, ignore_errors=True)


def decide(case, seated):
    """MOSAIC's order (LiveSceneService, the Chat step): place, else movement, else dance, else gesture. Standing up only
    when she sits or lies. Situational gestures count, as when MOSAIC's ModelActions is off; a dance assumes a dance library."""
    place = case["place"]
    if place == result["words"]["standUp"] and not seated:
        place = None
    if place is not None:
        return dict(kind="stand", argument=None) if place == result["words"]["standUp"] else dict(kind="place", argument=place)
    if case["movement"] is not None:
        return dict(kind="walk", argument=case["movement"])
    if case["dance"]:
        return dict(kind="dance", argument=None)
    if case["gesture"] is not None:
        return dict(kind="gesture", argument=case["gesture"])
    return None


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


doc = dict(
    source=dict(commands=dict(file="src/AijadeWorkbench.Application/LiveScene/LiveSceneCommands.cs (MOSAIC working copy)", sha256=sha(commands_cs)),
                home=dict(file="configs/scenes/home-v1.json (MOSAIC working copy)", sha256=sha(home_json), schema=home.get("schema")),
                readOn=read_on),
    spots=spots, places=places, doing=doing, words=result["words"],
    cases=[dict(c, decision=decide(c, seated=False), decisionSeated=decide(c, seated=True)) for c in result["cases"]],
)
json.dump(doc, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for c in doc["cases"]:
    print(c["text"], "->", c["decision"], "| seated:", c["decisionSeated"])
