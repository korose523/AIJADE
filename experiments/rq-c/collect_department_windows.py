#!/usr/bin/env python3
"""Read-only P2-R log evidence from the approved Windows NVIDIA host."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys
from xml.etree import ElementTree

from collect_department_journal import CAPTURE, EPOCH, config_bytes, decode, iso, need, sha, stamp


CONFIG = "aijade.p2-r.windows-event-collector.v1"
NATIVE = "aijade.p2-r.windows-event-native-export.v1"
HELPER = Path(__file__).with_suffix(".ps1").resolve()
SHA256 = re.compile(r"[0-9a-f]{64}")
UUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
CHANNELS = ("System", "Application")
NAMESPACE = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
GPU_PROVIDERS = {"nvlddmkm", "nvidia", "nvidia driver", "microsoft-windows-dxgkrnl", "display"}
SCM_FAILURES = {7000, 7001, 7009, 7011, 7022, 7023, 7024, 7031, 7034}
APP_FAILURE_PROVIDERS = {"application error", "application hang", "windows error reporting", ".net runtime"}
FAILURE_WORDS = re.compile(r"\b(?:crash(?:ed)?|failed|failure|error|panic|timeout|reset|hang|xid|fatal)\b", re.I)
READ_BUDGET = 32 * 1024 * 1024


def fields(value, names, label):
    need(type(value) is dict and set(value) == set(names.split()), f"invalid {label} fields")
    return value


def config_from(raw):
    cfg = fields(decode(raw), "schema allocation powerShell powerShellSha256 nativeHelperSha256 nvidiaSmi "
                            "nvidiaSmiSha256 gpuUuid serviceNames applicationExecutables applicationProviders",
                 "Windows collector configuration")
    need(cfg["schema"] == CONFIG, "unknown Windows collector configuration schema")
    allocation = cfg["allocation"]
    need(type(allocation) is str and allocation.strip() and len(allocation) <= 256 and allocation.isprintable(),
         "expected the approved host allocation")
    powershell = cfg["powerShell"]
    need(type(powershell) is str and powershell.isprintable()
         and (native_tool(powershell, "powershell.exe") or
              (powershell.startswith("/") and not powershell.startswith("//")
               and Path(powershell).name.casefold() == "powershell.exe")),
         "expected an absolute native or WSL-mounted powershell.exe")
    need(native_tool(cfg["nvidiaSmi"], "nvidia-smi.exe"), "expected an absolute Windows NVIDIA-SMI path")
    for name in ("powerShellSha256", "nativeHelperSha256", "nvidiaSmiSha256"):
        need(type(cfg[name]) is str and SHA256.fullmatch(cfg[name]), f"expected a reviewed {name}")
    need(type(cfg["gpuUuid"]) is str and re.fullmatch("GPU-" + UUID, cfg["gpuUuid"], re.I),
         "expected an assigned NVIDIA GPU UUID")
    for name in ("serviceNames", "applicationExecutables", "applicationProviders"):
        values = cfg[name]
        need(type(values) is list and len(values) <= 16 and all(
            type(item) is str and item == item.strip() and 1 <= len(item) <= 128 and item.isprintable()
            for item in values) and len(set(map(str.casefold, values))) == len(values), f"invalid or duplicate {name}")
    need(all(re.fullmatch(r"[a-zA-Z0-9._-]{1,124}\.exe", item, re.I) for item in cfg["applicationExecutables"]),
         "expected explicit bare executable names ending in .exe")
    need(any(cfg[name] for name in ("serviceNames", "applicationExecutables", "applicationProviders")),
         "expected at least one approved model service or application identity")
    return cfg


def native_tool(value, filename):
    return type(value) is str and value.isprintable() and '"' not in value and bool(re.fullmatch(
        r"[A-Za-z]:\\(?:[^\r\n]+\\)?" + re.escape(filename), value, re.I))


def verify_config(path, expected_sha=None, expected_allocation=None):
    raw = config_bytes(path)
    cfg = config_from(raw)
    digest = sha(raw)
    need(expected_sha is None or expected_sha == digest, "Windows configuration differs from its expected SHA-256")
    need(expected_allocation is None or expected_allocation == cfg["allocation"], "Windows allocation differs")
    need(sha(HELPER.read_bytes()) == cfg["nativeHelperSha256"], "Windows helper differs from its reviewed SHA-256")
    return raw, cfg


def host_identity(value, cfg):
    fields(value, "machineGuid computer bootAt osVersion osBuild gpu driver", "Windows host identity")
    need(all(type(item) is str for item in value.values()), "Windows identity fields must be strings")
    guid = value["machineGuid"].lower()
    need(re.fullmatch(UUID, guid) and len(set(guid.replace("-", ""))) > 1, "invalid Windows machine GUID")
    need(re.fullmatch(r"[a-zA-Z0-9._-]{1,253}", value["computer"]), "invalid Windows computer name")
    need(re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", value["osVersion"])
         and re.fullmatch(r"[0-9]{4,8}", value["osBuild"]), "invalid Windows build identity")
    need(value["gpu"].casefold() == cfg["gpuUuid"].casefold()
         and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", value["driver"]), "Windows GPU or NVIDIA driver differs")
    boot = iso(value["bootAt"])
    machine = sha(guid.encode())
    return {"machine": machine, "boot": sha(f"{machine}/{stamp(boot)}".encode()),
            "os": f"Windows {value['osVersion']} build {value['osBuild']}",
            "gpu": "GPU-" + value["gpu"][4:].lower(), "driver": "nvidia " + value["driver"],
            "allocation": cfg["allocation"]}, boot


def event_from(raw, channel, computer):
    need(type(raw) is str and "<!" not in raw, "invalid Windows event XML")
    event = ElementTree.fromstring(raw)
    system = event.find("e:System", NAMESPACE)
    need(event.tag == "{" + NAMESPACE["e"] + "}Event" and system is not None, "invalid Windows event schema")

    def field(name):
        return system.findtext("e:" + name, namespaces=NAMESPACE) or ""

    def attribute(tag, name):
        node = system.find("e:" + tag, NAMESPACE)
        return node.get(name, "") if node is not None else ""

    provider = attribute("Provider", "Name")
    event_id, record_id, level = field("EventID"), field("EventRecordID"), field("Level")
    need(field("Channel") == channel and field("Computer").split(".")[0].casefold() == computer.split(".")[0].casefold(),
         "Windows event came from another computer or channel")
    need(provider and provider.isprintable() and re.fullmatch(r"[0-9]{1,5}", event_id)
         and re.fullmatch(r"[1-9][0-9]{0,19}", record_id) and re.fullmatch(r"[0-9]{1,3}", level),
         "invalid Windows event provider, ID, record ID or level")
    values = {value.strip().casefold() for section in ("EventData", "UserData")
              for node in event.findall("e:" + section, NAMESPACE) for value in node.itertext() if value.strip()}
    return provider.casefold(), int(event_id), int(record_id), int(level), iso(attribute("TimeCreated", "SystemTime")), values


def classes(event, channel, cfg):
    provider, event_id, _, level, _, values = event
    lowered = lambda key: {item.casefold() for item in cfg[key]}
    severe = level in (1, 2)
    markers = any(FAILURE_WORDS.search(value) for value in values)
    gpu = (provider == "nvlddmkm" or (provider == "display" and event_id == 4101)
           or (provider in GPU_PROVIDERS and (severe or markers)))
    hardware = (provider == "microsoft-windows-whea-logger"
                or (provider == "microsoft-windows-kernel-power" and event_id in (41, 42, 107))
                or (provider == "eventlog" and event_id == 6008)
                or (provider in ("bugcheck", "microsoft-windows-wer-systemerrorreporting") and event_id == 1001))
    service = (provider == "service control manager" and event_id in SCM_FAILURES
               and bool(values & lowered("serviceNames")))
    crash_names = {PureWindowsPath(value).name for value in values}
    app = ((provider in lowered("applicationProviders") and (severe or markers))
           or (provider in APP_FAILURE_PROVIDERS and bool(crash_names & lowered("applicationExecutables"))))
    labels = []
    if hardware or service or app or (channel == "System" and severe):
        labels.append("system")
    if gpu:
        labels.append("gpu")
    return labels


def xpath_for(since, until):
    def fixed_time(at):
        return at.isoformat(timespec="microseconds").replace("+00:00", "0Z")

    return f"*[System[TimeCreated[@SystemTime >= '{fixed_time(since)}' and @SystemTime < '{fixed_time(until)}']]]"


def anchor(value, channel, computer, since):
    fields(value, "oldestRecordId recordCount logFilePath logMode xml", "Windows retention anchor")
    need(type(value["oldestRecordId"]) is int and type(value["recordCount"]) is int and value["recordCount"] > 0
         and type(value["logFilePath"]) is str and value["logFilePath"].strip()
         and value["logMode"] in ("Circular", "AutoBackup", "Retain"), "invalid Windows log retention metadata")
    _, _, record_id, _, when, _ = event_from(value["xml"], channel, computer)
    need(record_id == value["oldestRecordId"] and when <= since, "Windows log has no readable start boundary")
    return when


def capture(native, cfg, since, until, config_sha, collector_sha, argv):
    packet = fields(decode(native), "schema powershellVersion startedAt finishedAt identityBefore identityAfter channels",
                    "native Windows log export")
    need(packet["schema"] == NATIVE and isinstance(packet["powershellVersion"], str)
         and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", packet["powershellVersion"]), "unrecognized Windows log export")
    need(EPOCH < since < until <= iso(packet["startedAt"]) <= iso(packet["finishedAt"]), "invalid Windows capture interval")
    host, boot = host_identity(packet["identityBefore"], cfg)
    need(packet["identityBefore"] == packet["identityAfter"] and EPOCH < boot <= since,
         "Windows boot, hardware or operating system changed or does not cover the interval")
    computer = packet["identityBefore"]["computer"]
    channel_rows = fields(packet["channels"], "System Application", "Windows event channels")
    proof = {}
    events = {"system": [], "gpu": []}
    scope_logs = {}
    start = boot
    for channel in CHANNELS:
        data = fields(channel_rows[channel], "xpath before events after", "Windows event channel export")
        need(data["xpath"] == xpath_for(since, until), "native Windows XPath differs from the reviewed interval query")
        before, after, records = data["before"], data["after"], data["events"]
        before_at = anchor(before, channel, computer, since)
        after_at = anchor(after, channel, computer, since)
        start = max(start, before_at, after_at)
        stable = ("oldestRecordId", "logFilePath", "logMode", "xml")
        need(all(before[name] == after[name] for name in stable) and after["recordCount"] >= before["recordCount"],
             "Windows log rotated, cleared or changed configuration during capture")
        need(type(records) is list and len(records) <= 12000, "incomplete or oversized Windows event record list")
        if before_at == since:
            need(before["xml"] in records, "Windows window omitted the start-boundary witness")
        seen = set()
        for raw in records:
            event = event_from(raw, channel, computer)
            provider, event_id, record_id, _, when, _ = event
            need(record_id not in seen and record_id >= before["oldestRecordId"] and since <= when < until,
                 "duplicate or out-of-window Windows event")
            seen.add(record_id)
            need(not ((provider == "microsoft-windows-eventlog" and event_id == 104)
                      or (provider == "microsoft-windows-kernel-general" and event_id == 1)),
                 "Windows log clearing or system-clock change prevents a continuous observation")
            for destination in classes(event, channel, cfg):
                events[destination].append({"id": f"{channel}/{record_id}", "at": stamp(when), "record": raw})
        proof[channel] = {"xpath": data["xpath"], "before": before, "after": after, "queriedRecords": len(records)}
        scope_logs[channel] = {"path": before["logFilePath"], "mode": before["logMode"]}

    common = {"collectorSha256": collector_sha, "nativeHelperSha256": cfg["nativeHelperSha256"],
              "powerShellSha256": cfg["powerShellSha256"], "powershellVersion": packet["powershellVersion"],
              "nvidiaSmiSha256": cfg["nvidiaSmiSha256"], "channels": scope_logs,
              "interval": "half-open UTC TimeCreated", "serviceNames": sorted(map(str.casefold, cfg["serviceNames"])),
              "applicationExecutables": sorted(map(str.casefold, cfg["applicationExecutables"])),
              "applicationProviders": sorted(map(str.casefold, cfg["applicationProviders"]))}
    sources = {}
    for label in events:
        scope = {**common, "source": label}
        sources[label] = {"sourceId": f"local-windows-event-log/{host['machine']}/{host['boot']}/{label}",
                          "querySha256": sha(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()),
                          "complete": True, "readableFrom": stamp(start), "readableUntil": stamp(until),
                          "events": sorted(events[label], key=lambda row: (row["at"], row["id"])), "queryScope": scope}
    return {"schema": CAPTURE, "host": host, "since": stamp(since), "until": stamp(until), "sources": sources,
            "provenance": {"kind": "local Windows System and Application Event Logs", "configurationSha256": config_sha,
                           "startedAt": packet["startedAt"], "finishedAt": packet["finishedAt"], "argv": argv,
                           "nativeStdoutSha256": sha(native), "nativeStdoutBytes": len(native), "nativeExit": 0,
                           "nativeStderrSha256": sha(b""), "channels": proof}}


def file_sha(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def host_powershell(cfg, since, until):
    power_shell = Path(cfg["powerShell"])
    need(power_shell.is_absolute() and power_shell.resolve() == power_shell and power_shell.is_file()
         and os.access(power_shell, os.X_OK), "expected a resolved native PowerShell executable")
    need(file_sha(power_shell) == cfg["powerShellSha256"], "PowerShell executable differs from its reviewed SHA-256")
    if sys.platform == "win32":
        helper = str(HELPER)
    else:
        need(sys.platform == "linux" and "microsoft" in os.uname().release.lower(), "Windows host capture requires Windows or WSL")
        converted = subprocess.run(["/usr/bin/wslpath", "-w", str(HELPER)], capture_output=True, check=True, timeout=5)
        need(not converted.stderr, "wslpath returned a diagnostic")
        helper = converted.stdout.decode("utf-8").strip()
        drive = PureWindowsPath(helper).drive.casefold()
        need(PureWindowsPath(helper).is_absolute() and helper.isprintable()
             and (re.fullmatch(r"[a-z]:", drive) or drive.startswith(("\\\\wsl.localhost\\", "\\\\wsl$\\"))),
             "wslpath did not return a local Windows or WSL helper path")
    argv = [str(power_shell), "-NoLogo", "-NoProfile", "-NonInteractive", "-File", helper,
            "-Since", stamp(since), "-Until", stamp(until), "-ExpectedHelperSha256", cfg["nativeHelperSha256"],
            "-NvidiaSmi", cfg["nvidiaSmi"], "-NvidiaSmiSha256", cfg["nvidiaSmiSha256"], "-GpuUuid", cfg["gpuUuid"]]
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=95)
    if result.returncode or result.stderr:
        detail = result.stderr[:2048].decode("utf-8", errors="replace").strip()
        raise ValueError(f"local Windows Event Log reader failed ({result.returncode}): {detail}")
    need(len(result.stdout) <= READ_BUDGET and result.stdout.endswith(b"\n"), "incomplete or oversized native log output")
    need(file_sha(power_shell) == cfg["powerShellSha256"], "PowerShell changed during log capture")
    return result.stdout, argv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--check-config", type=Path, metavar="FILE")
    parser.add_argument("--expected-config-sha256")
    parser.add_argument("--expected-allocation")
    args = parser.parse_args()
    try:
        if args.check_config is not None:
            need(args.since is None and args.until is None, "offline configuration check cannot capture logs")
            raw, _ = verify_config(args.check_config, args.expected_config_sha256, args.expected_allocation)
            value = {"status": "COLLECTOR_CONFIG_OFFLINE_VALIDATED", "configurationSha256": sha(raw),
                     "hostCompatibilityAndLogAccess": "UNVERIFIED"}
        else:
            need(args.since and args.until and args.expected_config_sha256 is None and args.expected_allocation is None,
                 "capture requires --since and --until; expectation flags require --check-config")
            location = os.environ.get("AIJADE_P2_LOG_CONFIG")
            need(location, "AIJADE_P2_LOG_CONFIG must name the reviewed configuration")
            path = Path(location)
            raw, cfg = verify_config(path)
            since, until = iso(args.since), iso(args.until)
            need(EPOCH < since < until <= datetime.now(timezone.utc), "invalid or future Windows capture cutoff")
            native, argv = host_powershell(cfg, since, until)
            need(verify_config(path)[0] == raw, "Windows collector configuration changed during capture")
            value = capture(native, cfg, since, until, sha(raw), file_sha(Path(__file__)), argv)
    except (ValueError, OSError, OverflowError, subprocess.SubprocessError, ElementTree.ParseError) as error:
        print(f"Windows log capture refused: {error}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
