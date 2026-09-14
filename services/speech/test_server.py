"""
Tests for the AIJADE voice proxy (sensevoice_asr_server.py).

Covers the new pieces added in the provider-abstraction + VAD-gate refactor:
  * detect_speech (VAD gate)
  * provider/model routing (resolve_asr)
  * VAD gate rejecting silence before the model runs
  * TTS proxy route (unconfigured -> 501, configured -> streamed bytes)

No funasr/GPU needed: the VAD gate short-circuits silence, and the TTS path
is exercised with a fake provider. The ASR model is never imported in these
tests (the lifespan preload is guarded).
"""
from __future__ import annotations

import io

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

import sensevoice_asr_server as srv


def make_wav(audio: np.ndarray, sr: int = 16000) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV")
    return buf.getvalue()


# --------------------------------------------------------------------------- VAD gate

def test_detect_speech_silence_is_false():
    sr = 16000
    silent = np.zeros(sr, dtype=np.float32)  # 1s of pure silence
    assert srv.detect_speech(silent, sr) is False


def test_detect_speech_too_short_is_false():
    sr = 16000
    tone = (0.5 * np.sin(2 * np.pi * 220 * np.arange(int(0.1 * sr)) / sr)).astype(np.float32)
    assert srv.detect_speech(tone, sr) is False  # 0.1s < min_duration 0.25s


def test_detect_speech_real_tone_is_true():
    sr = 16000
    t = np.arange(int(1.0 * sr)) / sr
    tone = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    assert srv.detect_speech(tone, sr) is True


# --------------------------------------------------------------------------- provider routing

def test_resolve_asr_explicit_provider():
    p = srv.resolve_asr("sensevoice/SenseVoiceSmall")
    assert p.name == "sensevoice"


def test_resolve_asr_bare_model_falls_back_to_default():
    assert srv.resolve_asr("SenseVoiceSmall") is srv._DEFAULT_ASR


def test_resolve_asr_unknown_provider_raises():
    try:
        srv.resolve_asr("unknown/x")
        raise AssertionError("expected ValueError for unknown provider")
    except ValueError:
        pass


# --------------------------------------------------------------------------- endpoint: VAD gate

def test_transcription_vad_gate_skips_model(monkeypatch):
    called = {"n": 0}

    def fake_transcribe(audio, sr, language=None):
        called["n"] += 1
        return {"text": "SHOULD_NOT_HAPPEN", "language": "en", "emotion": "neutral", "event": []}

    monkeypatch.setattr(srv._DEFAULT_ASR, "transcribe", fake_transcribe)
    client = TestClient(srv.app)
    wav = make_wav(np.zeros(16000, dtype=np.float32))
    resp = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("s.wav", wav, "audio/wav")},
        data={"model": "sensevoice/SenseVoiceSmall", "response_format": "json"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == ""
    assert body["language"] == "nospeech"
    assert called["n"] == 0  # model was never invoked on silence


# --------------------------------------------------------------------------- endpoint: TTS proxy

def test_tts_unconfigured_returns_501():
    client = TestClient(srv.app)
    resp = client.post("/v1/audio/speech", data={"input": "hello", "voice": "default"})
    assert resp.status_code == 501
    assert "not configured" in resp.json()["error"]


def test_tts_proxy_streams_bytes(monkeypatch):
    class FakeTTS(srv.BaseTTSProvider):
        name = "fake"

        def synthesize(self, text, voice, response_format="mp3", **kw):
            return (b"WAVEDATA-" + text.encode()), "audio/wav"

    monkeypatch.setattr(srv, "_TTS_PROVIDER", FakeTTS())
    client = TestClient(srv.app)
    resp = client.post(
        "/v1/audio/speech",
        data={"model": "fake/x", "input": "hi", "voice": "v", "response_format": "wav"},
    )
    assert resp.status_code == 200
    assert resp.content == b"WAVEDATA-hi"
    assert resp.headers["content-type"] == "audio/wav"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
