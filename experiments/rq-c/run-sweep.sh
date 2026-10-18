#!/bin/sh
# Runs the temperature sweep of temperature-sweep-plan.md (as amended), one run after another. A run that finished
# (summary.json) is skipped; a run that was interrupted is moved to sweep-1.5b/interrupted/<run> and resumed from its
# recorded generations (--resume-from), so the work already done is replayed rather than regenerated.
set -eu
export DOTNET_ROOT="$HOME/.dotnet" PATH="$HOME/.dotnet:$PATH" DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
cd "$(dirname "$0")/../.."
dll=$HOME/.cache/aijade-next-artifacts/bin/Aijade.Rqc/release/Aijade.Rqc.dll
base=experiments/rq-c/sweep-1.5b
for t in 0.4 0.8; do
  run=rq-c-s42-ollama-t30-r5-T$t
  [ -f "$base/$run/summary.json" ] && continue
  resume=""
  if [ -s "$base/$run/candidates.jsonl" ]; then
    # a later interruption supersedes an earlier one: its records already contain the replayed prefix
    mkdir -p "$base/interrupted"
    rm -rf "$base/interrupted/$run"
    mv "$base/$run" "$base/interrupted/$run"
  fi
  if [ -s "$base/interrupted/$run/candidates.jsonl" ]; then
    resume="--resume-from $base/interrupted/$run/candidates.jsonl"
  fi
  # shellcheck disable=SC2086
  dotnet "$dll" --backend ollama --model qwen2.5-coder:1.5b --trials 30 --rounds 5 --tasks 12 --seed 42 \
    --timeout-ms 600000 --ollama-base-url http://127.0.0.1:11434 --out "$base" --save-candidates --temperature "$t" $resume \
    >> "experiments/rq-c/run-1.5b-T$t.log" 2>&1
done
