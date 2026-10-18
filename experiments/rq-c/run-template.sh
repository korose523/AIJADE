#!/bin/sh
# P2 prompt-template control (registered 2026-10-18 in the papers workspace parts/PENDING.md before any run): the main model
# under the pre-registered design on the Windows GPU host over Tailscale, with the verifier prompt A (the pre-registered one)
# or B (the alternative wording). Both run on the same host, context 4096 and replies capped at 4096 tokens, so A on this
# host separates the template effect from the host effect. Output: experiments/rq-c/template-gpu/<A|B>/<run>. A stopped run is
# moved to <A|B>/interrupted/<run>-<time> and resumed from its record. Nothing is deleted.
#   usage: run-template.sh A|B
set -u
template="${1:?usage: run-template.sh A|B}"
export DOTNET_ROOT="$HOME/.dotnet" PATH="$HOME/.dotnet:$PATH" DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
cd "$(dirname "$0")/../.."
export AIJADE_ARTIFACTS="$HOME/.cache/aijade-next-artifacts-gpu"
dotnet build tools/Aijade.Rqc -c Release -v q || exit 1
dll=$AIJADE_ARTIFACTS/bin/Aijade.Rqc/release/Aijade.Rqc.dll
url="${AIJADE_OLLAMA_URL:?set AIJADE_OLLAMA_URL to the Ollama server, e.g. http://<host>:11434}"
model=qwen2.5-coder:7b-instruct
base=experiments/rq-c/template-gpu/$template
run=rq-c-s42-ollama-t30-r5
log=experiments/rq-c/run-template.log
mkdir -p "$base"
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
  echo "[$(date '+%F %T')] template $template attempt $attempt ${resume:+(resuming)}" >> "$log"
  # shellcheck disable=SC2086
  dotnet "$dll" --backend ollama --model "$model" --trials 30 --rounds 5 --tasks 12 --seed 42 \
    --timeout-ms 3600000 --ollama-base-url "$url" --out "$base" --save-candidates --max-reply-tokens 4096 --num-ctx 4096 \
    --verify-template "$template" $resume >> "$log" 2>&1 || sleep 60
done
[ -f "$base/$run/summary.json" ] || { echo "[$(date '+%F %T')] template $template did not finish after $attempt attempts" >> "$log"; exit 1; }
