#!/usr/bin/env python3
"""Check WSL runtime dependencies without contacting any model service or logs."""

import argparse
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import re
import shutil
import subprocess
import sys

from department_oracle_capture import ENVIRONMENT_SCHEMA
from launch_department_oracle_replay import NODE_ENV, NODE_SNAPSHOT
from launch_department_regeneration import digest_file
from prepare_department_regeneration import REPO, encoded, prepare, require, sha


SCHEMA = "aijade.p2-r.wsl-offline-preflight.v1"
WORKLIST_SHA256 = "04bf4f7f96b41b888ce22f81de4bf533b3d3edc53d38a0f3f6828785b898b91d"
HOST_PROBE = ("Get-Command Get-WinEvent,Get-CimInstance -ErrorAction Stop | Out-Null; "
              "[Console]::Write(('{0}|{1}' -f $env:OS,$PSVersionTable.PSVersion))")
LINUX_TOOLS = ("git", "findmnt", "dotnet", "node")
WINDOWS_MOUNTS = {"9p", "drvfs", "ntfs", "ntfs3", "fuseblk", "cifs", "smb3"}
GIT_ENV = {"GIT_OPTIONAL_LOCKS": "0"}


def probe(executable, arguments, cwd, *, env=None):
    result = subprocess.run([str(executable), *arguments], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, check=True, timeout=20)
    require(not result.stderr.strip(), f"{executable.name} probe wrote an unexpected diagnostic")
    return result.stdout.decode("utf-8").strip()


def executable_paths(powershell=None):
    names = (*LINUX_TOOLS, "wslpath", "powershell.exe")
    located = {name: shutil.which(name) for name in names}
    if powershell is not None:
        require(powershell.is_absolute(), "the explicit PowerShell path must be absolute in WSL")
        located["powershell.exe"] = powershell
    missing = [name for name, path in located.items() if not path]
    require(not missing, "missing WSL commands: " + ", ".join(missing))
    tools = {name: Path(path).resolve(strict=True) for name, path in located.items() if name != "wslpath"}
    # WSL can dispatch to wslpath from /init by the executable alias in argv[0].
    tools["wslpath"] = Path(located["wslpath"]).absolute()
    tools["python3"] = Path(sys.executable).resolve(strict=True)
    for name in (*LINUX_TOOLS, "python3", "powershell.exe"):
        tool = tools[name]
        with tool.open("rb") as source:
            valid = source.read(4).startswith(b"MZ" if name == "powershell.exe" else b"\x7fELF")
        expected = "a native Windows executable" if name == "powershell.exe" else "a native Linux executable"
        require(valid, f"{name} is not {expected}")
    return tools


def sdk_version(version):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?", version)
    require(match is not None, "expected a .NET SDK version")
    return tuple(map(int, match.groups()))


def command_identity(path):
    real_path = path.resolve(strict=True)
    return {"path": str(path), "resolvedPath": str(real_path), "sha256": digest_file(real_path)}


def preflight(repo, expected_commit, powershell=None):
    release = platform.release()
    report = {"schema": SCHEMA, "status": "WSL_OFFLINE_DEPENDENCIES_INCOMPLETE",
              "expectedSourceCommit": expected_commit, "kernelRelease": release,
              "formalRunsStarted": 0, "hostLogsQueried": 0, "modelRequests": 0, "candidateExecutions": 0}
    try:
        require(sys.platform == "linux" and "wsl2" in release.casefold(),
                "the current kernel release does not identify WSL 2")
        require(sys.version_info >= (3, 12), "Python 3.12 or later is required")
        report["pythonVersion"] = platform.python_version()
        tools = executable_paths(powershell)

        git_env = dict(os.environ, **GIT_ENV)
        git = tools["git"]
        actual = probe(git, ["rev-parse", "HEAD"], repo, env=git_env)
        report["sourceCommit"] = actual
        require(actual == expected_commit, "checkout HEAD differs from the expected source commit")
        status = probe(git, ["status", "--porcelain=v1", "--untracked-files=all",
                             "--ignore-submodules=none"], repo, env=git_env)
        require(not status, "the complete source checkout must be clean")

        mount = probe(tools["findmnt"], ["-n", "-o", "FSTYPE", "-T", str(repo)], repo)
        require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+", mount)), "checkout filesystem type could not be determined")
        report["checkoutFileSystem"] = mount
        report["checkoutOnWindowsOrNetworkFileSystem"] = mount.casefold() in WINDOWS_MOUNTS

        policy = json.loads((repo / "global.json").read_bytes())["sdk"]
        version = probe(tools["dotnet"], ["--version"], repo,
                        env=dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1",
                                 DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1", DOTNET_GENERATE_ASPNET_CERTIFICATE="false"))
        requested, selected = sdk_version(policy["version"]), sdk_version(version)
        require(policy.get("rollForward") == "latestFeature" and selected[:2] == requested[:2]
                and selected >= requested, "selected .NET SDK does not satisfy global.json")
        report["dotnetSdk"] = version

        node = tools["node"]
        node_version = probe(node, ["--version"], repo, env=NODE_ENV)
        require(re.fullmatch(r"v\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.+-]+)?", node_version) is not None,
                "expected a Node runtime version")
        snapshot = json.loads(probe(node, ["-e", NODE_SNAPSHOT], repo, env=NODE_ENV))
        require(snapshot["runtime"] == "node" and snapshot["runtimeVersion"] == node_version
                and snapshot["platform"] == "linux" and snapshot["architecture"] in {"arm64", "x64"}
                and all(isinstance(snapshot.get(key), str) and snapshot[key] for key in ("osRelease", "locale", "timeZone")),
                "Node runtime disagrees with the Linux evaluator environment")
        report["nodeEnvironment"] = dict(snapshot, schema=ENVIRONMENT_SCHEMA)

        windows_path = probe(tools["wslpath"], ["-w", str(repo)], repo)
        require(PureWindowsPath(windows_path).is_absolute(), "wslpath did not return an absolute Windows path")
        version = probe(tools["powershell.exe"], ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", HOST_PROBE],
                        repo)
        match = re.fullmatch(r"Windows_NT\|(\d+(?:\.\d+){1,3})", version)
        require(match is not None, "Windows PowerShell did not respond through WSL interoperability")
        report["windowsPowerShellVersion"] = match[1]

        digest = sha(encoded(prepare()))
        require(digest == WORKLIST_SHA256, "worklist bytes differ from the frozen 3ce1812 population")
        report["worklistSha256"] = digest
        report["executables"] = {name: command_identity(path) for name, path in tools.items()}
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        report["diagnostic"] = str(error)
    else:
        report["status"] = "WSL_OFFLINE_DEPENDENCIES_VERIFIED"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit", required=True, help="full Git commit of the WSL checkout")
    parser.add_argument("--powershell", type=Path, help="absolute WSL path if powershell.exe is absent from PATH")
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.expected_commit) is None:
        parser.error("expected a full 40-character lowercase Git SHA")
    result = preflight(REPO, args.expected_commit, args.powershell)
    sys.stdout.buffer.write(encoded(result))
    return 0 if result["status"] == "WSL_OFFLINE_DEPENDENCIES_VERIFIED" else 2


if __name__ == "__main__":
    sys.exit(main())
