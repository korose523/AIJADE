#!/usr/bin/python3
"""Read-only P2-R error-log capture for an approved Linux NVIDIA system journal."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import time


CONFIG = "aijade.p2-r.linux-journal-collector.v1"
CAPTURE = "aijade.p2-r.department-log-capture.v1"
SOURCE_FIELDS = (
    "_MACHINE_ID", "_BOOT_ID", "_TRANSPORT", "_SYSTEMD_UNIT", "SYSLOG_IDENTIFIER",
    "OBJECT_SYSTEMD_UNIT", "UNIT", "MESSAGE", "MESSAGE_ID", "PRIORITY",
)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
READ_BUDGET = 32 * 1024 * 1024
QUERY_BUDGET_SECONDS = 90
GPU_LABEL = re.compile(r"\b(?:nvidia|nvrm|nouveau|amdgpu|gpu|drm|gsp|cuda|nvlink|nvml)\b", re.I)
GPU_FAILURE = re.compile(r"\b(?:xid|fault|fail(?:ed|ure)?|error|reset|hang|timeout|timed out|fallen off|uncorrectable|fatal)\b", re.I)
HOST_FAILURE = re.compile(r"\b(?:hardware error|machine check|mce|edac|uncorrectable|kernel panic|oom-kill|out of memory|watchdog|segfault)\b", re.I)
SERVICE_FAILURE = re.compile(r"\b(?:panic|failed|failure|error|aborted|crash(?:ed|ing)?|segfault|oom|watchdog|exited with|killed|signal)\b", re.I)
CAPTURE_LOSS = re.compile(
    r"(?:suppressed\s+\d+\s+messages|missed\s+\d+\s+kernel messages|"
    r"\bdropped\s+\d+\s+messages|\blost\s+\d+\s+(?:kernel\s+)?messages|"
    r"journal file .*corrupt|rate limit.*discard)",
    re.I,
)
CAPTURE_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "SYSTEMD_COLORS": "0"}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pin_file(path, wanted):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    need(result.hexdigest() == wanted, "journalctl executable hash differs from the reviewed configuration")


def slots(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def decode(raw):
    def invalid(literal):
        raise ValueError(f"non-finite JSON: {literal}")

    return json.loads(raw, object_pairs_hook=slots, parse_constant=invalid)


def iso(value):
    need(type(value) is str, "expected a zoned ISO-8601 time")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    need(stamp.tzinfo is not None, "expected a zoned ISO-8601 time")
    return stamp.astimezone(timezone.utc)


def stamp(when):
    return when.astimezone(timezone.utc).isoformat(timespec="microseconds")


def journal_time(when):
    delta = when.astimezone(timezone.utc) - EPOCH
    return f"@{delta.days * 86400 + delta.seconds}.{delta.microseconds:06d}"


def config_from(raw):
    obj = decode(raw)
    need(type(obj) is dict and set(obj) == {
        "schema", "allocation", "pciAddress", "journalctl", "journalctlSha256", "serviceUnits",
    } and obj["schema"] == CONFIG, "unknown or incomplete Linux collector configuration")
    need(type(obj["allocation"]) is str and obj["allocation"].strip() and len(obj["allocation"]) <= 256
         and obj["allocation"].isprintable(), "expected the approved allocation identifier")
    need(type(obj["pciAddress"]) is str and re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", obj["pciAddress"]),
         "expected a lowercase PCI device address with its domain")
    need(type(obj["journalctl"]) is str and Path(obj["journalctl"]).is_absolute(),
         "journalctl path must be absolute")
    need(type(obj["journalctlSha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", obj["journalctlSha256"]),
         "expected a pinned journalctl SHA-256")
    units = obj["serviceUnits"]
    need(type(units) is list and 1 <= len(units) <= 16
         and all(type(unit) is str and re.fullmatch(r"[a-zA-Z0-9_.@-]{1,150}\.service", unit) for unit in units)
         and len(set(units)) == len(units), "expected explicit unique system service units")
    return obj


def identity(cfg, read):
    machine = read("/etc/machine-id").strip()
    boot = read("/proc/sys/kernel/random/boot_id").strip()
    need(re.fullmatch(r"[0-9a-f]{32}", machine) and machine != "0" * 32, "missing Linux machine identity")
    need(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot)
         and boot.replace("-", "") != "0" * 32, "missing Linux boot identity")
    release = read("/proc/sys/kernel/osrelease").strip()
    driver = read("/sys/module/nvidia/version").strip()
    need(re.fullmatch(r"[a-zA-Z0-9_.+-]{1,120}", release), "missing kernel release")
    need(re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", driver), "missing NVIDIA module version")
    pci = cfg["pciAddress"]
    vendor = read(f"/sys/bus/pci/devices/{pci}/vendor").strip()
    need(vendor == "0x10de", "the approved PCI address is not an NVIDIA device")
    info = read(f"/proc/driver/nvidia/gpus/{pci}/information")
    uuid = re.findall(r"^GPU UUID:\s*(GPU-[0-9a-fA-F-]{36})\s*$", info, flags=re.M)
    need(len(uuid) == 1 and re.fullmatch(r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", uuid[0]),
         "missing NVIDIA device UUID at the approved PCI address")
    return {"machine": machine, "boot": boot.replace("-", ""), "os": "Linux " + release,
            "gpu": uuid[0], "driver": "nvidia " + driver, "allocation": cfg["allocation"]}


def bounded_query(command, seconds, budget):
    """Run one direct child and bound total stdout/stderr in memory."""
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          stdin=subprocess.DEVNULL, env=CAPTURE_ENV) as child:
        try:
            buffers = {"stdout": bytearray(), "stderr": bytearray()}
            remaining = budget
            deadline = time.monotonic() + seconds
            with selectors.DefaultSelector() as channels:
                channels.register(child.stdout, selectors.EVENT_READ, "stdout")
                channels.register(child.stderr, selectors.EVENT_READ, "stderr")
                while channels.get_map():
                    left = deadline - time.monotonic()
                    need(left > 0, "journal query timed out")
                    ready = channels.select(left)
                    need(ready, "journal query timed out")
                    for selected, _ in ready:
                        data = os.read(selected.fd, min(65536, remaining + 1))
                        if not data:
                            channels.unregister(selected.fd)
                            continue
                        need(len(data) <= remaining, "journal query exceeded its evidence byte limit")
                        remaining -= len(data)
                        buffers[selected.data].extend(data)
            return child.wait(timeout=max(0.001, deadline - time.monotonic())), bytes(buffers["stdout"]), bytes(buffers["stderr"])
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()


def journal_row(line, host):
    obj = decode(line)
    need(type(obj) is dict and obj.get("_MACHINE_ID") == host["machine"] and obj.get("_BOOT_ID") == host["boot"],
         "journal returned a different machine or boot")
    cursor, timestamp = obj.get("__CURSOR"), obj.get("__REALTIME_TIMESTAMP")
    need(type(cursor) is str and 1 <= len(cursor) <= 4096 and cursor.isprintable(), "missing journal cursor")
    need(type(timestamp) is str and re.fullmatch(r"[0-9]{1,18}", timestamp), "missing journal realtime timestamp")
    return obj, EPOCH + timedelta(microseconds=int(timestamp))


def message_text(message):
    if type(message) is str:
        return message
    if type(message) is list and all(type(value) is int and 0 <= value <= 255 for value in message):
        return bytes(message).decode("utf-8", errors="replace")
    need(message is None, "unexpected journal MESSAGE representation")
    return ""


def classes(record, units):
    text = message_text(record.get("MESSAGE"))
    identifier, transport, unit, object_unit, manager_unit = (
        record.get(k, "") for k in ("SYSLOG_IDENTIFIER", "_TRANSPORT", "_SYSTEMD_UNIT", "OBJECT_SYSTEMD_UNIT", "UNIT")
    )
    need(all(type(value) is str for value in (identifier, transport, unit, object_unit, manager_unit)),
         "ambiguous journal transport or service identity")
    need(not CAPTURE_LOSS.search(text), "the journal reports suppressed, lost, dropped or corrupt records")
    priority = record.get("PRIORITY")
    need(priority is None or type(priority) is str and re.fullmatch("[0-7]", priority), "invalid journal priority")
    severe = priority is not None and int(priority) <= 3
    tagged_gpu = GPU_LABEL.search(identifier + " " + text)
    service = unit in units or object_unit in units or (identifier == "systemd" and (
        manager_unit in units
        or any(re.search(r"(?<![\w.@-])" + re.escape(name) + r"(?![\w.@-])", text) for name in units)
    ))
    result = set()
    if severe or HOST_FAILURE.search(text) or (service and SERVICE_FAILURE.search(text)):
        result.add("system")
    if tagged_gpu and (severe or GPU_FAILURE.search(text)) and (transport == "kernel" or service):
        result.add("gpu")
    return result


def query_base(cfg, host):
    return [cfg["journalctl"], "--system", "--local", "--no-pager", "--all",
            "--output=json", "--output-fields=" + ",".join(SOURCE_FIELDS),
            "--boot=" + host["boot"]]


def capture(cfg, since, until, read, run_query, clock, monotonic, collector_sha):
    started = clock()
    need(EPOCH < since < until <= started, "journal interval is invalid or its cutoff has not yet occurred")
    cutoff = monotonic() + QUERY_BUDGET_SECONDS
    host = identity(cfg, read)
    base = query_base(cfg, host)
    proof = {}
    remaining = READ_BUDGET

    def query(label, command):
        nonlocal remaining
        elapsed_limit = cutoff - monotonic()
        need(elapsed_limit > 0, "collector exhausted its query time budget")
        code, raw, diagnostic = run_query(command, elapsed_limit, remaining)
        need(code == 0, f"{label}: journalctl exited unsuccessfully")
        need(not diagnostic.strip(), f"{label}: journalctl reported a diagnostic; check access, retention and integrity")
        remaining -= len(raw) + len(diagnostic)
        need(remaining >= 0, "collector exceeded its total evidence byte limit")
        proof[label] = {"argv": command, "exit": code, "stdoutSha256": sha(raw),
                        "stdoutBytes": len(raw), "stderrSha256": sha(diagnostic)}
        need(not raw or raw.endswith(b"\n"), f"{label}: partial journal output")
        return [] if raw == b"-- No entries --\n" else raw.splitlines()

    version = query("journalctlVersion", [cfg["journalctl"], "--version"])
    need(version and re.fullmatch(rb"systemd [0-9]+(?: .*)?", version[0]), "unrecognized journalctl version")
    version_line = version[0].decode("utf-8")
    proof["journalctlVersion"]["version"] = version_line

    def anchor(label, transport=None):
        filters = [f"_TRANSPORT={transport}"] if transport is not None else []
        lines = query(label, base + ["--reverse", "--until=" + journal_time(since), "--lines=1"] + filters)
        need(len(lines) == 1, f"{label}: retained journal has no readable entry at or before the requested start")
        obj, at = journal_row(lines[0], host)
        need(at <= since and (transport is None or obj.get("_TRANSPORT") == transport),
             f"{label}: journal entry does not establish its coverage boundary")
        need(not CAPTURE_LOSS.search(message_text(obj.get("MESSAGE"))),
             f"{label}: the coverage witness reports dropped or corrupted records")
        proof[label].update(cursor=obj["__CURSOR"], at=stamp(at), raw=lines[0].decode("utf-8"))
        return lines[0], at

    floor, floor_at = anchor("systemAtStart")
    kernel, kernel_at = anchor("kernelAtStart", "kernel")
    records = query("window", base + ["--since=" + journal_time(since), "--until=" + journal_time(until)])
    need((floor_at != since or floor in records) and (kernel_at != since or kernel in records),
         "journal window omitted a start-boundary witness")
    events = {"system": [], "gpu": []}
    seen = set()
    for record in records:
        obj, at = journal_row(record, host)
        ident = obj["__CURSOR"]
        need(ident not in seen and since <= at <= until, "duplicate or out-of-window journal entry")
        seen.add(ident)
        if at == until:  # journalctl --until includes the cutoff itself.
            continue
        for label in classes(obj, cfg["serviceUnits"]):
            events[label].append({"id": ident, "at": stamp(at), "record": record.decode("utf-8")})
    need(anchor("systemRecheck")[0] == floor and anchor("kernelRecheck", "kernel")[0] == kernel,
         "journal coverage witness changed during the query")
    need(identity(cfg, read) == host, "host or GPU identity changed during the query")
    finished = clock()
    need(finished >= started, "collector clock moved backward")

    def result_for(label, readable_from):
        query_scope = {
            "journalctlSha256": cfg["journalctlSha256"], "collectorSha256": collector_sha,
            "journalctlVersion": version_line, "journalQueryArguments": base[1:],
            "source": label, "sourceFields": SOURCE_FIELDS, "systemJournal": True,
            "serviceUnits": sorted(cfg["serviceUnits"]), "interval": "half-open UTC",
        }
        fingerprint = sha(json.dumps(query_scope, sort_keys=True, separators=(",", ":")).encode())
        return {"sourceId": f"local-system-journal/{host['machine']}/{host['boot']}/{label}",
                "querySha256": fingerprint, "complete": True, "readableFrom": stamp(readable_from),
                "readableUntil": stamp(until), "events": sorted(events[label], key=lambda row: (row["at"], row["id"])),
                "queryScope": query_scope}

    return {"schema": CAPTURE, "host": host, "since": stamp(since), "until": stamp(until),
            "sources": {"system": result_for("system", floor_at), "gpu": result_for("gpu", max(floor_at, kernel_at))},
            "provenance": {"kind": "same-boot retained system journal, queried at or after cutoff",
                           "startedAt": stamp(started), "finishedAt": stamp(finished),
                           "queriedRecords": len(records), "queries": proof}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True)
    parser.add_argument("--until", required=True)
    args = parser.parse_args()
    try:
        need(sys.platform == "linux", "this collector requires Linux; verify the actual assigned host first")
        path = Path(os.environ.get("AIJADE_P2_LOG_CONFIG", ""))
        need(path.is_absolute() and path.resolve() == path and path.is_file(),
             "AIJADE_P2_LOG_CONFIG must name the reviewed absolute configuration")
        need(path.stat().st_size <= 65536, "collector configuration is too large")
        settings = path.read_bytes()
        cfg = config_from(settings)
        journalctl = Path(cfg["journalctl"])
        need(journalctl.resolve() == journalctl and journalctl.is_file() and os.access(journalctl, os.X_OK),
             "expected an executable, resolved journalctl path")
        pin_file(journalctl, cfg["journalctlSha256"])

        def read_linux(name):
            with Path(name).open("rb") as source:
                raw = source.read(65537)
            need(len(raw) <= 65536, "host identity source exceeds its size limit")
            return raw.decode("utf-8")

        capture_result = capture(cfg, iso(args.since), iso(args.until), read_linux, bounded_query,
                                 lambda: datetime.now(timezone.utc), time.monotonic,
                                 sha(Path(__file__).read_bytes()))
        pin_file(journalctl, cfg["journalctlSha256"])
        need(path.read_bytes() == settings, "collector configuration changed during capture")
        capture_result["provenance"]["configurationSha256"] = sha(settings)
    except (ValueError, OSError, OverflowError, subprocess.SubprocessError) as error:
        print(f"journal capture refused: {error}", file=sys.stderr)
        return 2
    print(json.dumps(capture_result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
