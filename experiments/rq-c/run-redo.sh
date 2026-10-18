#!/bin/sh
# Runs the P2 experiments of the 7B model: the main run and the inert negative control, with the pre-registered parameters
# (trials 30, rounds 5, tasks 12, seed 42, temperature 0) plus the warm-up request. A finished run (summary.json) is
# skipped. If a run stops (e.g. a request exceeds the timeout on a saturated machine), the partial run is moved to
# rq-c/redo/interrupted/<run> and resumed from its recorded generations; the runner checks every replayed step
# against the record. Up to 30 attempts per run, one minute apart. The per-request timeout is not part of the fingerprint.
set -u
export DOTNET_ROOT="$HOME/.dotnet" PATH="$HOME/.dotnet:$PATH" DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
cd "$(dirname "$0")/../.."
dll=$HOME/.cache/aijade-next-artifacts/bin/Aijade.Rqc/release/Aijade.Rqc.dll
base=experiments/rq-c/redo
for spec in "main:" "inert:--inert"; do
  name=${spec%%:*}; extra=${spec#*:}
  run=rq-c-s42-ollama-t30-r5
  if [ -n "$extra" ]; then run="$run-INERT"; fi
  attempt=0
  while [ ! -f "$base/$run/summary.json" ] && [ "$attempt" -lt 30 ]; do
    attempt=$((attempt + 1))
    resume=""
    if [ -s "$base/$run/candidates.jsonl" ]; then
      mkdir -p "$base/interrupted"
      new=$(wc -l < "$base/$run/candidates.jsonl"); old=0
      if [ -s "$base/interrupted/$run/candidates.jsonl" ]; then old=$(wc -l < "$base/interrupted/$run/candidates.jsonl"); fi
      if [ "$new" -ge "$old" ]; then
        rm -rf "$base/interrupted/$run.prev"; [ -d "$base/interrupted/$run" ] && mv "$base/interrupted/$run" "$base/interrupted/$run.prev"
        mv "$base/$run" "$base/interrupted/$run"
      else
        rm -rf "$base/interrupted/$run.short"; mv "$base/$run" "$base/interrupted/$run.short"   # shorter than the record: keep the record
      fi
    fi
    if [ -s "$base/interrupted/$run/candidates.jsonl" ]; then resume="--resume-from $base/interrupted/$run/candidates.jsonl"; fi
    echo "[$(date '+%F %T')] $name attempt $attempt ${resume:+(resuming)}" >> "experiments/rq-c/run-7b-$name.log"
    # shellcheck disable=SC2086
    dotnet "$dll" --backend ollama --model qwen2.5-coder:7b-instruct --trials 30 --rounds 5 --tasks 12 --seed 42 \
      --timeout-ms 3600000 --ollama-base-url http://127.0.0.1:11434 --out "$base" --save-candidates $extra $resume \
      >> "experiments/rq-c/run-7b-$name.log" 2>&1 || sleep 60
  done
  if [ ! -f "$base/$run/summary.json" ]; then
    echo "[$(date '+%F %T')] $name did not finish after $attempt attempts" >> "experiments/rq-c/run-7b-$name.log"
    exit 1
  fi
done
# Determinism pre-check with a positive control on the same model, after the runs (its research sampling profile uses a
# larger context window, which would make the server reload the model if it were interleaved with a run).
dotnet "$HOME/.cache/aijade-next-artifacts/bin/Aijade.Substrate/release/Aijade.Substrate.dll" verify --model qwen2.5-coder:7b-instruct \
  --runs 5 --seed-strategy varied --control --out experiments/rq-c/determinism-7b.json >> experiments/rq-c/run-7b-main.log 2>&1 || true
