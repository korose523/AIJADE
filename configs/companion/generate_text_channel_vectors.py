"""Text-channel vectors of the companion contract (docs/COMPANION-CONTRACT.md, 1.2.0), from MOSAIC's QQ bridge.

MOSAIC is read-only from this repository, and its bridge is a script with side effects, so it is not run: its constants are
read from the source with `ast` (CHANNEL_NOTE, MOVEMENT_NOTE, MOVEMENT_WORDS, PUT_OFF, LATER). The put-off rule is inline in
its `answer()`; it is transcribed below (`put_off`) and the cases record what that rule gives.

    python3 -B -I configs/companion/generate_text_channel_vectors.py \\
        <MOSAIC>/tools/companion_qq.py configs/companion/text-channel-vectors.json
"""
import ast
import hashlib
import json
import sys
import time

src, out = sys.argv[1], sys.argv[2]
read_on = sys.argv[3] if len(sys.argv) > 3 else time.strftime("%Y-%m-%d")
source = open(src, "rb").read()
names = {"CHANNEL_NOTE", "MOVEMENT_NOTE", "MOVEMENT_WORDS", "PUT_OFF", "LATER"}
consts = {}
for node in ast.parse(source).body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names:
        consts[node.targets[0].id] = ast.literal_eval(node.value)
missing = names - consts.keys()
if missing:
    sys.exit(f"not found in {src}: {sorted(missing)}")


def put_off(text, said):
    """MOSAIC's rule (companion_qq.py, answer()): a reply to a movement request that does not put it off gets LATER added."""
    moved = any(w in text for w in consts["MOVEMENT_WORDS"])
    if moved and not any(w in said for w in consts["PUT_OFF"]):
        said = said.rstrip() + ("" if said.rstrip().endswith(("。", "！", "!", "？", "?", "~")) else "。") + consts["LATER"]
    return said


cases = [
    ("你能跳个舞给我看吗", "好呀！"),
    ("给我鞠个躬吧", "好的"),
    ("挥挥手嘛", "等你回到屏幕前我就挥手~"),
    ("转一圈给我看", "现在不能哦，下次吧"),
    ("今天好累", "辛苦了，要不要早点休息？"),
    ("过来抱抱我", "抱抱你。"),
    ("Can you dance for me?", "Sure!"),
    ("比心", "好啊  "),
]
doc = dict(source=dict(file="tools/companion_qq.py (MOSAIC working copy)", sha256=hashlib.sha256(source).hexdigest(), readOn=read_on),
           mosaic=dict(medium="QQ text messages on their phone", channel="QQ", channelNote=consts["CHANNEL_NOTE"],
                       movementNote=consts["MOVEMENT_NOTE"]),
           movementWords=list(consts["MOVEMENT_WORDS"]), putOff=list(consts["PUT_OFF"]), later=consts["LATER"],
           cases=[dict(text=t, reply=r, sent=put_off(t, r)) for t, r in cases])
json.dump(doc, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for c in doc["cases"]:
    print(c["text"], "->", c["sent"])
