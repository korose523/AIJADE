#!/bin/sh
# Second-family control for P2 (exploratory): the pre-registered design (trials 30, rounds 5, tasks 12, seed 42,
# temperature 0, warm-up request) with a Phi-3 based model instead of Qwen. llava-phi3 is a vision-language model built on
# Phi-3-mini; it is the only non-Qwen chat model on this machine, which the paper states as a caveat. A stopped run is
# moved to rq-c/family/interrupted/<run>-<time> and resumed from its recorded generations (each replayed step is checked
# against the record). Nothing is deleted.
# ABANDONED on 2026-10-18 (see family/ABANDONED.md): the model's verifier ignores the PASS/FAIL-first format, so under the
# pre-registered rule every verdict is FAIL; the control was rerun with llama3.1:8b (run-family-gpu.sh).
# Replies were capped at 4096 tokens from step 1608 on, after a restart; no reply before that point is longer than 834
# characters. Step 1620 had generated for 16 minutes until Ollama's repetition abort ended it, and the resumed run
# reproduced it exactly.
set -u
export DOTNET_ROOT="$HOME/.dotnet" PATH="$HOME/.dotnet:$PATH" DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
cd "$(dirname "$0")/../.."
dll=$HOME/.cache/aijade-next-artifacts/bin/Aijade.Rqc/release/Aijade.Rqc.dll
base=experiments/rq-c/family
model=llava-phi3:latest
run=rq-c-s42-ollama-t30-r5
log=experiments/rq-c/run-family.log
# resume from the newest interrupted record when the run directory has none of its own (e.g. a crash at start-up)
latest="$(ls -td "$base"/interrupted/"$run"-* 2>/dev/null | head -1)"
attempt=0
while [ ! -f "$base/$run/summary.json" ] && [ "$attempt" -lt 30 ]; do
  attempt=$((attempt + 1))
  if [ -s "$base/$run/candidates.jsonl" ]; then
    mkdir -p "$base/interrupted"
    latest="$base/interrupted/$run-$(date '+%Y%m%d-%H%M%S')"
    mv "$base/$run" "$latest"
  fi
  resume=""
  if [ -n "$latest" ] && [ -s "$latest/candidates.jsonl" ]; then resume="--resume-from $latest/candidates.jsonl"; fi
  echo "[$(date '+%F %T')] attempt $attempt ${resume:+(resuming)}" >> "$log"
  # shellcheck disable=SC2086
  dotnet "$dll" --backend ollama --model "$model" --trials 30 --rounds 5 --tasks 12 --seed 42 \
    --timeout-ms 3600000 --ollama-base-url http://127.0.0.1:11434 --out "$base" --save-candidates --max-reply-tokens 4096 $resume \
    >> "$log" 2>&1 || sleep 60
done
[ -f "$base/$run/summary.json" ] || { echo "[$(date '+%F %T')] did not finish after $attempt attempts" >> "$log"; exit 1; }
