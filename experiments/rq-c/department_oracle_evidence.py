"""Validate reviewed per-case replay observations and derive the scoring transcript."""

import json

from prepare_department_regeneration import encoded, require, sha
from regen_compare_v2 import SHA256


OBSERVATIONS_SCHEMA = "aijade.p2-r.department-oracle-observations.v1"
EVALUATOR_SCHEMA = "aijade.p2-r.department-oracle-evaluator-receipt.v1"
TRANSCRIPT_SCHEMA = "aijade.p2-r.department-oracle-replay-transcript.v2"
VARIANTS = ("asRun", "entry", "entryAndTest")
OBSERVATION_SCOPES = frozenset({"SYNTHETIC_FIXTURE", "OPERATOR_REVIEWED_EXTERNAL_REPLAY"})
SKIPPED = "SKIPPED_ARCHIVE_HOST_FACILITY"


def decode_evidence(raw):
    def unique(pairs):
        value = dict(pairs)
        require(len(pairs) == len(value), "evidence contains a duplicate object key")
        return value

    def reject_nonfinite(_):
        raise ValueError("evidence contains a non-finite JSON number")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject_nonfinite)


def require_fields(value, fields, label):
    require(type(value) is dict and set(value) == fields, f"{label}: missing or unexpected evidence fields")


def evaluator_receipt(raw, manifest_document, manifest_raw, observations_raw, scope):
    receipt = decode_evidence(raw)
    manifest = manifest_document["manifest"]
    contract = manifest_document["ruleContract"]
    expected = {
        "schema": EVALUATOR_SCHEMA, "evidenceScope": scope,
        "binding": manifest["binding"], "manifestSha256": manifest_document["manifestSha256"],
        "manifestFileSha256": sha(manifest_raw), "observationsFileSha256": sha(observations_raw),
        "referenceReplayEngineSha256": contract["referenceReplayEngineSha256"],
        "groups": {name: {"captureFilesSha256": item["captureFilesSha256"],
                          "programCount": len(item["programs"])}
                   for name, item in manifest["groups"].items()},
    }
    require_fields(receipt, set(expected) | {"evaluatorIdentity"}, "evaluator receipt")
    identity = receipt["evaluatorIdentity"]
    require_fields(identity, {"artifactSha256", "runtimeSha256", "invocationContractSha256", "environmentSha256"},
                   "reviewed evaluator identity")
    require(all(isinstance(value, str) and SHA256.fullmatch(value) for value in identity.values()),
            "reviewed evaluator identity digests are invalid")
    actual = {key: receipt[key] for key in expected}
    require(encoded(actual) == encoded(expected),
            "evaluator receipt does not bind the observed bytes, manifest, rule, phase and group population")
    return receipt


def derive_case_outcome(observed, indices):
    require_fields(observed, {"status", "cases"}, "variant observations")
    status, cases = observed["status"], observed["cases"]
    require(type(cases) is list, "case observations must be an ordered list")
    if status in ("NO_CALLABLE", "SETUP_ERROR"):
        require(not cases, "an entry or setup failure cannot have case observations")
        return {"outcome": status, "failedCaseIndices": []}
    require(status == "CASE_RESULTS" and len(cases) <= len(indices), "invalid case observation population")
    failures = []
    timeout = None
    for ordinal, case in enumerate(cases):
        require_fields(case, {"caseIndex", "result"}, "case observation")
        index = case["caseIndex"]
        require(type(index) is int and index == indices[ordinal], "observed cases must follow exact retained order")
        result = case["result"]
        require(result in ("PASS", "FAIL", "TIMEOUT"), "unknown case observation result")
        if result == "FAIL":
            failures.append(index)
        elif result == "TIMEOUT":
            require(ordinal == len(cases) - 1, "timeout must be the final observation")
            timeout = index
    if timeout is not None:
        return {"outcome": "TIMEOUT", "failedCaseIndices": failures, "timedOutCaseIndex": timeout}
    require(len(cases) == len(indices), "case observations stopped before all retained cases without a timeout")
    return {"outcome": "FAILED_CASES" if failures else "PASSED", "failedCaseIndices": failures}


def derive_programs(observed, pinned, contract):
    require(type(observed) is list and len(observed) == len(pinned), "observed program population differs from the manifest")
    expected = {(item["taskId"], item["codeSha256"]): item["historicalSkipApplies"] for item in pinned}
    derived = {}
    for item in observed:
        require(type(item) is dict and isinstance(item.get("taskId"), str) and isinstance(item.get("codeSha256"), str),
                "invalid observed task or code identity")
        key = item["taskId"], item["codeSha256"]
        require(key in expected and key not in derived, "unknown or duplicate observed program")
        identity = {"taskId": key[0], "codeSha256": key[1]}
        skipped = expected[key]
        status = SKIPPED if skipped else "CAPTURED"
        require_fields(item, set(identity) | {"status"} | (set() if skipped else set(VARIANTS)),
                       "program observations")
        require(item["status"] == status, "observed skip differs from the manifest")
        transcript = {**identity, "status": status}
        if not skipped:
            task = contract["tasks"][key[0]]
            for variant in VARIANTS:
                order = task["entryAndTestCaseIndices" if variant == "entryAndTest" else "caseIndices"]
                transcript[variant] = derive_case_outcome(item[variant], order)
        derived[key] = transcript
    return [derived[item["taskId"], item["codeSha256"]] for item in pinned]


def produce_transcript(manifest_document, manifest_raw, observations_raw, evaluator_raw, expected_scope):
    """Construct a transcript from complete observations. Program code is never evaluated."""
    require(manifest_raw == encoded(manifest_document), "reviewed manifest bytes differ from the selected phase")
    manifest = manifest_document["manifest"]
    contract = manifest_document["ruleContract"]
    observations = decode_evidence(observations_raw)
    require_fields(observations, {"schema", "evidenceScope", "binding", "manifestSha256",
                                  "manifestFileSha256", "groups"}, "observations")
    scope = observations["evidenceScope"]
    require(isinstance(scope, str) and scope in OBSERVATION_SCOPES, "unknown replay evidence scope")
    require(scope == expected_scope, "observed evidence scope requires a matching explicit synthetic or external mode")
    require(observations["schema"] == OBSERVATIONS_SCHEMA
            and observations["binding"] == manifest["binding"]
            and observations["manifestSha256"] == manifest_document["manifestSha256"]
            and observations["manifestFileSha256"] == sha(manifest_raw),
            "observations are for a different manifest, rule or phase")
    receipt = evaluator_receipt(evaluator_raw, manifest_document, manifest_raw, observations_raw, scope)

    require_fields(observations["groups"], set(manifest["groups"]), "observed groups")
    groups = {}
    for name, pinned in manifest["groups"].items():
        item = observations["groups"][name]
        require_fields(item, {"captureFilesSha256", "programs"}, f"{name} observations")
        require(item["captureFilesSha256"] == pinned["captureFilesSha256"], f"{name}: observed capture hashes differ")
        groups[name] = {"captureFilesSha256": item["captureFilesSha256"],
                        "programs": derive_programs(item["programs"], pinned["programs"], contract)}
    return {
        "schema": TRANSCRIPT_SCHEMA, "binding": manifest["binding"], "evidenceScope": scope,
        "manifestSha256": manifest_document["manifestSha256"], "manifestFileSha256": sha(manifest_raw),
        "observationsFileSha256": sha(observations_raw),
        "reviewedEvaluatorReceiptSha256": sha(evaluator_raw),
        "reviewedEvaluatorIdentity": receipt["evaluatorIdentity"], "groups": groups,
    }
