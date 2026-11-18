"""Offline Linux collector controls. No real journal, GPU or server is queried."""

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import collect_department_journal as collector
import launch_department_regeneration as launch


START = datetime(2026, 11, 18, tzinfo=timezone.utc)
STOP = START + timedelta(minutes=20)
MACHINE = "a" * 32
BOOT = "aa223344-5566-7890-aabb-ccddeeff1100"
PCI = "0000:65:00.0"
UUID = "GPU-12345678-aaaa-bbbb-cccc-0123456789ab"
CFG = {
    "schema": collector.CONFIG, "allocation": "synthetic-appointment", "pciAddress": PCI,
    "journalctl": "/usr/bin/journalctl", "journalctlSha256": "b" * 64, "serviceUnits": ["ollama.service"],
}
HOST_FILES = {
    "/etc/machine-id": MACHINE + "\n",
    "/proc/sys/kernel/random/boot_id": BOOT + "\n",
    "/proc/sys/kernel/osrelease": "6.12.3-test\n",
    "/sys/module/nvidia/version": "555.42.02\n",
    f"/sys/bus/pci/devices/{PCI}/vendor": "0x10de\n",
    f"/proc/driver/nvidia/gpus/{PCI}/information": f"Model: Synthetic GPU\nGPU UUID: {UUID}\n",
}


def event(cursor, when, message="normal entry", transport="journal", fields=None):
    value = {
        "_MACHINE_ID": MACHINE, "_BOOT_ID": BOOT.replace("-", ""), "_TRANSPORT": transport,
        "__REALTIME_TIMESTAMP": collector.journal_time(when)[1:].replace(".", ""),
        "__CURSOR": cursor, "MESSAGE": message, "PRIORITY": "6",
    }
    value.update(fields or {})
    return json.dumps(value, separators=(",", ":")).encode() + b"\n"


SYSTEM_FLOOR = event("system-floor", START - timedelta(seconds=2))
KERNEL_FLOOR = event("kernel-floor", START - timedelta(minutes=1), transport="kernel")
VERSION = b"systemd 255 (255.10)\n+PAM +AUDIT\n"


class JournalTests(unittest.TestCase):
    def capture(self, window=b"", *, start=START, stop=STOP, left=SYSTEM_FLOOR, kernel=KERNEL_FLOOR,
                changed=None, stderr=b"", exit_code=0, host_files=HOST_FILES, config=CFG, now=None,
                version=VERSION):
        calls = []
        results = [(0, version, b""), (0, left, b""), (0, kernel, b""), (exit_code, window, stderr),
                   (0, changed if changed is not None else left, b""), (0, kernel, b"")]

        def query(cmd, seconds, budget):
            self.assertGreater(seconds, 0)
            self.assertGreaterEqual(budget, 0)
            index = len(calls)
            calls.append(cmd)
            if index == 0:
                self.assertEqual([config["journalctl"], "--version"], cmd)
                return results[index]
            base = collector.query_base(config, collector.identity(config, host_files.__getitem__))
            self.assertEqual(base, cmd[:len(base)])
            expected = ["--since=" + collector.journal_time(start), "--until=" + collector.journal_time(stop)]
            if index != 3:
                expected = ["--reverse", "--until=" + collector.journal_time(start), "--lines=1"]
                if index in (2, 5):
                    expected += ["_TRANSPORT=kernel"]
            self.assertEqual(expected, cmd[len(base):])
            return results[index]

        latest = now if now is not None else stop + timedelta(seconds=1)
        value = collector.capture(config, start, stop, host_files.__getitem__, query,
                                  lambda: latest, lambda: 0.0, "c" * 64)
        self.assertEqual(6, len(calls))
        self.assertNotIn("--quiet", calls[1])
        self.assertNotIn("--follow", calls[3])
        return value

    def test_quiet_window_retains_independent_access_witnesses(self):
        value = self.capture()
        self.assertEqual(("Linux 6.12.3-test", UUID, "nvidia 555.42.02"),
                         tuple(value["host"][key] for key in ("os", "gpu", "driver")))
        stamp = collector.stamp(STOP)
        self.assertEqual((0, stamp),
                         (value["provenance"]["queriedRecords"], value["sources"]["system"]["readableUntil"]))
        self.assertEqual(stamp, value["until"])
        self.assertGreater(value["provenance"]["startedAt"], stamp)
        self.assertEqual([], value["sources"]["gpu"]["events"])
        self.assertEqual(KERNEL_FLOOR.rstrip(b"\n").decode(), value["provenance"]["queries"]["kernelAtStart"]["raw"])
        self.assertEqual(collector.sha(b""), value["provenance"]["queries"]["window"]["stdoutSha256"])
        self.assertEqual("systemd 255 (255.10)", value["sources"]["system"]["queryScope"]["journalctlVersion"])
        self.assertEqual(collector.sha(VERSION), value["provenance"]["queries"]["journalctlVersion"]["stdoutSha256"])
        captured = launch.log_snapshot(launch.encoded(value), START, STOP, value["host"])
        self.assertTrue(captured["sources"]["system"]["complete"])
        marker = b"-- No entries --\n"
        quiet = self.capture(marker)["provenance"]
        self.assertEqual((0, collector.sha(marker)), (quiet["queriedRecords"], quiet["queries"]["window"]["stdoutSha256"]))

    def test_same_boot_retention_floors_required_even_with_zero_exit(self):
        for overrides in ({"left": b""}, {"kernel": b""}, {"changed": b""},
                          {"kernel": SYSTEM_FLOOR}):
            with self.subTest(overrides=overrides):
                self.assertRaisesRegex(ValueError, "readable entry|coverage boundary", self.capture, **overrides)

    def test_same_cutoff_event_belongs_to_later_window(self):
        old = event("cpu", START + timedelta(minutes=5), "mce: hardware error", "kernel")
        failure = event("xid", STOP, "NVRM: Xid 79: GPU has fallen off bus", "kernel")
        service = event("service", STOP + timedelta(minutes=4), "main process exited with failure",
                        fields={"SYSLOG_IDENTIFIER": "systemd", "UNIT": "ollama.service"})
        irrelevant = event("quiet", STOP + timedelta(minutes=5), "succeeded")
        before = self.capture(old + failure)
        later = STOP + timedelta(minutes=10)
        after = self.capture(old + failure + service + irrelevant, stop=later)
        self.assertEqual(["cpu"], [e["id"] for e in before["sources"]["system"]["events"]])
        self.assertEqual([], before["sources"]["gpu"]["events"])
        self.assertEqual(failure.rstrip(b"\n").decode(), after["sources"]["gpu"]["events"][0]["record"])
        self.assertEqual(collector.sha(old + failure + service + irrelevant),
                         after["provenance"]["queries"]["window"]["stdoutSha256"])
        report = launch.audit_logs(launch.encoded(before), launch.encoded(after), START, STOP, later, before["host"])
        self.assertEqual("RELEVANT_EVENTS_RETAINED", report["status"])
        self.assertEqual({"system": ["service"], "gpu": ["xid"]}, report["eventIdsBySource"])

    def test_reject_warnings_truncation_clock_and_limit_failures(self):
        for overrides, reason in (
            ({"stderr": b"Warning: some journal files were not opened due to insufficient permissions"}, "diagnostic"),
            ({"exit_code": 1}, "unsuccessfully"),
            ({"window": b'{"broken":'}, "partial"),
            ({"now": STOP - timedelta(seconds=1)}, "cutoff"),
            ({"version": b"unexpected executable\n"}, "unrecognized journalctl version"),
        ):
            with self.subTest(overrides=overrides):
                self.assertRaisesRegex(ValueError, reason, self.capture, **overrides)

    def test_reject_rate_limit_notice_and_changing_coverage_witness(self):
        expired = event("system-floor", START - timedelta(seconds=3))
        self.assertRaisesRegex(ValueError, "witness changed", self.capture, changed=expired)
        suppressed = event("drop", START + timedelta(minutes=5), "Suppressed 12 messages from ollama.service")
        self.assertRaisesRegex(ValueError, "suppressed", self.capture, suppressed)

    def test_reject_different_boot_or_device(self):
        wrong = event("wrong", START, fields={"_BOOT_ID": "2" * 32})
        self.assertRaisesRegex(ValueError, "different machine or boot", self.capture, wrong)
        changed = dict(HOST_FILES)
        changed[f"/sys/bus/pci/devices/{PCI}/vendor"] = "0x1002\n"
        self.assertRaisesRegex(ValueError, "not an NVIDIA device", self.capture, host_files=changed)

    def test_reject_missing_start_witness_and_duplicate_cursor(self):
        exact = event("start", START)
        self.assertRaisesRegex(ValueError, "omitted a start-boundary witness", self.capture, left=exact)
        self.assertRaisesRegex(ValueError, "duplicate", self.capture, exact + exact)

    def test_reject_unknown_or_unbounded_configuration(self):
        self.assertEqual(CFG, collector.config_from(json.dumps(CFG).encode()))
        for changed in (dict(CFG, args=["--follow"]), dict(CFG, journalctl="journalctl"),
                        dict(CFG, pciAddress="../../something"), dict(CFG, serviceUnits=["*"])):
            self.assertRaises(ValueError, collector.config_from, json.dumps(changed).encode())
        self.assertRaisesRegex(ValueError, "duplicate JSON key", collector.config_from, b'{"schema":"a","schema":"b"}')

    def test_check_config_reads_exact_bytes_without_running_the_collector(self):
        runtime = launch.REPO / ".runtime"
        runtime.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix="p2-config-check-", dir=runtime) as directory:
            config = Path(directory).resolve() / "collector.json"
            raw = (json.dumps(CFG) + "\n").encode()
            config.write_bytes(raw)
            digest = collector.sha(raw)
            command = ["collect_department_journal.py", "--check-config", str(config),
                       "--expected-config-sha256", digest, "--expected-allocation", CFG["allocation"]]
            with patch.object(sys, "argv", command), patch.object(sys, "platform", "darwin"), \
                    patch.object(collector, "capture") as capture, patch.object(collector, "pin_file") as pin, \
                    redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(0, collector.main())
                report = json.loads(stdout.getvalue())
                capture.assert_not_called()
                pin.assert_not_called()
            self.assertEqual(report, {"status": "COLLECTOR_CONFIG_OFFLINE_VALIDATED", "configurationSha256": digest,
                                      "comparedExpectedSha256": True, "comparedExpectedAllocation": True,
                                      "hostCompatibilityAndLogAccess": "UNVERIFIED"})

    def test_check_config_refuses_mismatch_and_oversized_bytes(self):
        runtime = launch.REPO / ".runtime"
        runtime.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix="p2-config-check-", dir=runtime) as directory:
            config = Path(directory).resolve() / "collector.json"
            raw = json.dumps(CFG).encode()
            cases = ((raw + b"\n", ["--expected-config-sha256", collector.sha(raw)], "SHA-256"),
                     (raw, ["--expected-allocation", "another-allocation"], "expected allocation"),
                     (b" " * (collector.CONFIG_BUDGET + 1), [], "too large"))
            command = ["collect_department_journal.py", "--check-config", str(config)]
            for content, flags, message in cases:
                with self.subTest(message=message):
                    config.write_bytes(content)
                    with patch.object(sys, "argv", command + flags), redirect_stderr(io.StringIO()) as stderr:
                        self.assertEqual(2, collector.main())
                    self.assertIn(message, stderr.getvalue())

    def test_bounded_capture_drains_both_channels_and_stops_at_limit(self):
        command = [sys.executable, "-B", "-c", "import sys; sys.stdout.write('abc'); sys.stderr.write('de')"]
        self.assertEqual((0, b"abc", b"de"), collector.bounded_query(command, 3, 5))
        self.assertRaisesRegex(ValueError, "byte limit", collector.bounded_query, command, 3, 4)

    def test_launcher_hands_only_pinned_configuration_to_read_only_collector(self):
        runtime = launch.REPO / ".runtime"
        runtime.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix="p2-journal-controls-", dir=runtime) as workspace:
            root = Path(workspace).resolve()
            config = root / "collector.json"
            settings = json.dumps(CFG).encode()
            config.write_bytes(settings)
            digest = collector.sha(settings)
            approval = {"logCollector": {"config": {"path": "collector.json", "sha256": digest}}}
            stage = launch.DepartmentRuntime(approval, {"logCollector": root / "fake-collector", "logCollectorConfig": config})

            def mocked_call(cmd, *, env, stdout, **kwargs):
                self.assertEqual(str(config), env["AIJADE_P2_LOG_CONFIG"])
                self.assertEqual([str(root / "fake-collector"), "--since", launch.stamp(START),
                                  "--until", launch.stamp(STOP)], cmd)
                capture = self.capture()
                capture["provenance"]["configurationSha256"] = digest
                stdout.write(launch.encoded(capture))
                return SimpleNamespace(returncode=0)

            with patch.dict(os.environ, {"AIJADE_P2_LOG_CONFIG": "/different-config"}), \
                    patch.object(launch.subprocess, "run", side_effect=mocked_call) as run:
                raw = stage.capture(root, "before", START, STOP)
                self.assertEqual(digest, json.loads(raw)["provenance"]["configurationSha256"])
                config.write_bytes(settings + b" ")
                self.assertRaisesRegex(ValueError, "file identity differs", stage.capture, root, "after", START, STOP)
                self.assertEqual(1, run.call_count)
                self.assertFalse((root / "logs-after.json").exists())

    def test_launcher_rejects_mismatched_collector_output_attestation(self):
        runtime = launch.REPO / ".runtime"
        runtime.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix="p2-journal-controls-", dir=runtime) as workspace:
            root = Path(workspace).resolve()
            config = root / "collector.json"
            config.write_bytes(b"synthetic")
            approval = {"logCollector": {"config": {"sha256": collector.sha(b"synthetic")}}}
            stage = launch.DepartmentRuntime(approval, {"logCollector": root / "fake-collector", "logCollectorConfig": config})

            def mocked_call(cmd, *, stdout, **kwargs):
                stdout.write(launch.encoded(self.capture()))
                return SimpleNamespace(returncode=0)

            with patch.object(launch.subprocess, "run", side_effect=mocked_call):
                self.assertRaisesRegex(ValueError, "does not attest", stage.capture, root, "before", START, STOP)
                self.assertTrue((root / "logs-before.json").is_file())


if __name__ == "__main__":
    unittest.main()
