#!/usr/bin/env python3
"""Local smoke test for the AIJADE speech stack.

Verifies connectivity + the over-persona half-loop:
  * SenseVoice ASR  (:8000) -> transcription + detected emotion
  * IndexTTS2 TTS  (:8765) -> speech synthesis (multipart, emo_text)
  * CosyVoice-local (:9000, optional) -> Instruct emotion synthesis

Pure standard library (urllib + wave). Run on the real machine:

    python smoke_test.py --sample speech.wav --cosyvoice
    python smoke_test.py                       # auto-generates a tone if no --sample
"""
import argparse
import io
import os
import sys
import wave

try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:  # pragma: no cover
    from urllib2 import Request, urlopen, HTTPError, URLError


ASR_BASE = "http://localhost:8000"
TTS_BASE = "http://localhost:8765"
COSY_BASE = "http://localhost:9000"

BOUNDARY = "----airismokeboundary"


def _build_multipart(fields: dict, file_name: str, file_bytes: bytes, file_ct: str = "audio/wav", file_field: str = "file"):
    """Build a multipart/form-data body as pure bytes (no str/bytes mixing)."""
    parts = []
    for name, value in fields.items():
        if value is None:
            continue
        parts.append(("--" + BOUNDARY + "\r\n").encode("utf-8"))
        parts.append(
            ('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode("utf-8")
        )
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")
    # file part
    parts.append(("--" + BOUNDARY + "\r\n").encode("utf-8"))
    parts.append(
        ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (file_field, file_name)).encode("utf-8")
    )
    parts.append(("Content-Type: %s\r\n\r\n" % file_ct).encode("utf-8"))
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(("--" + BOUNDARY + "--\r\n").encode("utf-8"))
    return b"".join(parts)


def _post(url: str, body: bytes, headers: dict, timeout: int = 300):
    req = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except HTTPError as e:  # type: ignore
        return e.code, e.read()
    except URLError as e:  # type: ignore
        return -1, str(getattr(e, "reason", e)).encode("utf-8")


def _get(url: str, timeout: int = 10):
    try:
        with urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read()
    except HTTPError as e:  # type: ignore
        return e.code, e.read()
    except URLError as e:  # type: ignore
        return -1, str(getattr(e, "reason", e)).encode("utf-8")


def check_health(name: str, base: str, path: str = "/health") -> bool:
    status, _ = _get(base + path)
    ok = status == 200
    print(f"[{'OK ' if ok else 'FAIL'}] {name} health -> {status}")
    return ok


def make_tone_wav(seconds: float = 1.0, hz: int = 440, sr: int = 16000) -> bytes:
    import math

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = []
        for n in range(int(sr * seconds)):
            val = int(32767 * 0.3 * math.sin(2 * math.pi * hz * n / sr))
            frames.append(val)
        w.writeframes(b"".join((v.to_bytes(2, "little", signed=True) for v in frames)))
    return buf.getvalue()


def load_sample(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def test_asr(base: str, audio: bytes) -> bool:
    print("\n--- SenseVoice ASR (emotion) ---")
    check_health("SenseVoice ASR", base)
    body = _build_multipart(
        {"model": "iic/SenseVoiceSmall", "response_format": "verbose_json"},
        "sample.wav",
        audio,
    )
    status, resp = _post(
        f"{base}/v1/audio/transcriptions",
        body,
        {"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
        timeout=300,
    )
    if status != 200:
        print(f"[{'FAIL'}] transcription -> {status} {resp[:200]!r}")
        return False
    try:
        import json

        data = json.loads(resp.decode("utf-8"))
        print(f"[{'OK '}] transcription -> text={data.get('text')!r} "
              f"lang={data.get('language')!r} emotion={data.get('emotion')!r} "
              f"event={data.get('event')!r}")
        return True
    except Exception as e:  # noqa
        print(f"[{'FAIL'}] could not parse ASR json: {e} raw={resp[:200]!r}")
        return False


def test_tts(base: str, audio: bytes) -> bool:
    print("\n--- IndexTTS2 TTS (emo_text) ---")
    check_health("IndexTTS2 TTS", base, "/openapi.json")
    fields = {
        "model": "IndexTTS-1.5",
        "input": "Hello from AIJADE, I am smiling.",
        "voice": "default",
        "response_format": "wav",
        "emo_text": "happy and cheerful",
    }
    # IndexTTS2 tts_server uses multipart Form (voice_audio = reference voice,
    # emo_text = emotion description). voice_audio is REQUIRED for voice cloning.
    body = _build_multipart(fields, "ref.wav", audio, file_field="voice_audio")
    status, resp = _post(
        f"{base}/v1/audio/speech",
        body,
        {"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
        timeout=300,
    )
    ok = status == 200 and len(resp) > 44
    print(f"[{'OK ' if ok else 'FAIL'}] synthesize -> {status} ({len(resp)} bytes)")
    if ok:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_smoke_tts.wav"), "wb") as f:
            f.write(resp)
        print("      saved _smoke_tts.wav")
    else:
        print(f"      resp: {resp[:200]!r}")
    return ok


def test_cosyvoice(base: str, audio: bytes) -> bool:
    print("\n--- CosyVoice-local TTS (instruct) ---")
    check_health("CosyVoice-local", base, "/")
    fields = {
        "model": "CosyVoice-300M",
        "prompt": "Say this with a happy tone.",
        "input": "Hello from AIJADE.",
        "response_format": "wav",
    }
    body = _build_multipart(fields, "sample.wav", audio)
    status, resp = _post(
        f"{base}/v1/audio/speech",
        body,
        {"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
        timeout=300,
    )
    ok = status == 200 and len(resp) > 44
    print(f"[{'OK ' if ok else 'FAIL'}] cosyvoice instruct synth -> {status} ({len(resp)} bytes)")
    if ok:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_smoke_cosy.wav"), "wb") as f:
            f.write(resp)
        print("      saved _smoke_cosy.wav")
    return ok


def main():
    ap = argparse.ArgumentParser(description="AIJADE speech stack smoke test")
    ap.add_argument("--asr-base", default=ASR_BASE)
    ap.add_argument("--tts-base", default=TTS_BASE)
    ap.add_argument("--cosyvoice-base", default=COSY_BASE)
    ap.add_argument("--sample", default=None, help="WAV file to send (else a tone is generated)")
    ap.add_argument("--cosyvoice", action="store_true", help="also test CosyVoice-local")
    ap.add_argument("--skip-asr", action="store_true")
    ap.add_argument("--skip-tts", action="store_true")
    args = ap.parse_args()

    audio = load_sample(args.sample) if args.sample else make_tone_wav()

    results = []
    if not args.skip_asr:
        results.append(test_asr(args.asr_base, audio))
    if not args.skip_tts:
        results.append(test_tts(args.tts_base, audio))
    if args.cosyvoice:
        results.append(test_cosyvoice(args.cosyvoice_base, audio))

    print("\n=== SUMMARY ===")
    passed = sum(1 for r in results if r)
    print(f"{passed}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
