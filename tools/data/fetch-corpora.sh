#!/bin/sh
# Fetch the two third-party corpora of the P3 memory experiments into the paths the drivers read by default, and check each
# against the SHA-256 the code pins (src/Aijade.Memory/Locomo/Locomo.cs, LongMemEval.cs). Neither corpus is part of this
# repository; both are downloaded from their authors' release locations:
#   LoCoMo (snap-research/locomo, data/locomo10.json)                    -> ~/.local/share/aijade-data/locomo10.json
#   LongMemEval_s, cleaned (huggingface.co/datasets/xiaowu0162/longmemeval-cleaned, MIT)
#                                                                         -> ~/.local/share/aijade-data/longmemeval/longmemeval_s_cleaned.json
# A file that is already present and matches is left alone; a download that does not match is discarded, never installed.
#   usage: tools/data/fetch-corpora.sh [locomo|longmemeval]     (default: both)
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
