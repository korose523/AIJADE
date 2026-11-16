from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, subprocess

C = Path(__file__).resolve().parent
BASE = Path('/Volumes/Untitled/AIJADE')
W = C / 'worktree'
P = BASE / '.runtime/python-envs/p2-tokenizer/bin/python'
output = BASE / '.runtime/posix/runs/ch7-relocation-20261116/qualification-01'
build = json.loads((C / 'frozen-build.json').read_text())
publication = json.loads((C / 'binary-freeze-publication.json').read_text())
assert publication['status'] == 'ACTUAL_BINARY_IDENTITIES_PUBLIC_BEFORE_ADMISSION'
assert publication['sourceCommit'] == build['commit']
assert hashlib.sha256((C / 'frozen-build.json').read_bytes()).hexdigest() == publication['frozenBuildSha256']
assert json.loads((C / 'execution-source-ci.json').read_text())['conclusion'] == 'success'
assert not output.exists()
env = dict(os.environ, **json.loads((C / 'service-environment.json').read_text()),
           AIJADE_GIT_COMMIT=build['commit'],
           AIJADE_TEST_DATABASE_URL='postgres://aijade:aijade@127.0.0.1:55432/aijade',
           AIJADE_REAL_GODOT='/Users/mac/.local/share/mosaic/godot-4.5.2/Godot_mono.app/Contents/MacOS/Godot',
           AIJADE_GODOT_SANDBOX_PROFILE=str(C / 'godot-project-writes-only.sb'),
           AIJADE_GODOT_LOG_DIR=str(C / 'godot-version-probe'))
env.pop('REDIS_URL', None)
args = [str(P), str(W / 'experiments/ch7/run_finite_sequence.py')]
options = {
    'repo': W, 'client': C / 'prepared-renderer',
    'model': BASE / 'references/private-renderer-assets/m2/明音凛1.1.pmx',
    'selection': C / 'qualification-inputs/selection.json',
    'inputs': C / 'qualification-inputs', 'output': output,
    'dotnet': '/Users/mac/.dotnet/dotnet', 'assembly': build['assemblyPath'],
    'build-manifest': C / 'frozen-build.json',
    'build-freeze-commit': publication['buildFreezeCommit'],
    'godot': W / 'experiments/ch7/godot_local.py',
    'docker': '/Users/mac/.local/bin/docker', 'db-container': 'aijade-next-db',
    'execution-plan': W / 'experiments/plans/2026-11-16-ch7-relocated-runtime-qualification.md',
    'settle-seconds': 600,
}
for key, value in options.items():
    args += ['--' + key, str(value)]
launch = C / 'single-qualification-launch.json'
assert not launch.exists()
launch.write_text(json.dumps(dict(
    status='SINGLE_PROSPECTIVE_QUALIFICATION_INVOCATION',
    launchedAt=datetime.now(timezone.utc).isoformat(), sourceCommit=build['commit'],
    buildFreezeCommit=publication['buildFreezeCommit'], command=args, output=str(output),
    sourceCI='success', globalRedisUnset=True, secondAdmissionAuthorized=False,
    scope='Known ten development pairs only; no fresh cases or generation seed.'), indent=2) + '\n')
with (C / 'single-qualification-controller.log').open('x') as log:
    run = subprocess.run(args, cwd=W, env=env, stdout=log, stderr=subprocess.STDOUT)
(C / 'single-qualification-command-exit.json').write_text(json.dumps(dict(
    exitCode=run.returncode, finishedAt=datetime.now(timezone.utc).isoformat(),
    output=str(output), secondAdmissionStarted=False), indent=2) + '\n')
print(json.dumps(dict(exitCode=run.returncode, output=str(output))))
raise SystemExit(run.returncode)
