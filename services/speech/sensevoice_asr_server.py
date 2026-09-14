"""
SenseVoice (FunASR) OpenAI-compatible ASR + TTS-proxy server.

Exposes an OpenAI-compatible surface so it can be dropped into AIJADE's
voice providers:

    POST /v1/audio/transcriptions   ASR  (speech -> text + rich tags)
    POST /v1/audio/speech           TTS  (text  -> audio, provider-abstracted proxy)
    GET  /v1/models                 capability listing (ASR + TTS)
    GET  /health                    liveness + load state

Design notes (grounded in ecosystem references):
  * unspeech: a unified, OpenAI-compatible voice proxy. We mirror its
    `provider/model` routing — the ASR provider is selected by the `model`
    field (`sensevoice/SenseVoiceSmall`); TTS is a provider-abstracted proxy
    behind `TTS_BASE_URL`.
  * WebAI realtime-voice: a VAD-first pipeline (VAD -> STT -> LLM -> TTS).
    We add a lightweight VAD gate at the API edge so silent / too-short
    uploads are rejected *before* they hit the model (no spurious
    transcriptions, no wasted GPU).

Beyond plain text, ASR returns the rich SenseVoice tags (language / emotion /
audio-event) when `response_format=verbose_json` — the half of the
"over-persona" loop that feeds the *listener's* emotion back into the LLM
conversation context.

License: FunASR is MIT; the SenseVoiceSmall model weights carry a separate
Model License Agreement from ModelScope — review before redistribution.
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Optional

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

DEFAULT_MODEL_ID = os.getenv("SENSEVOICE_MODEL_ID", "iic/SenseVoiceSmall")
# This project is GPU self-host, so default to "cuda". funasr 1.3.14 rejects
# the string "auto" as a device, which previously crashed startup — override
# with SENSEVOICE_DEVICE=cpu (or any torch device string) if needed.
DEVICE = os.getenv("SENSEVOICE_DEVICE", "cuda")

_model_loaded_at: Optional[float] = None


# ---------------------------------------------------------------------------
# Rich-tag parsing (mirrors test_parse_rich.py — kept in sync)
# ---------------------------------------------------------------------------

_LANG_MAP = {
    "<|zh|>": "zh",
    "<|en|>": "en",
    "<|yue|>": "yue",
    "<|ja|>": "ja",
    "<|ko|>": "ko",
    "<|nospeech|>": "nospeech",
}

_EMO_MAP = {
    "<|NEUTRAL|>": "neutral",
    "<|HAPPY|>": "happy",
    "<|SAD|>": "sad",
    "<|ANGRY|>": "angry",
    "<|FEARFUL|>": "fearful",
    "<|DISGUSTED|>": "disgusted",
    "<|SURPRISED|>": "surprised",
}

# Audio-event tags we surface (everything else inside <|...|> is ignored).
_EVENT_TAGS = {
    "<|Speech|>",
    "<|BGM|>",
    "<|Applause|>",
    "<|Laughter|>",
    "<|Cry|>",
    "<|Sneeze|>",
    "<|Breath|>",
}


def _parse_rich(text: str):
    """Strip SenseVoice rich tokens and return (text, language, emotion, event).

    SenseVoice emits a leading sequence of tags such as
    ``<|zh|><|NEUTRAL|><|Speech|>...`` followed by the transcribed text.
    Tags after the first text token are treated as audio events.
    """
    import re

    language = "unknown"
    emotion = "neutral"
    events: list[str] = []
    cleaned_parts: list[str] = []

    # Split on any <|...|> token.
    for token in re.split(r"(<\|[^|]+\|>)", text):
        if not token:
            continue
        if token.startswith("<|") and token.endswith("|>"):
            tag = token.strip()
            if tag in _LANG_MAP:
                language = _LANG_MAP[tag]
            elif tag in _EMO_MAP:
                emotion = _EMO_MAP[tag]
            elif tag in _EVENT_TAGS:
                events.append(tag[2:-2])  # strip <| and |>
            # unknown tags are dropped
            continue
        # Plain text fragment.
        cleaned_parts.append(token)

    clean_text = "".join(cleaned_parts).strip()
    return clean_text, language, emotion, events


# ---------------------------------------------------------------------------
# VAD gate (WebAI realtime-voice: VAD-first)
# ---------------------------------------------------------------------------

def detect_speech(
    audio: np.ndarray,
    sr: int,
    *,
    min_duration_s: float = 0.25,
    min_rms: float = 1e-4,
) -> bool:
    """Return True if `audio` looks like real speech worth transcribing.

    Cheap pre-filter applied *before* the ASR model runs: drops silence and
    clips that are too short to carry a sentence, so the GPU is not wasted on
    ``<|nospeech|>`` results (WebAI's VAD -> STT ordering, at the API edge).
    """
    if audio.size == 0:
        return False
    if audio.shape[0] / float(sr) < min_duration_s:
        return False
    rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float64)))))
    return rms >= min_rms


# ---------------------------------------------------------------------------
# ASR provider abstraction (unspeech: provider/model routing)
# ---------------------------------------------------------------------------

class BaseASRProvider:
    """Interface every ASR backend implements."""

    name = "base"

    def is_loaded(self) -> bool:
        return False

    def transcribe(self, audio: np.ndarray, sr: int, language: Optional[str] = None) -> dict:
        raise NotImplementedError


class SenseVoiceProvider(BaseASRProvider):
    """Default backend: FunASR SenseVoiceSmall (+ fsmn-vad)."""

    name = "sensevoice"

    def __init__(self, device: str = DEVICE, model_id: str = DEFAULT_MODEL_ID):
        self._device = device
        self._model_id = model_id
        self._model = None

    def _ensure(self):
        if self._model is None:
            from funasr import AutoModel

            self._model = AutoModel(
                model=self._model_id,
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                device=self._device,
                disable_update=True,
                hub="modelscope",
            )
        return self._model

    def is_loaded(self) -> bool:
        return self._model is not None

    def transcribe(self, audio: np.ndarray, sr: int, language: Optional[str] = None) -> dict:
        model_inst = self._ensure()
        res = model_inst.generate(input=audio, language=language, batch_size=1)
        raw_text = res[0]["text"] if isinstance(res, list) and res else str(res)
        text, lang, emotion, events = _parse_rich(raw_text)
        return {"text": text, "language": lang, "emotion": emotion, "event": events}


# Provider registry. Add new backends here (e.g. whisper) without touching
# the endpoint. Route key = the `provider` segment of `provider/model`.
_DEFAULT_ASR = SenseVoiceProvider()
_ASR_REGISTRY: dict[str, BaseASRProvider] = {"sensevoice": _DEFAULT_ASR}


def resolve_asr(model: str) -> BaseASRProvider:
    """Pick an ASR provider from the OpenAI-style `model` field.

    ``sensevoice/SenseVoiceSmall`` -> SenseVoice; a bare ``SenseVoiceSmall``
    (no ``/``) falls back to the default provider. Unknown provider -> raise.
    """
    if "/" in model:
        provider, _ = model.split("/", 1)
        if provider not in _ASR_REGISTRY:
            raise ValueError(f"unknown ASR provider: {provider!r} (known: {sorted(_ASR_REGISTRY)})")
        return _ASR_REGISTRY[provider]
    return _DEFAULT_ASR


# ---------------------------------------------------------------------------
# TTS provider abstraction (unspeech: unified /audio/speech proxy)
# ---------------------------------------------------------------------------

class BaseTTSProvider:
    """Interface every TTS backend implements."""

    name = "base"

    def synthesize(self, text: str, voice: Optional[str], response_format: str = "mp3", **kwargs):
        """Return (audio_bytes, content_type)."""
        raise NotImplementedError


class HTTPTTSProvider(BaseTTSProvider):
    """Proxy to an HTTP TTS backend (e.g. IndexTTS2).

    The exact path is configurable via ``TTS_PATH`` (default ``/tts``) so it
    can target whatever the backend exposes without code changes.
    """

    name = "http"

    def __init__(self, base_url: str, path: str = "/tts"):
        self.base_url = base_url.rstrip("/")
        self.path = path

    def synthesize(self, text: str, voice: Optional[str], response_format: str = "mp3", **kwargs):
        import httpx

        resp = httpx.post(
            f"{self.base_url}{self.path}",
            json={"text": text, "voice": voice, "format": response_format, **kwargs},
            timeout=60,
        )
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "audio/mpeg")
        return resp.content, ctype


_TTS_PROVIDER: Optional[BaseTTSProvider] = None
_tts_base_url = os.getenv("TTS_BASE_URL")
if _tts_base_url:
    _TTS_PROVIDER = HTTPTTSProvider(_tts_base_url, os.getenv("TTS_PATH", "/tts"))


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app):
    # Preload the default ASR model once at startup. get_model() is a
    # *synchronous* torch load; doing it here (before the server accepts
    # traffic) avoids blocking the event loop on the first request. Guarded so
    # the server can still boot (for TTS routing / health) in environments
    # without the ASR deps installed.
    global _model_loaded_at
    try:
        _DEFAULT_ASR._ensure()
        _model_loaded_at = time.time()
    except Exception as e:  # pragma: no cover - environment dependent
        print(f"[warn] ASR model preload skipped: {e}")
    yield


app = FastAPI(title="AIJADE Voice Proxy (ASR + TTS, OpenAI-compatible)", lifespan=lifespan)


class TranscriptionVerbose(BaseModel):
    text: str
    language: str
    emotion: str
    event: list[str]
    model: str


@app.get("/health")
def health():
    return {
        "status": "ok",
        "asr_loaded": _DEFAULT_ASR.is_loaded(),
        "asr_model": DEFAULT_MODEL_ID,
        "tts_configured": _TTS_PROVIDER is not None,
    }


@app.get("/v1/models")
def list_models():
    data = [
        {
            "id": DEFAULT_MODEL_ID,
            "object": "model",
            "owned_by": "funasr",
            "created": int(_model_loaded_at) if _model_loaded_at else None,
            "type": "asr",
        }
    ]
    if _TTS_PROVIDER is not None:
        data.append(
            {
                "id": os.getenv("TTS_MODEL_ID", "tts-proxy/default"),
                "object": "model",
                "owned_by": _TTS_PROVIDER.name,
                "type": "tts",
            }
        )
    return {"object": "list", "data": data}


@app.post("/v1/audio/transcriptions")
async def create_transcription(
    file: UploadFile = File(...),
    model: str = Form(DEFAULT_MODEL_ID),
    response_format: str = Form("json"),
    language: Optional[str] = Form(None),
    temperature: float = Form(0.0),
):
    # Read audio into a numpy float32 array @ 16kHz mono.
    raw = await file.read()
    audio, sr = sf.read(BytesIO(raw), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != 16000:
        # Lightweight resample fallback (funasr expects 16k).
        try:
            import librosa

            audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
            sr = 16000
        except Exception:
            pass

    # VAD gate (WebAI: VAD before STT). Reject silence / too-short clips
    # without invoking the model.
    if not detect_speech(audio, sr):
        payload = {"text": "", "language": "nospeech", "emotion": "neutral", "event": []}
        if response_format == "verbose_json":
            return TranscriptionVerbose(**payload, model=model)
        if response_format == "text":
            return PlainTextResponse("")
        return JSONResponse(payload)

    provider = resolve_asr(model)
    result = await asyncio.to_thread(provider.transcribe, audio, sr, language)

    text = result["text"]
    lang = result["language"]
    emotion = result["emotion"]
    events = result["event"]

    if response_format == "verbose_json":
        return TranscriptionVerbose(text=text, language=lang, emotion=emotion, event=events, model=model)
    if response_format == "text":
        return PlainTextResponse(text)
    # default "json"
    return JSONResponse({"text": text, "language": lang, "emotion": emotion, "event": events})


@app.post("/v1/audio/speech")
async def create_speech(
    model: str = Form("tts-proxy/default"),
    input: str = Form(...),
    voice: Optional[str] = Form(None),
    response_format: str = Form("mp3"),
):
    if _TTS_PROVIDER is None:
        return JSONResponse(
            {
                "error": "TTS backend not configured",
                "hint": "set TTS_BASE_URL (and optionally TTS_PATH) to enable /v1/audio/speech",
            },
            status_code=501,
        )
    audio_bytes, ctype = await asyncio.to_thread(
        _TTS_PROVIDER.synthesize, input, voice, response_format
    )
    return Response(content=audio_bytes, media_type=ctype)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("SENSEVOICE_HOST", "0.0.0.0"),
        port=int(os.getenv("SENSEVOICE_PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
