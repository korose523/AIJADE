#!/usr/bin/env bash
# Launch the local speech stack (ASR + TTS).
# SenseVoice ASR is served from this folder; IndexTTS2 from its own checkout.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INDEX_TTS_VENV="${INDEX_TTS_VENV:-/d/项目/index-tts/.venv}"
ASR_VENV="${ASR_VENV:-$HERE/venv}"

# Pick the first python that can actually import uvicorn + funasr.
# The local ASR venv ($HERE/venv) is sometimes incomplete on this machine,
# so we fall back to the IndexTTS2 venv where funasr was installed.
PY=""
for cand in "$ASR_VENV/Scripts/python" "$ASR_VENV/bin/python" "$INDEX_TTS_VENV/Scripts/python" python; do
  if [ -x "$cand" ] && "$cand" -c "import uvicorn, funasr" >/dev/null 2>&1; then
    PY="$cand"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "ERROR: no python with uvicorn+funasr found (tried $ASR_VENV, $INDEX_TTS_VENV)" >&2
  exit 1
fi
echo ">> Using ASR python: $PY"

echo ">> Starting SenseVoice ASR on :8000"
"$PY" -m uvicorn sensevoice_asr_server:app --host 0.0.0.0 --port 8000 --log-level info &

echo ">> Starting IndexTTS2 TTS on :8765"
"$INDEX_TTS_VENV/Scripts/python" -m uvicorn tts_server:app --host 0.0.0.0 --port 8765 --log-level info \
  --app-dir "/d/项目/index-tts" &

wait
