from pathlib import Path
import hashlib,json,subprocess,sys
B=Path('/Volumes/Untitled/AIJADE');C=Path(__file__).resolve().parent;W=C/'worktree';O=B/'.research/runs/ch7-relocation-20261116'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
profile=C/'godot-project-writes-only.sb';assert not profile.exists();profile.write_bytes((O/'godot-project-writes-only.sb').read_bytes())
godot=Path('/Users/mac/.local/share/mosaic/godot-4.5.2/Godot_mono.app/Contents/MacOS/Godot');model=B/'references/private-renderer-assets/m2/明音凛1.1.pmx';client=O/'prepared-renderer'
assert godot.is_file() and model.is_file() and (client/'aijade-prepared-renderer.json').is_file()
assert sha(model)=='0151ed94ef82d4d53684b614333ec46f20b59750db59b88db0819dbd74caab53'
marker=json.loads((client/'aijade-prepared-renderer.json').read_text())
print(json.dumps({'rendererMarker':marker,'godotSha256':sha(godot),'modelSha256':sha(model),'profileSha256':sha(profile),'knownInputs':sorted(p.name for p in (C/'qualification-inputs').iterdir())},indent=2))
(C/'known-launch-assets-preflight.json').write_text(json.dumps(dict(rendererMarker=marker,godotSha256=sha(godot),modelSha256=sha(model),profileSha256=sha(profile)),indent=2)+'\n')
