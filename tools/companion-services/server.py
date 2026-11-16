#!/usr/bin/env python3
"""AIJADE-owned loopback speech service; no MOSAIC source, launchers or runtime required."""
from __future__ import annotations

import argparse
import base64
import binascii
from contextlib import contextmanager
import importlib.util
import io
import ipaddress
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import wave

MAX_TEXT = 2000
MAX_WAV = 4 << 20
MAX_BODY = 6 << 20
EMOTIONS = {"neutral", "happy", "calm", "curious"}
LANGUAGES = {"auto": None, "Chinese": "zh", "English": "en", "Japanese": "ja", "Korean": "ko"}


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def loopback(host: str) -> str:
    host = "127.0.0.1" if host == "localhost" else host
    try:
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError("Only a loopback listen address is allowed")
    except ValueError as error:
        raise ValueError("Only a numeric loopback address or localhost is allowed") from error
    return host


def within(path: Path, root: Path) -> Path:
    path, root = path.resolve(), root.resolve()
    if path != root and root not in path.parents:
        raise ValueError("Service state and local models must stay inside the AIJADE workspace")
    return path


def wav_info(data: bytes) -> tuple[float, int]:
    if not data or len(data) > MAX_WAV:
        raise ServiceError(400, "INVALID_AUDIO", "A WAV of 1 byte to 4 MiB is required")
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            if frames <= 0 or rate <= 0 or audio.getnchannels() not in (1, 2) or audio.getsampwidth() not in (1, 2, 3, 4):
                raise ValueError("Unsupported PCM WAV")
            expected = frames * audio.getnchannels() * audio.getsampwidth()
            if len(audio.readframes(frames)) != expected or frames / rate > 120:
                raise ValueError("Truncated WAV or duration above two minutes")
            return frames / rate, rate
    except (wave.Error, EOFError, ValueError) as error:
        raise ServiceError(400, "INVALID_AUDIO", "A complete PCM WAV of at most two minutes is required") from error


def check_cancel(cancel: threading.Event):
    if cancel.is_set():
        raise ServiceError(499, "CANCELLED", "The request was cancelled")


class Commands:
    """Only processes started by this request are terminated on cancellation or timeout."""
    def run(self, command: list[str], deadline: float, cancel: threading.Event, directory: Path):
        check_cancel(cancel)
        environment = dict(os.environ, TMPDIR=str(directory), TMP=str(directory), TEMP=str(directory))
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, shell=False, env=environment, cwd=directory)
        except OSError as error:
            raise ServiceError(503, "ENGINE_UNAVAILABLE", "The configured system speech command is unavailable") from error
        try:
            while process.poll() is None:
                check_cancel(cancel)
                if time.monotonic() >= deadline:
                    raise ServiceError(504, "ENGINE_TIMEOUT", "The system speech command exceeded its request limit")
                cancel.wait(min(0.05, max(0, deadline - time.monotonic())))
            check_cancel(cancel)
            if process.returncode:
                raise ServiceError(502, "ENGINE_FAILED", "The system speech command failed")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)


class LocalServices:
    def __init__(self, workspace: Path, state: Path, *, voice: str | None = None,
                 asr_model: Path | None = None, timeout: float = 30, commands=None, asr_factory=None):
        if not 0 < timeout <= 120:
            raise ValueError("Engine timeout must be greater than zero and at most 120 seconds")
        self.workspace = workspace.resolve()
        self.state = within(state, self.workspace)
        self.model_path = within(asr_model, self.workspace) if asr_model is not None else None
        if self.model_path is not None and not self.model_path.is_dir():
            raise ValueError("--asr-model must be an existing local model directory")
        if self.model_path is not None:
            self.validate_model()
        self.voice, self.timeout = voice, timeout
        self.commands = commands or Commands()
        self.asr_factory, self.model = asr_factory, None
        self.asr_lock = threading.Lock()
        self.events_lock = threading.Lock()
        self.request_gate = threading.BoundedSemaphore(2)
        self.events: set[threading.Event] = set()
        self.tts_verified = self.asr_verified = False
        self.state.mkdir(parents=True, exist_ok=True)

    def validate_model(self):
        # faster-whisper can otherwise fetch a fallback tokenizer even when the weights came from a local directory.
        for name in ("model.bin", "tokenizer.json", "config.json"):
            if not within(self.model_path / name, self.workspace).is_file():
                raise ValueError("The existing local ASR directory must include model.bin, tokenizer.json and config.json")

    def health(self):
        return {"ok": True, "service": "aijade-companion-services", "version": 1,
                "speech": {"configured": True, "available": bool(shutil.which("say") and shutil.which("afconvert")),
                           "engine": "macos-system-say", "voice": self.voice or "system-default",
                           "trainingVerified": False, "runtimeVerified": self.tts_verified,
                           "emotionApplied": False},
                "transcription": {"configured": self.model_path is not None,
                                  "dependencyAvailable": importlib.util.find_spec("faster_whisper") is not None,
                                  "modelLoaded": self.model is not None, "runtimeVerified": self.asr_verified,
                                  "automaticDownload": False},
                "alignment": {"available": False, "status": "not_implemented"},
                "singing": {"available": False, "status": "not_implemented"}}

    @contextmanager
    def request(self, cancel: threading.Event):
        if not self.request_gate.acquire(blocking=False):
            raise ServiceError(503, "SERVICE_BUSY", "Two local requests are already running")
        with self.events_lock:
            self.events.add(cancel)
        try:
            yield
        finally:
            with self.events_lock:
                self.events.discard(cancel)
            self.request_gate.release()

    def cancel_all(self):
        with self.events_lock:
            for event in self.events:
                event.set()

    def speak(self, request: dict, cancel: threading.Event) -> bytes:
        if set(request) - {"text", "emotion"} or not isinstance(request.get("text"), str):
            raise ServiceError(400, "INVALID_REQUEST", "Only text and optional emotion fields are accepted")
        text, emotion = request["text"], request.get("emotion", "neutral")
        if not text.strip() or len(text) > MAX_TEXT or "\0" in text or not isinstance(emotion, str) or emotion not in EMOTIONS:
            raise ServiceError(400, "INVALID_REQUEST", "Text must contain 1-2000 characters and emotion must be supported")
        check_cancel(cancel)
        deadline = time.monotonic() + self.timeout
        with tempfile.TemporaryDirectory(prefix="tts-", dir=self.state) as temporary:
            directory = Path(temporary)
            source, intermediate, output = directory / "text.txt", directory / "speech.aiff", directory / "speech.wav"
            source.write_text(text, encoding="utf-8")
            command = ["/usr/bin/say", "-f", str(source), "-o", str(intermediate)]
            if self.voice:
                command += ["-v", self.voice]
            self.commands.run(command, deadline, cancel, directory)
            self.commands.run(["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16", str(intermediate), str(output)], deadline, cancel, directory)
            check_cancel(cancel)
            try:
                if output.stat().st_size > MAX_WAV:
                    raise ServiceError(502, "INVALID_ENGINE_AUDIO", "System speech returned more than 4 MiB")
                result = output.read_bytes()
                wav_info(result)
            except (OSError, ServiceError) as error:
                raise ServiceError(502, "INVALID_ENGINE_AUDIO", "System speech did not produce a complete WAV within the limits") from error
        self.tts_verified = True
        return result

    def transcribe(self, request: dict, cancel: threading.Event):
        if set(request) - {"wav_b64", "language"} or not isinstance(request.get("wav_b64"), str):
            raise ServiceError(400, "INVALID_REQUEST", "Only wav_b64 and optional language fields are accepted")
        language = request.get("language", "auto")
        if not isinstance(language, str) or language not in LANGUAGES:
            raise ServiceError(400, "INVALID_LANGUAGE", "Supported languages: auto, Chinese, English, Japanese, Korean")
        try:
            audio = base64.b64decode(request["wav_b64"], validate=True)
        except (binascii.Error, ValueError) as error:
            raise ServiceError(400, "INVALID_AUDIO", "wav_b64 must contain valid base64") from error
        wav_info(audio)
        check_cancel(cancel)
        if self.model_path is None:
            raise ServiceError(503, "ASR_UNCONFIGURED", "Configure an existing local --asr-model directory; no model is downloaded")
        with self.asr_lock:
            check_cancel(cancel)
            if self.model is None:
                try:
                    self.validate_model()
                    factory = self.asr_factory
                    if factory is None:
                        from faster_whisper import WhisperModel
                        factory = WhisperModel
                    self.model = factory(str(self.model_path), device="cpu", compute_type="int8", cpu_threads=2, local_files_only=True)
                except Exception as error:
                    raise ServiceError(503, "ASR_UNAVAILABLE", "The configured local ASR model or dependency could not be loaded") from error
            try:
                segments, info = self.model.transcribe(io.BytesIO(audio), language=LANGUAGES[language], beam_size=1, vad_filter=True)
                words = []
                for segment in segments:
                    check_cancel(cancel)
                    words.append(segment.text)
                check_cancel(cancel)
            except ServiceError:
                raise
            except Exception as error:
                raise ServiceError(502, "ASR_FAILED", "Local ASR failed to transcribe this WAV") from error
        self.asr_verified = True
        return {"text": "".join(words).strip(), "language": info.language, "audio_s": info.duration}


def server(host: str, port: int, service: LocalServices):
    host = loopback(host)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, _format, *_args):
            pass  # No request text, identifiers or audio are logged.

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def response(self, status, body, mime="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass

        def do_GET(self):
            if self.path == "/health":
                self.response(200, service.health())
            else:
                self.response(404, {"error": "Unknown endpoint", "code": "NOT_FOUND"})

        def do_POST(self):
            cancel, finished = threading.Event(), threading.Event()
            monitor = None
            try:
                if self.path in ("/align", "/sing"):
                    raise ServiceError(503, "NOT_IMPLEMENTED", "This service does not implement alignment or singing")
                if self.path not in ("/tts", "/transcribe"):
                    raise ServiceError(404, "NOT_FOUND", "Unknown endpoint")
                if self.headers.get("Transfer-Encoding"):
                    raise ServiceError(400, "INVALID_REQUEST", "Transfer-Encoding is not supported")
                try:
                    length = int(self.headers.get("Content-Length", "-1"))
                except ValueError:
                    length = -1
                if length < 0 or length > MAX_BODY:
                    raise ServiceError(413, "REQUEST_TOO_LARGE", "A Content-Length within 6 MiB is required")
                if self.headers.get_content_type() != "application/json":
                    raise ServiceError(415, "INVALID_REQUEST", "application/json is required")
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ServiceError(400, "INVALID_REQUEST", "Truncated request body")
                try:
                    def unique_object(pairs):
                        result = {}
                        for key, value in pairs:
                            if key in result:
                                raise ValueError("Duplicate JSON field")
                            result[key] = value
                        return result
                    request = json.loads(data, object_pairs_hook=unique_object)
                except (ValueError, UnicodeError) as error:
                    raise ServiceError(400, "INVALID_REQUEST", "A JSON object is required") from error
                if not isinstance(request, dict):
                    raise ServiceError(400, "INVALID_REQUEST", "A JSON object is required")

                def disconnected():
                    while not finished.wait(0.05):
                        try:
                            if select.select([self.connection], [], [], 0)[0] and not self.connection.recv(1, socket.MSG_PEEK):
                                cancel.set()
                                return
                        except OSError:
                            cancel.set()
                            return

                monitor = threading.Thread(target=disconnected, daemon=True)
                monitor.start()
                with service.request(cancel):
                    if self.path == "/tts":
                        self.response(200, service.speak(request, cancel), "audio/wav")
                    else:
                        self.response(200, service.transcribe(request, cancel))
            except ServiceError as error:
                self.response(error.status, {"error": str(error), "code": error.code})
            except (TimeoutError, ConnectionResetError):
                cancel.set()
            except Exception:
                self.response(500, {"error": "The local request failed", "code": "INTERNAL_ERROR"})
            finally:
                finished.set()
                if monitor is not None:
                    monitor.join(timeout=0.2)

    class Server(ThreadingHTTPServer):
        # Stop requests cooperatively and join them before interpreter exit, so a Ctrl+C cannot orphan say/afconvert.
        daemon_threads = False
        address_family = socket.AF_INET6 if ":" in host else socket.AF_INET

        def server_close(self):
            service.cancel_all()
            super().server_close()

    return Server((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8796)
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--voice")
    parser.add_argument("--asr-model", type=Path)
    parser.add_argument("--engine-timeout", type=float, default=30)
    args = parser.parse_args()
    # This process serves local capabilities only. Protect optional library fallbacks from initiating Hub downloads.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        service = LocalServices(args.workspace, args.state_dir or args.workspace / ".runtime/companion-services",
                                voice=args.voice, asr_model=args.asr_model, timeout=args.engine_timeout)
        http = server(args.host, args.port, service)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps({"service": "aijade-companion-services", "listen": f"http://{args.host}:{http.server_port}", "trainingVerified": False}), flush=True)
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        http.server_close()


if __name__ == "__main__":
    main()
