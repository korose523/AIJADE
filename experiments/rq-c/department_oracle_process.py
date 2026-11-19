"""Verify a complete P2-R replay process and compare its two retained outputs."""

import re

from department_oracle_evidence import SKIPPED, VARIANTS, decode_evidence, derive_case_outcome, require_fields
from prepare_department_regeneration import encoded, instant, require, sha
from regen_compare_v2 import SHA256


APPROVAL_SCHEMA = "aijade.p2-r.department-oracle-replay-approval.v1"
PROCESS_SCHEMA = "aijade.p2-r.department-oracle-replay-process.v1"
APPROVAL_FILE = "execution-approval.json"
PROCESS_FILE = "process-receipt.json"
INPUT_FILE = "evaluator-input.json"
STDOUT_FILE = "evaluator-stdout.json"
RAW_EVENTS_FILE = "evaluator-events.jsonl"
STREAM_FILES = (INPUT_FILE, STDOUT_FILE, RAW_EVENTS_FILE)
PROCESS_FILES = frozenset((APPROVAL_FILE, PROCESS_FILE, INPUT_FILE, STDOUT_FILE))
COMPLETE = "REPLAY_PROCESS_EVIDENCE_COMPLETE"
REFUSED = "REPLAY_PROCESS_EVIDENCE_REFUSED"


def ordered_programs(manifest):
    return [(group, entry) for group, data in sorted(manifest["groups"].items()) for entry in data["programs"]]


def streams(documents):
    return {name: {"sha256": sha(documents[name]), "bytes": len(documents[name])} for name in STREAM_FILES}


def context_fields(invocation):
    return {name: invocation[name] for name in ("evidenceScope", "sessionId", "manifestFileSha256")}


def validate_input(raw, manifest, contract, invocation):
    data = decode_evidence(raw)
    require_fields(data, {"tasks", "pairs", "dropped", "observationContext"}, "replay process input")
    require(data["observationContext"] == context_fields(invocation)
            and sha(raw) == invocation["evaluatorInputSha256"], "process input identity differs")
    require_fields(data["tasks"], set(contract["tasks"]), "process input tasks")
    require(encoded(data["dropped"]) == encoded(contract["removedCaseArgs"]), "process exclusion rule differs")
    for name, task in data["tasks"].items():
        require_fields(task, {"tests", "timeoutMs"}, "process input task")
        rule = contract["tasks"][name]
        timeout = 2000 if task["timeoutMs"] is None else task["timeoutMs"]
        require(type(timeout) is int and timeout == rule["timeoutMs"] and type(task["tests"]) is list
                and sha(encoded(task["tests"])) == rule["casesSha256"], "process input task or cases differ")
    require(type(data["pairs"]) is list and len(data["pairs"]) == len(ordered_programs(manifest)),
            "process input candidate population differs")
    for pair, (_, reviewed) in zip(data["pairs"], ordered_programs(manifest)):
        require(type(pair) is list and len(pair) == 2 and all(isinstance(value, str) for value in pair)
                and pair[0] == reviewed["taskId"] and sha(pair[1].encode()) == reviewed["codeSha256"],
                "process input candidate identity differs")
    return data


def validate_stdout(raw, manifest, groups, tasks, contract):
    report = decode_evidence(raw)
    population = ordered_programs(manifest)
    require(type(report) is list and len(report) == len(population), "stdout does not cover the full program population")
    observed = {(group, entry["taskId"], entry["codeSha256"]): entry
                for group, data in groups.items() for entry in data["programs"]}
    for row, (group, program) in zip(report, population):
        task = program["taskId"]
        observation = observed[group, task, program["codeSha256"]]
        if observation["status"] == SKIPPED:
            require(row == {"skipped": True} and type(row["skipped"]) is bool,
                    "stdout differs from the recorded lexical skip")
            continue
        require_fields(row, set(VARIANTS), "stdout program")
        rule = contract["tasks"][task]
        for variant in VARIANTS:
            result = row[variant]
            indices = rule["entryAndTestCaseIndices" if variant == "entryAndTest" else "caseIndices"]
            outcome = derive_case_outcome(observation[variant], indices)
            status = outcome["outcome"]
            fields = {"ok", "via", "failing"}
            error = status in ("TIMEOUT", "SETUP_ERROR", "NO_CALLABLE")
            require_fields(result, fields | ({"error"} if error else set()), "stdout variant")
            require(result["ok"] is (status == "PASSED") and type(result["failing"]) is list
                    and len(result["failing"]) == len(outcome["failedCaseIndices"]),
                    "stdout verdict or complete failure population disagrees with case events")
            via = result["via"]
            if status in ("SETUP_ERROR", "NO_CALLABLE"):
                require(via is None and isinstance(result["error"], str)
                        and (result["error"] == "no callable") is (status == "NO_CALLABLE"),
                        "stdout entry failure disagrees with case events")
            else:
                require(via in (("sandbox",) if variant == "asRun" else ("sandbox", "lexical")),
                        "stdout entry resolution differs")
                if status == "TIMEOUT":
                    require(result["error"] == "timeout", "stdout timeout disagrees with case events")
            for failure, index in zip(result["failing"], outcome["failedCaseIndices"]):
                case = tasks[task]["tests"][index]
                require(type(failure) is dict and set(failure) in (
                    {"args", "expected"}, {"args", "expected", "actual"}, {"args", "expected", "threw"},
                ) and all(isinstance(value, str) for value in failure.values())
                        and failure["args"] == case["args"] and failure["expected"] == case["expected"],
                        "stdout failure does not bind the original case")
    return {"programs": len(population), "variants": sum(len(VARIANTS) for row in report if "skipped" not in row)}


def process_binding(approval, invocation, manifest):
    return {"binding": manifest["binding"], **context_fields(invocation),
            "evaluatorInputSha256": invocation["evaluatorInputSha256"],
            "sourceCommit": approval["sourceCommit"], "regenerationApprovalSha256": approval["regenerationApprovalSha256"]}


def verify_execution_approval(value, invocation, manifest, artifact_sha, node_sha):
    require_fields(value, {"schema", "scope", "binding", "manifestFileSha256", "evidenceScope", "sessionId",
                           "evaluatorInputSha256", "sourceCommit", "evaluatorSha256", "node", "hostName",
                           "notBefore", "notAfter", "supervisorReply", "approvedPlan", "regenerationApprovalSha256"},
                   "replay execution approval")
    require(value["schema"] == APPROVAL_SCHEMA and value["scope"] == "P2-R-department-oracle-replay"
            and all(value[key] == expected for key, expected in process_binding(value, invocation, manifest).items())
            and value["evaluatorSha256"] == artifact_sha, "replay execution approval binds other inputs or evaluator")
    require_fields(value["node"], {"path", "sha256", "environment"}, "approved replay runtime")
    reply, plan = value["supervisorReply"], value["approvedPlan"]
    require_fields(reply, {"path", "sha256", "reviewedSender", "receivedAt"}, "reviewed supervisor reply")
    require_fields(plan, {"path", "sha256"}, "reviewed replay plan")
    require(all(isinstance(item["path"], str) and item["path"].strip()
                and isinstance(item["sha256"], str) and SHA256.fullmatch(item["sha256"]) for item in (reply, plan))
            and isinstance(reply["reviewedSender"], str) and reply["reviewedSender"].strip(),
            "reviewed plan or reply identity is incomplete")
    require(isinstance(value["hostName"], str) and value["hostName"].strip()
            and isinstance(value["sourceCommit"], str) and re.fullmatch(r"[0-9a-f]{40}", value["sourceCommit"])
            and isinstance(value["regenerationApprovalSha256"], str) and SHA256.fullmatch(value["regenerationApprovalSha256"])
            and isinstance(value["node"]["path"], str) and value["node"]["sha256"] == node_sha
            and instant(reply["receivedAt"]) <= instant(value["notBefore"]) < instant(value["notAfter"]),
            "replay execution approval binds another runtime, plan or invalid window")
    return value


def verify_process(documents, hashes, manifest, contract, invocation, environment, groups, capture_start, capture_end,
                   reviewed_at, expected_close, expected_regeneration_approval):
    approval = verify_execution_approval(decode_evidence(documents[APPROVAL_FILE]), invocation, manifest,
                                        hashes["evaluator.bin"], hashes["node.bin"])
    receipt = decode_evidence(documents[PROCESS_FILE])
    fields = {"schema", "status", "executionApprovalSha256", "processStarted", "termination", "exitCode",
              "startedAtUtc", "finishedAtUtc", "invocationContractSha256", "fileEvidence", "error",
              "hostName", "stdoutReadback"}
    binding = process_binding(approval, invocation, manifest)
    require_fields(receipt, fields | set(binding), "replay process receipt")
    require(receipt["schema"] == PROCESS_SCHEMA and receipt["status"] == COMPLETE
            and receipt["processStarted"] is True and receipt["termination"] == "EXITED"
            and type(receipt["exitCode"]) is int and receipt["exitCode"] == 0 and receipt["error"] is None,
            "replay process did not exit successfully")
    require(all(receipt[key] == value for key, value in binding.items())
            and receipt["executionApprovalSha256"] == hashes[APPROVAL_FILE]
            and receipt["invocationContractSha256"] == hashes["invocation.json"]
            and receipt["hostName"] == approval["hostName"]
            and approval["regenerationApprovalSha256"] == expected_regeneration_approval
            and encoded(receipt["fileEvidence"]) == encoded(streams(documents))
            and encoded(approval["node"]["environment"]) == encoded(environment),
            "process receipt does not bind the approval, invocation and complete raw streams")
    start, end = instant(receipt["startedAtUtc"]), instant(receipt["finishedAtUtc"])
    require(expected_close is not None
            and max(instant(approval["notBefore"]), instant(expected_close)) <= start
            <= capture_start < capture_end <= end <= min(instant(approval["notAfter"]), reviewed_at),
            "process timestamps do not cover the completed evaluator or approved window")
    data = validate_input(documents[INPUT_FILE], manifest, contract, invocation)
    proof = validate_stdout(documents[STDOUT_FILE], manifest, groups, data["tasks"], contract)
    require(encoded(receipt["stdoutReadback"]) == encoded(proof), "process receipt stdout population differs")
    return {"processReceiptSha256": hashes[PROCESS_FILE], "executionApprovalSha256": hashes[APPROVAL_FILE],
            "processExitCode": receipt["exitCode"], "stdoutSha256": hashes[STDOUT_FILE],
            "stdoutBytes": len(documents[STDOUT_FILE]), "rawStderrBytes": len(documents[RAW_EVENTS_FILE]),
            "stdoutReadback": proof}
