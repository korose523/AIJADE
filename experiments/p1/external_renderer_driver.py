#!/usr/bin/env python3
"""P1-C: runs the MOSAIC client's sessions and the cases on their receipts (experiments/plans/2026-11-06-p1-c-external-renderer.md).

Usage: external_renderer_driver.py <MOSAIC checkout, read only> <model.pmx> <new work dir> <built copy of this repo> <repo to archive into>
Needs AIJADE_TEST_DATABASE_URL. The client is copied into the work dir and built and run there; nothing is written to the MOSAIC checkout.
Each round: healthy, killed, old format, restarted. A healthy session that does not close its file is kept and one further session is run.
"""
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

ROUNDS = 3
MOSAIC_PYTHON = ".venv/bin/python"
COPIED = ["clients/godot-scene", "host-dotnet/Mosaic.Scene.Core", "host-dotnet/Mosaic.Scene.Bullet", "configs/scenes"]
REVISIONS = ["clients/godot-scene/Main.cs", "clients/godot-scene/BehaviorDriver.cs", "host-dotnet/Mosaic.Scene.Core/RenderStateLog.cs", "host-dotnet/Mosaic.Scene.Core/AijadePackets.cs",
             "host-dotnet/Mosaic.Scene.Core/BehaviorEvents.cs", "scripts/run-native-mmd-scene.py", "tools/make_companion_preset.py"]
METHOD = "Aijade.Tests.ExternalRendererStudyTests."


def main():
    mosaic, model, work, built, repo = (pathlib.Path(a).resolve() for a in sys.argv[1:6])
    work.mkdir(parents=True)
    dotnet_env = dict(os.environ, PATH=os.path.expanduser("~/.dotnet") + ":" + os.environ["PATH"], DOTNET_ROOT=os.path.expanduser("~/.dotnet"), DOTNET_PROCESSOR_COUNT="2", DOTNET_CLI_TELEMETRY_OPTOUT="1")
    client = work / "client-copy"
    for rel in COPIED:
        (client / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(mosaic / rel, client / rel, ignore=shutil.ignore_patterns(".godot", "bin", "obj"))
    (client / "scripts").mkdir()
    shutil.copy2(mosaic / "scripts/run-native-mmd-scene.py", client / "scripts")
    for name in ("global.json", "Directory.Build.props"):
        shutil.copy2(mosaic / name, client)
    sources = hashlib.sha256()
    for f in sorted(p for p in client.rglob("*") if p.is_file()):
        sources.update(f.relative_to(client).as_posix().encode() + b"\0" + f.read_bytes())
    revisions = {r: subprocess.run(["svn", "info", "--show-item", "last-changed-revision", str(mosaic / r)], capture_output=True, text=True).stdout.strip() for r in REVISIONS}
    preset = work / "preset"
    subprocess.run([str(mosaic / MOSAIC_PYTHON), "-B", str(mosaic / "tools/make_companion_preset.py"), "--out", str(preset), "--profile", "calm", "--seed", "7", "--duration-s", "40", "--preserve-signed"], check=True, stdout=subprocess.DEVNULL)
    rounds_dir = work / "rounds"
    rounds_dir.mkdir()
    dll = built / "tests/Aijade.Tests/bin/Release/net10.0/Aijade.Tests.dll"
    log = open(work / "run.log", "w", encoding="utf-8")

    def tests(selector, *names, **extra):
        args = ["dotnet", str(dll)]
        for n in names:
            args += [selector, n]
        r = subprocess.run(args, cwd=built, env=dict(dotnet_env, **extra), capture_output=True, text=True)
        log.write(r.stdout + r.stderr + "\n")
        log.flush()
        m = re.search(r"Total: (\d+), Errors: (\d+), Failed: (\d+), Skipped: (\d+)", r.stdout)
        return {"total": int(m[1]), "errors": int(m[2]), "failed": int(m[3]), "skipped": int(m[4])} if m else {"unparsed": r.stdout[-400:]}

    def start_client(out, session, **extra):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        env = dict(dotnet_env, MOSAIC_SESSION_ID=session, **extra)
        cmd = ["nice", "-n", "10", sys.executable, str(client / "scripts/run-native-mmd-scene.py"), "--headless", "--out", str(out), "--pmx", str(model), "--scale", "0.1", "--clip", str(preset / "companion-rest.vmd"),
               "--pose-mode", "pmx", "--preserve-signed-linear-weights", "--behavior", str(preset / "companion-plan.json"), "--behavior-live", str(port), "--timeout", "400"]
        proc = subprocess.Popen(cmd, cwd=client, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        ready = threading.Event()

        def pump():
            for line in proc.stdout:
                log.write(line)
                if "behaviour live inbox" in line:
                    ready.set()
        threading.Thread(target=pump, daemon=True).start()
        if not ready.wait(300):
            proc.kill()
            raise SystemExit(f"{session}: the client's inbox never opened; see run.log")
        time.sleep(1)
        return proc, port

    def send(d, session, port, file, first, last):
        got = tests("-method", METHOD + "Send_intents", AIJADE_P1C_SEND_DIR=str(d), AIJADE_P1C_SESSION=session, AIJADE_P1C_FILE=str(file), AIJADE_P1C_FROM=str(first), AIJADE_P1C_TO=str(last), AIJADE_P1C_PORT=str(port))
        if got.get("failed") != 0 or got.get("skipped") != 0:
            raise SystemExit(f"{session}: sending failed {got}")

    def seal(registry, file, manifest):
        got = tests("-method", METHOD + "Seal_session", AIJADE_P1C_SEAL_REGISTRY=str(registry), AIJADE_P1C_SEAL_FILE=str(file), AIJADE_P1C_SEAL_MANIFEST=str(manifest))
        if got.get("failed") != 0 or got.get("skipped") != 0:
            raise SystemExit(f"sealing failed {got} {manifest}")

    def kill_client():
        time.sleep(1)
        # The pattern must not start with a dash: pkill would read it as an option, and the session would simply end by itself.
        if subprocess.run(["pkill", "-9", "-f", f"path {client}/clients/godot-scene"], check=False).returncode != 0:
            raise SystemExit("the kill found no client")

    def must_be_unfinished(name, exit_code, file):
        last = file.read_text(encoding="utf-8").rstrip("\n").rsplit("\n", 1)[-1]
        if exit_code == 0 or '"record":"end"' in last:
            raise SystemExit(f"{name}: the kill did not take (exit {exit_code}); the session is not the case it should be")

    def plain_session(d, session, killed=False, **extra):
        d.mkdir()
        file = d / "client/aijade-render-state.jsonl"
        proc, port = start_client(d / "client", session, **extra)
        send(d, session, port, file, 1, 11)
        if killed:
            kill_client()
        exit_code = proc.wait(420)
        if killed:
            must_be_unfinished(session, exit_code, file)
        seal(d / "registry.jsonl", file, d / "manifest.json")
        return exit_code

    exits, replaced = {}, []
    started = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    for n in range(1, ROUNDS + 1):
        r = rounds_dir / f"r{n}"
        r.mkdir()
        sid = f"p1c-r{n}"
        exits[sid] = plain_session(r / "healthy", sid)
        if '"record":"end"' not in (r / "healthy/client/aijade-render-state.jsonl").read_text(encoding="utf-8").rsplit("\n", 2)[-2]:
            replaced.append(sid)
            (r / "healthy").rename(r / "healthy-unfinished")
            exits[sid + "-again"] = plain_session(r / "healthy", sid)
        exits[sid + "-killed"] = plain_session(r / "killed", sid + "-killed", killed=True)
        exits[sid + "-v1"] = plain_session(r / "v1", sid + "-v1", MOSAIC_RENDER_STATE_LOG="v1")
        d = r / "restart"
        d.mkdir()
        rid = sid + "-restart"
        proc, port = start_client(d / "client", rid)
        send(d, rid, port, d / "client/aijade-render-state.jsonl", 1, 5)
        kill_client()
        exits[rid + "-first"] = proc.wait(60)
        must_be_unfinished(rid, exits[rid + "-first"], d / "client/aijade-render-state.jsonl")
        proc, port = start_client(d / "client2", rid)
        send(d, rid, port, d / "client2/aijade-render-state.jsonl", 6, 11)
        exits[rid + "-second"] = proc.wait(420)
        seal(d / "registry.jsonl", d / "client/aijade-render-state.jsonl", d / "manifest.json")
        seal(d / "registry.jsonl", d / "client2/aijade-render-state.jsonl", d / "manifest-2.json")
        print(f"round {n} done {time.strftime('%H:%M')}", flush=True)

    core = client / "host-dotnet/Mosaic.Scene.Core/bin/Debug/net8.0/Mosaic.Scene.Core.dll"
    unchanged = {
        "ContractDriftMatrixTests": tests("-class", "Aijade.Tests.ContractDriftMatrixTests"),
        "AdmissionChecksTests": tests("-class", "Aijade.Tests.AdmissionChecksTests"),
    }
    conformance = tests("-class", "Aijade.Tests.RendererLinkTests", AIJADE_MOSAIC_CORE_DLL=str(core))
    cases = tests("-method", METHOD + "Cases_on_client_receipts", AIJADE_P1C_ROUNDS_DIR=str(rounds_dir), AIJADE_P1C_GOLDEN=str(built / "tests/Aijade.Tests/Golden/p1/contract-drift.txt"), AIJADE_EXPERIMENT_DIR=str(work))
    if cases.get("failed") != 0 or cases.get("skipped") != 0:
        raise SystemExit(f"the cases did not run: {cases}; see run.log")
    data = json.load(open(work / "external-renderer-cases.json", encoding="utf-8"))

    def tally(round_):
        g1, g2, g3 = round_["group1"], round_["group2"], round_["group3"]
        return {"round": round_["round"], "group1": {"assertions": g1["assertions"], "same": g1["same"], "different": g1["different"]},
                "group2": {"cases": len(g2), "same": sum(c["sameAsRecorded"] for c in g2)}, "group3": {"cases": len(g3), "same": sum(c["sameAsExpected"] for c in g3), "different": [c["case"] for c in g3 if not c["sameAsExpected"]]}}

    commit = subprocess.run(["git", "-C", str(built), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    plan = "experiments/plans/2026-11-06-p1-c-external-renderer.md"
    result = {
        "experiment": "P1-C: the evidence gate's checks on receipts from a separate renderer implementation by the same researcher",
        "plan": plan, "planCommit": subprocess.run(["git", "-C", str(built), "log", "-1", "--format=%h", "--", plan], capture_output=True, text=True).stdout.strip(), "runCommit": commit,
        "started": started, "ended": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "machine": "Mac, x86_64, 8 CPUs, 16 GB, other containers running", "database": "PostgreSQL 18.0",
        "client": {"mosaicFileRevisions": revisions, "sourcesSha256OfCopy": sources.hexdigest(), "copied": COPIED, "mode": "headless, no frame drawn"},
        "behaviorPlan": {"tool": "make_companion_preset.py --profile calm --seed 7 --duration-s 40 --preserve-signed", "archived": "experiments/p1/external-renderer/preset/"},
        "clientExitCodes": exits, "healthySessionsReplaced": replaced,
        "testsAtRunCommit": {**unchanged, "RendererLinkTestsWithBuiltParser": conformance},
        "tally": [tally(x) for x in data["rounds"]],
        "rounds": data["rounds"],
        "deviations": [
            "Departures from the draft of 4 November 2026 are listed in the plan's section 'Fixed on 6 November 2026', committed before the code.",
            "The plan was not pushed or sent to the supervisor before the code, by the first author's decision.",
            "A first pass (run commit 86f5818, 6 November 2026, 07:11 to 07:27) is discarded: the driver's kill never took, because pkill read its pattern as an option, so the killed sessions and the first instances of the restarted sessions closed their files normally. S1 and S5a then differed in all three rounds, with 11 and 5 receipts written from files that were complete; the other 45 cases of group 3, and groups 1 and 2, had their expected or recorded outcomes. The driver now stops if a kill does not take; all sessions were run again. The first pass is kept outside the repository, not reported.",
        ],
        "notes": [
            "Groups 1 and 2 use variants built from the client's healthy receipts and mostly re-test this system's server checks; qualification, the mapping from rows to receipt events and group 3 test the client and the new code.",
            "A row's applied values are the whole behavior overlay, so a receipt shows that a frame consumed the intent and which overlay values it had, not that each value came from the intent.",
            "One separate implementation by the same researcher, stage behavior_overlay_pre_solve, constructed cases, headless. Not an independent replication.",
        ],
    }
    target = repo / "experiments/p1"
    (target / "external-renderer.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    archive = target / "external-renderer"
    shutil.copytree(preset, archive / "preset")
    for f in sorted(rounds_dir.rglob("*")):
        if f.name in ("registry.jsonl", "manifest.json", "manifest-2.json", "aijade-render-state.jsonl"):
            to = archive / f.relative_to(rounds_dir)
            to.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, to)
    print(json.dumps({k: result[k] for k in ("runCommit", "client", "clientExitCodes", "healthySessionsReplaced", "testsAtRunCommit", "tally")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
