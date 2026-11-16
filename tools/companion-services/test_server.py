import base64
from contextlib import contextmanager
import http.client
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
import wave

import server

ROOT = Path(os.environ.get("AIJADE_SERVICE_TEST_ROOT", Path(__file__).resolve().parents[2] / ".runtime/service-tests"))
ROOT.mkdir(parents=True, exist_ok=True)


def wav():
    out = io.BytesIO()
    with wave.open(out, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 160)
    return out.getvalue()


class FakeSpeech:
    def __init__(self, *, fail=False, block=False):
        self.fail, self.block = fail, block
        self.entered, self.cancelled = threading.Event(), threading.Event()
        self.calls = []

    def run(self, command, deadline, cancel, directory):
        self.calls.append(command)
        if self.fail:
            raise server.ServiceError(502, "ENGINE_FAILED", "Synthetic engine failure")
        if self.block:
            self.entered.set()
            cancel.wait(timeout=3)
            if cancel.is_set():
                self.cancelled.set()
            server.check_cancel(cancel)
        if command[0].endswith("afconvert"):
            Path(command[-1]).write_bytes(wav())


@contextmanager
def running(**options):
    with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
        workspace = Path(temporary)
        if options.pop("configured_asr", False):
            model = workspace / "model"
            model.mkdir()
            for name in ("model.bin", "tokenizer.json", "config.json"):
                (model / name).write_bytes(b"synthetic loader fixture")
            options["asr_model"] = model
        service = server.LocalServices(workspace, workspace / "state", **options)
        http = server.server("127.0.0.1", 0, service)
        worker = threading.Thread(target=lambda: http.serve_forever(poll_interval=0.02), daemon=True)
        worker.start()
        try:
            yield http.server_port, service, workspace
        finally:
            http.shutdown()
            http.server_close()
            worker.join(timeout=2)


def post(port, path, payload):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("POST", path, raw, {"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, response.read(), response.getheader("Content-Type")
    finally:
        connection.close()


class LocalServiceTests(unittest.TestCase):
    def test_real_http_tts_has_wav_and_no_training_claim_and_cleans_temporary_files(self):
        engine = FakeSpeech()
        with running(commands=engine) as (port, service, workspace):
            status, data, mime = post(port, "/tts", {"text": "-n $(do not run) `text`", "emotion": "happy"})
            self.assertEqual((200, "audio/wav"), (status, mime))
            self.assertEqual(wav(), data)
            self.assertEqual([], list((workspace / "state").iterdir()))
            self.assertTrue(service.health()["speech"]["runtimeVerified"])
            self.assertFalse(service.health()["speech"]["trainingVerified"])
            self.assertFalse(service.health()["speech"]["emotionApplied"])
            self.assertIn("-f", engine.calls[0])
            self.assertNotIn("$(do not run)", " ".join(engine.calls[0]))

    def test_invalid_text_fields_and_duplicate_json_are_rejected_before_engine(self):
        engine = FakeSpeech()
        with running(commands=engine) as (port, _, _workspace):
            payloads = [{"text": " "}, {"text": "x" * 2001}, {"text": "x", "unknown": 1},
                        {"text": "x", "emotion": "made-up"}, {"text": 1}, {"text": "nul\0text"},
                        [], b'{"text":"one","text":"two"}']
            for payload in payloads:
                with self.subTest(payload_type=type(payload).__name__):
                    self.assertEqual(400, post(port, "/tts", payload)[0])
            self.assertEqual([], engine.calls)

    def test_audio_and_language_are_validated_and_unconfigured_asr_is_explicit(self):
        with running() as (port, service, _workspace):
            for audio in [b"RIFF\0\0\0\0WAVE", b"garbage", wav()[:44], wav()[:-2], b"x" * (server.MAX_WAV + 1)]:
                self.assertEqual(400, post(port, "/transcribe", {"wav_b64": base64.b64encode(audio).decode()})[0])
            self.assertEqual(400, post(port, "/transcribe", {"wav_b64": "not base64"})[0])
            self.assertEqual(400, post(port, "/transcribe", {"wav_b64": base64.b64encode(wav()).decode(), "language": "invented"})[0])
            self.assertEqual(503, post(port, "/transcribe", {"wav_b64": base64.b64encode(wav()).decode()})[0])
            self.assertFalse(service.health()["transcription"]["configured"])
            self.assertFalse(service.health()["transcription"]["modelLoaded"])

    def test_asr_is_lazy_local_only_and_the_actual_result_is_returned(self):
        calls = []
        class Model:
            def transcribe(self, source, **options):
                calls.append(options)
                class Segment:
                    text = "synthetic transcript"
                class Info:
                    language, duration = "zh", 0.01
                return iter([Segment()]), Info()
        def factory(path, **options):
            calls.append({"path": path, **options})
            return Model()
        with running(configured_asr=True, asr_factory=factory) as (port, service, workspace):
            self.assertEqual([], calls)
            self.assertFalse(service.health()["transcription"]["modelLoaded"])
            status, data, _mime = post(port, "/transcribe", {"wav_b64": base64.b64encode(wav()).decode(), "language": "Chinese"})
            self.assertEqual(200, status)
            self.assertEqual("synthetic transcript", json.loads(data)["text"])
            self.assertTrue(calls[0]["local_files_only"])
            self.assertEqual(str(workspace / "model"), calls[0]["path"])
            self.assertTrue(service.health()["transcription"]["runtimeVerified"])

    def test_engine_failure_cleans_data_and_alignment_and_singing_do_not_fake_output(self):
        with running(commands=FakeSpeech(fail=True)) as (port, service, workspace):
            self.assertEqual(502, post(port, "/tts", {"text": "hello"})[0])
            self.assertEqual([], list((workspace / "state").iterdir()))
            self.assertFalse(service.health()["speech"]["runtimeVerified"])
            for path in ["/align", "/sing"]:
                status, data, _mime = post(port, path, {})
                self.assertEqual(503, status)
                self.assertEqual("NOT_IMPLEMENTED", json.loads(data)["code"])

    def test_asr_model_load_failure_is_explicit_without_runtime_success(self):
        def fail(_path, **_options):
            raise RuntimeError("synthetic model load failure")
        with running(configured_asr=True, asr_factory=fail) as (port, service, _workspace):
            status, data, _mime = post(port, "/transcribe", {"wav_b64": base64.b64encode(wav()).decode()})
            self.assertEqual(503, status)
            self.assertEqual("ASR_UNAVAILABLE", json.loads(data)["code"])
            self.assertFalse(service.health()["transcription"]["runtimeVerified"])

    def test_nonloopback_binding_and_paths_outside_workspace_are_rejected(self):
        for host in ["0.0.0.0", "192.168.1.2", "example.org", "::"]:
            with self.assertRaises(ValueError):
                server.loopback(host)
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                server.LocalServices(root, root.parent / "outside")

    def test_incomplete_local_model_is_rejected_before_a_tokenizer_fallback_can_download(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            model = root / "model"
            model.mkdir()
            (model / "model.bin").write_bytes(b"weights alone are insufficient")
            with self.assertRaisesRegex(ValueError, "tokenizer.json"):
                server.LocalServices(root, root / "state", asr_model=model)

    def test_oversized_http_body_is_rejected_without_reading_it(self):
        with running() as (port, _service, _workspace):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            connection.putrequest("POST", "/tts")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(server.MAX_BODY + 1))
            connection.endheaders()
            self.assertEqual(413, connection.getresponse().status)
            connection.close()

    def test_client_disconnect_cancels_engine_and_cleans_request_files(self):
        engine = FakeSpeech(block=True)
        with running(commands=engine) as (port, _service, workspace):
            connection = socket.create_connection(("127.0.0.1", port), timeout=2)
            body = b'{"text":"hello"}'
            connection.sendall(b"POST /tts HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            self.assertTrue(engine.entered.wait(timeout=2))
            connection.close()
            self.assertTrue(engine.cancelled.wait(timeout=2))
            for _ in range(30):
                if not list((workspace / "state").iterdir()):
                    break
                time.sleep(0.02)
            self.assertEqual([], list((workspace / "state").iterdir()))

    def test_real_owned_process_is_terminated_on_timeout_and_cancellation(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            for cancelled in [False, True]:
                cancel = threading.Event()
                timer = threading.Timer(0.05, cancel.set) if cancelled else None
                if timer:
                    timer.start()
                try:
                    with self.assertRaises(server.ServiceError) as caught:
                        server.Commands().run([sys.executable, "-c", "import time;time.sleep(10)"], time.monotonic() + 0.2, cancel, directory)
                    self.assertEqual("CANCELLED" if cancelled else "ENGINE_TIMEOUT", caught.exception.code)
                finally:
                    if timer:
                        timer.join()

    def test_server_shutdown_cancels_active_request_and_waits_for_cleanup(self):
        engine = FakeSpeech(block=True)
        results = []
        with running(commands=engine) as (port, _service, workspace):
            client = threading.Thread(target=lambda: results.append(post(port, "/tts", {"text": "hello"})[0]))
            client.start()
            self.assertTrue(engine.entered.wait(timeout=2))
        client.join(timeout=2)
        self.assertFalse(client.is_alive())
        self.assertTrue(engine.cancelled.is_set())
        self.assertEqual([499], results)
        self.assertFalse(workspace.exists())


if __name__ == "__main__":
    unittest.main()
