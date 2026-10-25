#!/bin/sh
# Fetch the third-party corpora into the paths the drivers read by default, and check each against the SHA-256 the code
# pins (P3: src/Aijade.Memory/Locomo/Locomo.cs, LongMemEval.cs; P2-A stage 0: tools/data/evalplus_compat.py). None is part
# of this repository; all are downloaded from their authors' release locations:
#   LoCoMo (snap-research/locomo, data/locomo10.json)                    -> ~/.local/share/aijade-data/locomo10.json
#   LongMemEval_s, cleaned (huggingface.co/datasets/xiaowu0162/longmemeval-cleaned, MIT)
#                                                                         -> ~/.local/share/aijade-data/longmemeval/longmemeval_s_cleaned.json
#   EvalPlus HumanEval+ v0.1.10 and MBPP+ v0.2.0 (github.com/evalplus, Apache-2.0)
#                                                                         -> ~/.local/share/aijade-data/evalplus/*.jsonl.gz
# A file that is already present and matches is left alone; a download that does not match is discarded, never installed.
#   usage: tools/data/fetch-corpora.sh [locomo|longmemeval|evalplus]     (default: both P3 corpora)
set -eu
dir="${AIJADE_DATA_DIR:-$HOME/.local/share/aijade-data}"

sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

fetch() { # name url target sha256
  name=$1 url=$2 target=$3 want=$4
  if [ -f "$target" ] && [ "$(sha256 "$target")" = "$want" ]; then
    echo "$name: present and verified ($target)"
    return 0
  fi
  mkdir -p "$(dirname "$target")"
  tmp="$target.download"
  echo "$name: downloading $url"
  curl -fL --retry 3 -o "$tmp" "$url"
  got="$(sha256 "$tmp")"
  if [ "$got" != "$want" ]; then
    rm -f "$tmp"
    echo "$name: SHA-256 mismatch (got $got, expected $want); nothing installed" >&2
    return 1
  fi
  mv "$tmp" "$target"
  echo "$name: installed and verified ($target)"
}

what="${1:-both}"
if [ "$what" = locomo ] || [ "$what" = both ]; then
  fetch LoCoMo https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json \
    "$dir/locomo10.json" 79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4
fi
if [ "$what" = longmemeval ] || [ "$what" = both ]; then
  fetch LongMemEval_s https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json \
    "$dir/longmemeval/longmemeval_s_cleaned.json" d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442
fi
if [ "$what" = evalplus ]; then
  fetch HumanEval+ https://github.com/evalplus/humanevalplus_release/releases/download/v0.1.10/HumanEvalPlus.jsonl.gz \
    "$dir/evalplus/HumanEvalPlus-v0.1.10.jsonl.gz" 272720b90ac375502c8ed23cd791c2a93dfb22a911641a494da74a426c09f101
  fetch MBPP+ https://github.com/evalplus/mbppplus_release/releases/download/v0.2.0/MbppPlus.jsonl.gz \
    "$dir/evalplus/MbppPlus-v0.2.0.jsonl.gz" af43697e8791c4c149bdfd6b489d8b5412507551ac20e28a439f650b8225db63
fi
