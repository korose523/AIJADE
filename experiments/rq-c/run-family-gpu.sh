#!/bin/sh
# Second-family control for P2, second attempt (rule fixed 2026-10-18, see the papers workspace parts/PENDING.md): the
# pre-registered design (trials 30, rounds 5, tasks 12, seed 42, temperature 0, warm-up request, strict verdict rule) with
# the model that passed the verdict-format pre-check, served by Ollama on a second host (the paper's: Windows, RTX 5080, Ollama 0.40.0, reached over Tailscale).
# Replies are capped at 4096 tokens and the context window is set to 4096 tokens (the default of the Ollama 0.35 host of
# the earlier runs; Ollama 0.40 would otherwise load Llama 3.1's 131072-token context) from the first step. The runner is built into its own artifacts directory so that the
# llava-phi3 run on this Mac (which uses the default one) is not disturbed. A stopped run is moved to
# rq-c/family-gpu/interrupted/<run>-<time> and resumed from its record. Nothing is deleted.
#   usage: run-family-gpu.sh <model>     e.g. run-family-gpu.sh deepseek-coder:6.7b-instruct
set -u
model="${1:?usage: run-family-gpu.sh <model>}"
export DOTNET_ROOT="$HOME/.dotnet" PATH="$HOME/.dotnet:$PATH" DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
cd "$(dirname "$0")/../.."
export AIJADE_ARTIFACTS="$HOME/.cache/aijade-next-artifacts-gpu"
dotnet build tools/Aijade.Rqc -c Release -v q || exit 1
dll=$AIJADE_ARTIFACTS/bin/Aijade.Rqc/release/Aijade.Rqc.dll
url="${AIJADE_OLLAMA_URL:?set AIJADE_OLLAMA_URL to the Ollama server, e.g. http://<host>:11434}"
base=experiments/rq-c/family-gpu
run=rq-c-s42-ollama-t30-r5
log=experiments/rq-c/run-family-gpu.log
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
  echo "[$(date '+%F %T')] attempt $attempt model $model ${resume:+(resuming)}" >> "$log"
  # shellcheck disable=SC2086
  dotnet "$dll" --backend ollama --model "$model" --trials 30 --rounds 5 --tasks 12 --seed 42 \
    --timeout-ms 3600000 --ollama-base-url "$url" --out "$base" --save-candidates --max-reply-tokens 4096 --num-ctx 4096 $resume \
    >> "$log" 2>&1 || sleep 60
done
[ -f "$base/$run/summary.json" ] || { echo "[$(date '+%F %T')] did not finish after $attempt attempts" >> "$log"; exit 1; }
