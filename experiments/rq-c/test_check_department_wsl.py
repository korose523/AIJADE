"""Authored offline controls for P2-R WSL dependency and source verification."""

import json
from pathlib import Path, PureWindowsPath
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import check_department_wsl as wsl
import prepare_department_regeneration as prep


COMMIT = "c" * 40
TOOLS = {name: Path("/fixture-commands") / name for name in (*wsl.LINUX_TOOLS, "wslpath", "powershell.exe", "python3")}
SNAPSHOT = {"runtime": "node", "runtimeVersion": "v24.22.1", "platform": "linux", "architecture": "x64",
            "osRelease": "6.6.87.2-microsoft-standard-WSL2", "locale": "en-US", "timeZone": "UTC"}
RESPONSES = {
    (TOOLS["git"], ("rev-parse", "HEAD")): COMMIT,
    (TOOLS["git"], ("status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none")): "",
    (TOOLS["findmnt"], ("-n", "-o", "FSTYPE", "-T", str(prep.REPO))): "ext4",
    (TOOLS["dotnet"], ("--version",)): "10.0.404",
    (TOOLS["node"], ("--version",)): SNAPSHOT["runtimeVersion"],
    (TOOLS["node"], ("-e", wsl.NODE_SNAPSHOT)): json.dumps(SNAPSHOT),
    (TOOLS["wslpath"], ("-w", str(prep.REPO))): r"\\wsl.localhost\Ubuntu\home\student\AIJADE",
    (TOOLS["powershell.exe"], ("-NoLogo", "-NoProfile", "-NonInteractive", "-Command", wsl.HOST_PROBE)):
        "Windows_NT|5.1.26100.1",
}


class WindowsRelativePath(type(prep.REPO)):
    def relative_to(self, *args, **kwargs):
        return PureWindowsPath(super().relative_to(*args, **kwargs))


class DepartmentWslTests(unittest.TestCase):
    def test_worklist_keeps_the_frozen_digest_on_windows_paths(self):
        with patch.multiple(prep, HERE=WindowsRelativePath(prep.HERE), PLAN=WindowsRelativePath(prep.PLAN)):
            result = prep.prepare()
        self.assertNotIn("\\", result["historicalPlan"]["path"])
        self.assertTrue(all("\\" not in row["historicalRun"]["directory"] for row in result["groups"]))
        self.assertEqual(wsl.WORKLIST_SHA256, prep.sha(prep.encoded(result)))

    def test_other_platform_stops_before_any_tool_or_archive_probe(self):
        for platform, release in (("darwin", "25.1.0"), ("linux", "6.8.0-generic"), ("linux", "4.4.0-Microsoft")):
            with self.subTest(platform=platform, release=release):
                with patch.object(wsl.platform, "release", return_value=release), \
                        patch.object(wsl.sys, "platform", platform), patch.object(wsl, "executable_paths") as tools, \
                        patch.object(wsl, "prepare") as prepare:
                    result = wsl.preflight(prep.REPO, COMMIT)
                self.assertEqual("WSL_OFFLINE_DEPENDENCIES_INCOMPLETE", result["status"])
                self.assertIn("does not identify WSL 2", result["diagnostic"])
                tools.assert_not_called()
                prepare.assert_not_called()

    def test_missing_and_wrong_platform_binaries_are_refused(self):
        runtime = prep.REPO / ".runtime"
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="p2-r-wsl-controls-", dir=runtime) as directory:
            tools = {name: (Path(directory) / name).resolve() for name in TOOLS}
            for name, path in tools.items():
                path.write_bytes(b"MZ\0\0" if name == "powershell.exe" else b"\x7fELF")
            with patch.object(wsl.sys, "executable", str(tools["python3"])), \
                    patch.object(wsl.shutil, "which", side_effect=lambda name: str(tools[name])):
                self.assertEqual(tools, wsl.executable_paths())
                tools["node"].write_bytes(b"MZ\0\0")
                with self.assertRaisesRegex(ValueError, "node is not a native Linux executable"):
                    wsl.executable_paths()
            with patch.object(wsl.shutil, "which", return_value=None):
                with self.assertRaisesRegex(ValueError, "missing WSL commands: git, findmnt, dotnet, node"):
                    wsl.executable_paths()

    def test_wslpath_multicall_alias_is_invoked_by_name_and_hashes_its_target(self):
        runtime = prep.REPO / ".runtime"
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="p2-r-wsl-alias-", dir=runtime) as directory:
            tools = {name: (Path(directory) / name).resolve() for name in TOOLS}
            target = tools["wslpath"].with_name("init")
            for name, path in tools.items():
                if name != "wslpath":
                    path.write_bytes(b"MZ\0\0" if name == "powershell.exe" else b"\x7fELF")
            target.write_bytes(b"\x7fELF dispatch fixture")
            tools["wslpath"].symlink_to(target)
            with patch.object(wsl.sys, "executable", str(tools["python3"])), \
                    patch.object(wsl.shutil, "which", side_effect=lambda name: str(tools[name])):
                alias = wsl.executable_paths()["wslpath"]
            self.assertEqual(tools["wslpath"], alias)
            self.assertEqual({"path": str(alias), "resolvedPath": str(target),
                              "sha256": prep.sha(target.read_bytes())}, wsl.command_identity(alias))

    def inspect(self, responses, expected_digest=wsl.WORKLIST_SHA256):
        query = lambda path, args, cwd, **kwargs: responses[(path, tuple(args))]
        expected_ref = {"fixture": True}
        with patch.object(wsl.platform, "release", return_value=SNAPSHOT["osRelease"]), \
                patch.object(wsl.sys, "platform", "linux"), patch.object(wsl, "executable_paths", return_value=TOOLS), \
                patch.object(wsl, "probe", side_effect=query) as probe, patch.object(wsl, "prepare", return_value=expected_ref), \
                patch.object(wsl, "sha", return_value=expected_digest), \
                patch.object(wsl, "command_identity", side_effect=lambda path: {"path": str(path), "sha256": "0" * 64}):
            result = wsl.preflight(prep.REPO, COMMIT)
        for call in probe.call_args_list:
            self.assertEqual(prep.REPO, call.args[2])
        return result, probe

    def test_all_dependency_checks_write_a_dependency_only_receipt(self):
        result, probe = self.inspect(RESPONSES)
        self.assertEqual("WSL_OFFLINE_DEPENDENCIES_VERIFIED", result["status"])
        self.assertEqual(wsl.WORKLIST_SHA256, result["worklistSha256"])
        self.assertEqual("linux", result["nodeEnvironment"]["platform"])
        self.assertEqual("5.1.26100.1", result["windowsPowerShellVersion"])
        self.assertEqual("ext4", result["checkoutFileSystem"])
        self.assertFalse(result["checkoutOnWindowsOrNetworkFileSystem"])
        self.assertEqual(set(TOOLS), set(result["executables"]))
        self.assertEqual(probe.call_count, len(RESPONSES))
        self.assertTrue(all(result[key] == 0 for key in
                            ("formalRunsStarted", "hostLogsQueried", "modelRequests", "candidateExecutions")))
        self.assertTrue(all(call.kwargs["env"] == wsl.NODE_ENV for call in probe.call_args_list if
                            call.args[0] == TOOLS["node"]))

    def test_checkout_mount_is_reported(self):
        responses = {**RESPONSES, (TOOLS["findmnt"], ("-n", "-o", "FSTYPE", "-T", str(prep.REPO))): "9p"}
        result, _ = self.inspect(responses)
        self.assertEqual("WSL_OFFLINE_DEPENDENCIES_VERIFIED", result["status"])
        self.assertTrue(result["checkoutOnWindowsOrNetworkFileSystem"])

    def test_wrong_source_sdk_node_or_host_probe_is_refused(self):
        cases = [
            ("wrong commit", (TOOLS["git"], ("rev-parse", "HEAD")), "a" * 40, "HEAD differs"),
            ("dirty", (TOOLS["git"], ("status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none")),
             "?? manifest.json", "must be clean"),
            ("old SDK", (TOOLS["dotnet"], ("--version",)), "10.0.402", "does not satisfy global.json"),
            ("wrong target", (TOOLS["dotnet"], ("--version",)), "11.0.403", "does not satisfy global.json"),
            ("Windows Node", (TOOLS["node"], ("-e", wsl.NODE_SNAPSHOT)), json.dumps(dict(SNAPSHOT, platform="win32")),
             "disagrees with the Linux evaluator"),
            ("translation", (TOOLS["wslpath"], ("-w", str(prep.REPO))), "./collector", "absolute Windows path"),
            ("interop", (TOOLS["powershell.exe"], ("-NoLogo", "-NoProfile", "-NonInteractive", "-Command", wsl.HOST_PROBE)),
             "PowerShell product", "did not respond"),
        ]
        for name, key, raw, diagnostic in cases:
            with self.subTest(name=name):
                result, _ = self.inspect({**RESPONSES, key: raw})
                self.assertEqual("WSL_OFFLINE_DEPENDENCIES_INCOMPLETE", result["status"])
                self.assertIn(diagnostic, result["diagnostic"])
                self.assertEqual(0, result["formalRunsStarted"])

    def test_frozen_worklist_drift_is_refused(self):
        result, _ = self.inspect(RESPONSES, "a" * 64)
        self.assertEqual("WSL_OFFLINE_DEPENDENCIES_INCOMPLETE", result["status"])
        self.assertIn("differ from the frozen 3ce1812 population", result["diagnostic"])

    def test_probe_runs_without_shell_or_input_and_times_out(self):
        with patch.object(wsl.subprocess, "run", side_effect=subprocess.TimeoutExpired("dotnet", 20)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                wsl.probe(TOOLS["dotnet"], ["--version"], prep.REPO)
        run.assert_called_once_with([str(TOOLS["dotnet"]), "--version"], cwd=prep.REPO, env=None,
                                    stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=20)


if __name__ == "__main__":
    unittest.main()
