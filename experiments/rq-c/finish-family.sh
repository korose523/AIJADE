#!/bin/sh
# After run-family.sh has finished: rebuild the Release tools (the run used them, so they are not rebuilt while it runs),
# recompute the model-based analysis with the second-family run included, run differential testing on it, and re-render
# the papers so that every p2.fam.* fact is available. Writing the control into P2 and its Chinese translation is left to the author's reading of
# the results: the differential classification in facts.py was made for the Qwen runs' tasks and must be checked against
# any new disagreeing task first.
set -eu
export DOTNET_ROOT="$HOME/.dotnet" PATH="$HOME/.dotnet:$PATH" DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
cd "$(dirname "$0")/../.."
run=${FAMILY_RUN:-experiments/rq-c/family-gpu/rq-c-s42-ollama-t30-r5}
[ -f "$run/summary.json" ] || { echo "no $run/summary.json yet: run-family.sh has not finished" >&2; exit 1; }
if pgrep -f "Aijade.Rqc.dll.*--out $(dirname "$run")( |$)" >/dev/null; then
  echo "the family run is still running" >&2; exit 1
fi
: "${AIJADE_ARTIFACTS:=$HOME/.cache/aijade-next-artifacts-gpu}"   # not the default one: the llava-phi3 run may still be using it
export AIJADE_ARTIFACTS
dotnet build tools/Aijade.Experiments -c Release
exp="$AIJADE_ARTIFACTS/bin/Aijade.Experiments/release/Aijade.Experiments.dll"
dotnet "$exp" p2-models
dotnet "$exp" differential --run "$run"
papers="$(cd ../docs/08_论文工程 && pwd)"
(cd "$papers" && python3 _工具/render.py && python3 _工具/figures.py && python3 _工具/稿件一致性守卫.py) || echo "the paper pipeline flagged something (see above)" >&2
python3 - "$run" <<'EOF'
import json, sys
s = json.load(open(f"{sys.argv[1]}/summary.json"))
d = json.load(open(f"{sys.argv[1]}/differential.json"))
print("abortedReplies:", (s.get("sampling") or {}).get("abortedReplies"), "lengthLimitedReplies:", (s.get("sampling") or {}).get("lengthLimitedReplies"))
models = json.load(open("experiments/rq-c/p2-models.json"))
m = models.get("second family (llama3.1:8b)", {})
print("first attempt (llava-phi3) verdict re-read:", {k: v for k, v in (models.get("second family, first attempt (llava-phi3)", {}).get("verdictFallback") or {}).items() if k not in ("diagnostics", "what")})
print("verdict re-read (exploratory):", {k: v for k, v in (m.get("verdictFallback") or {}).items() if k not in ("diagnostics", "what")})
print("guard:", (s.get("degeneracy") or {}).get("note", "")[:120])
print("differential:", d["candidates"], "candidates,", d["disagreeing"], "disagreeing")
for t in d["perTask"]:
    if t["disagreeing"]:
        print("  check against the instruction:", t["task"], t["disagreeing"], (t.get("examples") or [""])[0][:140])
EOF
