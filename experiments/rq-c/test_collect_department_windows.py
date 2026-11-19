"""Synthetic Windows host log evidence. No native tools, GPU or journal are queried."""

import copy
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape

import collect_department_windows as windows
from launch_department_regeneration import audit_handoff, audit_logs, log_snapshot, verify_collector_config


SINCE = windows.iso("2026-11-19T06:00:00Z")
CUTOFF = SINCE + timedelta(minutes=5)
END = SINCE + timedelta(minutes=10)
IDENTITY = {"machineGuid": "01020304-0506-0708-090a-0b0c0d0e0f01", "computer": "SYNTHETIC",
            "bootAt": "2026-11-19T05:00:00Z", "osVersion": "10.0.26100", "osBuild": "26100",
            "gpu": "GPU-01120304-0506-0708-090a-0b0c0d0e0f01", "driver": "560.94"}
CFG = {"schema": windows.CONFIG, "allocation": "synthetic-department-windows",
       "powerShell": "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
       "powerShellSha256": "a" * 64, "nativeHelperSha256": windows.sha(windows.HELPER.read_bytes()),
       "nvidiaSmi": r"C:\Windows\System32\nvidia-smi.exe", "nvidiaSmiSha256": "b" * 64, "gpuUuid": IDENTITY["gpu"],
       "serviceNames": ["Ollama"], "applicationExecutables": ["ollama.exe"], "applicationProviders": ["Ollama"]}
CONFIG_SHA = windows.sha(json.dumps(CFG).encode())
COLLECTOR_SHA = "c" * 64


def event(channel, record_id, minutes, provider="Benign Record", event_id=10, level=4, values=(), computer="SYNTHETIC.test"):
    when = windows.stamp(SINCE + timedelta(minutes=minutes))
    payload = "".join(f"<Data>{escape(value)}</Data>" for value in values)
    return (f'<Event xmlns="{windows.NAMESPACE["e"]}"><System><Provider Name="{provider}" />'
            f"<EventID>{event_id}</EventID><Level>{level}</Level><TimeCreated SystemTime=\"{when}\" />"
            f"<EventRecordID>{record_id}</EventRecordID><Channel>{channel}</Channel><Computer>{computer}</Computer>"
            f"</System><EventData>{payload}</EventData></Event>")


def native(until, system=(), application=()):
    packet = {"schema": windows.NATIVE, "powershellVersion": "5.1.26100.1", "startedAt": windows.stamp(END),
              "finishedAt": windows.stamp(END + timedelta(seconds=1)), "identityBefore": copy.deepcopy(IDENTITY),
              "identityAfter": copy.deepcopy(IDENTITY), "channels": {}}
    for channel, selected in (("System", system), ("Application", application)):
        anchor = {"oldestRecordId": 1, "recordCount": 100, "logFilePath": f"%SystemRoot%\\{channel}.evtx",
                  "logMode": "Circular", "xml": event(channel, 1, -30)}
        packet["channels"][channel] = {"xpath": windows.xpath_for(SINCE, until), "before": anchor,
                                       "after": copy.deepcopy(anchor), "events": list(selected)}
    return packet


def capture(packet, until=END):
    return windows.capture(json.dumps(packet).encode(), CFG, SINCE, until, CONFIG_SHA, COLLECTOR_SHA,
                           ["synthetic-powershell.exe", "-File", "synthetic-helper.ps1"])


class WindowsCollectorTests(unittest.TestCase):
    def test_quiet_repeated_coverage_through_launcher_validator(self):
        baseline = capture(native(CUTOFF), CUTOFF)
        final = capture(native(END))
        before, after = (json.dumps(item).encode() for item in (baseline, final))
        verify_collector_config(before, CONFIG_SHA, "baseline")
        verify_collector_config(after, CONFIG_SHA, "final")
        self.assertEqual("NO_NEW_RELEVANT_EVENTS_IN_CAPTURE",
                         audit_logs(before, after, SINCE, CUTOFF, END, baseline["host"])["status"])
        self.assertEqual("QUALIFICATION_HANDOFF_LOGS_COVERED", audit_handoff(baseline, final)["status"])
        self.assertEqual(windows.stamp(SINCE - timedelta(minutes=30)), final["sources"]["gpu"]["readableFrom"])
        self.assertEqual(baseline["sources"]["system"]["querySha256"], final["sources"]["system"]["querySha256"])
        for stream in final["sources"].values():
            self.assertEqual([], stream["events"])
        with self.assertRaisesRegex(ValueError, "does not attest"):
            verify_collector_config(after, "d" * 64, "mismatch")

    def test_faults_bound_to_actual_prior_and_handoff_windows(self):
        historical = event("System", 111, 1, "Microsoft-Windows-WHEA-Logger", 19, 4)
        system = [historical, event("System", 112, 6, "nvlddmkm", 153, 4),
                  event("System", 113, 7, "Service Control Manager", 7034, 3, ["Ollama"]),
                  event("System", 114, 8, "Service Control Manager", 7034, 3, ["Ollama Unrelated"])]
        app = [event("Application", 120, 7, "Application Error", 1000, 2, [r"C:\Ollama\ollama.exe"]),
               event("Application", 121, 8, "Application Error", 1000, 2, [r"C:\Other\not-ollama.exe"])]
        baseline = capture(native(CUTOFF, [historical]), CUTOFF)
        final = capture(native(END, system, app))
        before, after = (json.dumps(item).encode() for item in (baseline, final))
        evaluated = audit_logs(before, after, SINCE, CUTOFF, END, baseline["host"])
        self.assertEqual("RELEVANT_EVENTS_RETAINED", evaluated["status"])
        self.assertEqual({"system": ["Application/120", "System/113"], "gpu": ["System/112"]},
                         evaluated["eventIdsBySource"])
        self.assertEqual(app[0], final["sources"]["system"]["events"][1]["record"])
        with self.assertRaisesRegex(ValueError, "relevant log event"):
            audit_handoff(baseline, final)
        with self.assertRaisesRegex(ValueError, "retained baseline changed"):
            audit_logs(before, json.dumps(capture(native(END, system[1:], app))).encode(),
                       SINCE, CUTOFF, END, baseline["host"])

    def test_loss_clock_reset_changed_identity_and_bad_filter_are_refused(self):
        with self.assertRaisesRegex(ValueError, "clearing or system-clock change"):
            capture(native(END, [event("System", 21, 5, "Microsoft-Windows-Eventlog", 104, 4)]))
        with self.assertRaisesRegex(ValueError, "clearing or system-clock change"):
            capture(native(END, [event("System", 21, 5, "Microsoft-Windows-Kernel-General", 1, 4)]))
        packet = native(END)
        packet["identityAfter"]["driver"] = "560.95"
        with self.assertRaisesRegex(ValueError, "hardware or operating system changed"):
            capture(packet)
        packet = native(END)
        packet["channels"]["System"]["xpath"] = "*"
        with self.assertRaisesRegex(ValueError, "XPath differs"):
            capture(packet)

    def test_retention_wrap_or_missing_application_window_cannot_be_complete(self):
        packet = native(END)
        packet["channels"]["Application"]["after"]["xml"] = event("Application", 2, -20)
        packet["channels"]["Application"]["after"]["oldestRecordId"] = 2
        with self.assertRaisesRegex(ValueError, "rotated, cleared or changed"):
            capture(packet)
        packet = native(END)
        del packet["channels"]["Application"]
        with self.assertRaisesRegex(ValueError, "invalid Windows event channels"):
            capture(packet)
        packet = native(END)
        packet["channels"]["Application"]["before"]["xml"] = event("Application", 1, 1)
        with self.assertRaisesRegex(ValueError, "no readable start boundary"):
            capture(packet)

    def test_duplicate_future_and_cross_host_rows_are_rejected(self):
        row = event("System", 111, 4)
        with self.assertRaisesRegex(ValueError, "duplicate or out-of-window"):
            capture(native(END, [row, row]))
        with self.assertRaisesRegex(ValueError, "duplicate or out-of-window"):
            capture(native(END, [event("System", 112, 10)]))
        with self.assertRaisesRegex(ValueError, "another computer"):
            capture(native(END, [event("System", 112, 4, computer="other-host")]))
        valid = capture(native(END))
        wrong_host = dict(valid["host"], gpu="other-device")
        with self.assertRaisesRegex(ValueError, "host, boot or allocation changed"):
            log_snapshot(json.dumps(valid).encode(), SINCE, END, wrong_host)

    def test_configuration_checks_are_strict_and_require_no_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = (Path(temporary).resolve() / "collector.json")
            raw = json.dumps(CFG).encode()
            path.write_bytes(raw)
            self.assertEqual((raw, CFG), windows.verify_config(path, CONFIG_SHA, CFG["allocation"]))
            command = [sys.executable, "-B", str(Path(windows.__file__)), "--check-config", str(path),
                       "--expected-config-sha256", CONFIG_SHA, "--expected-allocation", CFG["allocation"]]
            result = subprocess.run(command, capture_output=True, check=True)
            self.assertEqual("UNVERIFIED", json.loads(result.stdout)["hostCompatibilityAndLogAccess"])
            with self.assertRaisesRegex(ValueError, "allocation differs"):
                windows.verify_config(path, CONFIG_SHA, "wrong-allocation")
            path.write_bytes(json.dumps(dict(CFG, nativeHelperSha256="d" * 64)).encode())
            with self.assertRaisesRegex(ValueError, "helper differs"):
                windows.verify_config(path)
        for field, bad in (("powerShell", "powershell"), ("powerShell", r"\\remote\share\powershell.exe"),
                           ("nvidiaSmi", r"\\remote\nvidia-smi.exe"),
                           ("gpuUuid", "NVIDIA-A"), ("applicationExecutables", [r"C:\Ollama\ollama.exe"]),
                           ("serviceNames", ["Ollama", "ollama"])):
            with self.subTest(key=field):
                with self.assertRaises(ValueError):
                    windows.config_from(json.dumps(dict(CFG, **{field: bad})).encode())

    def test_approved_windows_tool_invocation_has_no_policy_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            program = Path(temporary).resolve() / "powershell.exe"
            program.write_bytes(b"synthetic Windows tool identity")
            program.chmod(0o700)
            cfg = dict(CFG, powerShell=str(program), powerShellSha256=windows.file_sha(program))
            with patch.object(windows.sys, "platform", "win32"), patch.object(windows.subprocess, "run") as run:
                run.return_value = subprocess.CompletedProcess([], 0, b"{}\r\n", b"")
                raw, argv = windows.host_powershell(cfg, SINCE, END)
                self.assertEqual(b"{}\r\n", raw)
                self.assertIn("-File", argv)
                self.assertNotIn("-ExecutionPolicy", argv)
                self.assertNotIn("-Command", argv)
                self.assertEqual(95, run.call_args.kwargs["timeout"])
                run.return_value = subprocess.CompletedProcess([], 0, b"{}\r\n", b"channel access denied")
                with self.assertRaisesRegex(ValueError, "access denied"):
                    windows.host_powershell(cfg, SINCE, END)
                run.return_value = subprocess.CompletedProcess([], 0, b"{}", b"")
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    windows.host_powershell(cfg, SINCE, END)

    def test_wsl_translation_uses_local_helper_and_direct_approved_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            program = Path(temporary).resolve() / "powershell.exe"
            program.write_bytes(b"synthetic WSL host tool identity")
            program.chmod(0o700)
            cfg = dict(CFG, powerShell=str(program), powerShellSha256=windows.file_sha(program))
            local_path = r"\\wsl.localhost\Ubuntu\home\research\collect_department_windows.ps1"
            kernel = SimpleNamespace(release="6.6.36-microsoft-standard-WSL2")
            with patch.object(windows.sys, "platform", "linux"), patch.object(windows.os, "uname", create=True,
                    return_value=kernel), patch.object(windows.subprocess, "run") as run:
                run.side_effect = [subprocess.CompletedProcess([], 0, (local_path + "\n").encode(), b""),
                                   subprocess.CompletedProcess([], 0, b"{}\r\n", b"")]
                _, argv = windows.host_powershell(cfg, SINCE, END)
                self.assertEqual("/usr/bin/wslpath", run.call_args_list[0].args[0][0])
                self.assertEqual(local_path, argv[argv.index("-File") + 1])
                run.side_effect = [subprocess.CompletedProcess([], 0, b"\\\\server\\shared\\script.ps1\n", b"")]
                with self.assertRaisesRegex(ValueError, "did not return a local"):
                    windows.host_powershell(cfg, SINCE, END)


if __name__ == "__main__":
    unittest.main()
