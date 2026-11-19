"""Passive P2-R case capture checks using only authored inert records."""

from argparse import Namespace
from io import BytesIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import department_oracle_capture as capture
import department_oracle_evidence as evidence
from prepare_department_regeneration import REPO, encoded, sha
import rescore_department_oracle as oracle
from summarize_department_regeneration import Skill


PHASE_CLOSED = "2026-11-19T08:59:00.000000+00:00"
START = "2026-11-19T09:00:00Z"
FINISH = "2026-11-19T09:01:00Z"
REVIEW = "2026-11-19T09:02:00Z"
SESSION = sha(b"authored fixture session")
GROUPS = ("second-family", "template-a", "template-b")
TASK = "inert-case-fixture"
SKIPPED_CODE = "process synthetic fixture token"


class CaptureFixture:
    def __init__(self, root):
        self.root = root
        self.directory = root / "capture-directory"
        self.directory.mkdir()
        self.operator = root / "operator-review.json"
        self.manifest_file = root / "manifest.json"
        phase = encoded({"observationFinishedAt": PHASE_CLOSED})
        (root / "phase-result.json").write_bytes(phase)
        self.contract = {"referenceReplayEngineSha256": "1" * 64, "benchSha256": "2" * 64,
                         "tasks": {TASK: {"timeoutMs": 2000, "casesSha256": "3" * 64,
                                           "caseIndices": [0, 1, 2], "entryAndTestCaseIndices": [0, 2]}}}
        self.digest = {group: sha(self.code(group).encode()) for group in GROUPS}
        self.skip_digest = sha(SKIPPED_CODE.encode())
        self.groups = {}
        for index, name in enumerate(GROUPS, 4):
            pinned = [{"taskId": TASK, "codeSha256": self.digest[name], "historicalSkipApplies": False}]
            if name == "second-family":
                pinned.append({"taskId": TASK, "codeSha256": self.skip_digest, "historicalSkipApplies": True})
            self.groups[name] = {"programs": pinned, "captureFilesSha256": {"trials.jsonl": str(index) * 64}}
        manifest = {"binding": {"phaseReceiptSha256": sha(phase),
                                "ruleContractSha256": sha(encoded(self.contract))}, "groups": self.groups}
        self.worklist = {"groups": list(GROUPS)}
        self.document = {"scope": "REPLAY_MANIFEST_ONLY", "manifest": manifest, "manifestSha256": sha(encoded(manifest)),
                         "schema": oracle.REPORT_SCHEMA, "ruleContract": self.contract,
                         "ruleContractSha256": sha(encoded(self.contract)),
                         "worklistSha256": sha(encoded(self.worklist)),
                         "retainedOracleAuditSha256": oracle.MODEL_PINS["oracle-audit.json"],
                         "historicalBcaAbsoluteTolerance": oracle.HISTORICAL_BCA_ABSOLUTE_TOLERANCE,
                         "historicalClusteredPRelativeTolerance": oracle.HISTORICAL_CLUSTERED_P_RELATIVE_TOLERANCE,
                         "formalRunsStartedByReport": 0, "candidateExecutionsByReport": 0}
        self.manifest_file.write_bytes(encoded(self.document))
        self.manifest_sha = sha(self.manifest_file.read_bytes())

        environment = {"schema": capture.ENVIRONMENT_SCHEMA, "runtime": "node", "runtimeVersion": "v0.0.0-fixture",
                       "platform": "darwin", "architecture": "x64", "osRelease": "fixture", "locale": "C", "timeZone": "UTC"}
        invocation = {"schema": capture.INVOCATION_SCHEMA, "sessionId": SESSION, "arguments": ["--fixture"],
                      "evidenceScope": "SYNTHETIC_FIXTURE",
                      "manifestFileSha256": self.manifest_sha,
                      "benchSha256": self.contract["benchSha256"],
                      "referenceReplayEngineSha256": self.contract["referenceReplayEngineSha256"]}
        assets = {"evaluator.bin": b"inert evaluator identity fixture\n", "node.bin": b"inert runtime identity fixture\n",
                  "environment-before.json": encoded(environment), "environment-after.json": encoded(environment),
                  "version-before.txt": b"v0.0.0-fixture\n", "version-after.txt": b"v0.0.0-fixture\n",
                  "invocation.json": encoded(invocation)}
        for name, raw in assets.items():
            (self.directory / name).write_bytes(raw)
        identity = {name: sha(raw) for name, raw in assets.items()}
        self.events = self.directory / capture.EVENTS_FILE
        with self.events.open("wb") as stream:
            writer = capture.CaseEventWriter(
                stream, SESSION, "SYNTHETIC_FIXTURE", self.manifest_sha,
                capture.capture_identity(identity, "before"), START,
            )
            for name in GROUPS:
                for variant in evidence.VARIANTS:
                    writer.start_variant(name, TASK, self.digest[name], variant, 2000)
                    if variant == "asRun":
                        writer.finish_variant("NO_CALLABLE")
                    elif variant == "entry":
                        writer.case_result(0, capture.case_binding(self.contract, TASK, 0), "PASS", 100000)
                        writer.case_result(1, capture.case_binding(self.contract, TASK, 1), "TIMEOUT", 2000000000)
                        writer.finish_variant("CASE_RESULTS")
                    else:
                        writer.case_result(0, capture.case_binding(self.contract, TASK, 0), "PASS", 100000)
                        writer.case_result(2, capture.case_binding(self.contract, TASK, 2), "PASS", 110000)
                        writer.finish_variant("CASE_RESULTS")
            writer.skip_program("second-family", TASK, self.skip_digest)
            writer.finish(FINISH, capture.capture_identity(identity, "after"))
        self.review()

    @staticmethod
    def code(group):
        return f"inert authored fixture identity for {group}"

    def review(self, reviewed_at=REVIEW, scope="SYNTHETIC_FIXTURE"):
        self.review_body = {
            "schema": capture.REVIEW_SCHEMA, "evidenceScope": scope,
            "binding": self.document["manifest"]["binding"], "manifestFileSha256": self.manifest_sha,
            "fileSha256": {name: sha((self.directory / name).read_bytes()) for name in capture.CAPTURE_FILES},
            "attestation": {"operatorId": "synthetic-operator", "reviewedAtUtc": reviewed_at,
                            "decision": "ACCEPTED_CAPTURER_AND_EVIDENCE"},
        }
        self.operator.write_bytes(encoded(self.review_body))

    def args(self, **overrides):
        return Namespace(**dict({
            "evidence_mode": "synthetic", "action": "capture",
            "replay_manifest": self.manifest_file, "replay_manifest_sha256": self.manifest_sha,
            "capture_directory": self.directory, "operator_review": self.operator,
            "operator_review_sha256": sha(self.operator.read_bytes()), "observations": None,
            "observations_sha256": None, "evaluator_receipt": None, "evaluator_receipt_sha256": None,
        }, **overrides))

    def validate(self, phase_closed_at=PHASE_CLOSED, **overrides):
        return oracle.reviewed_replay(self.args(**overrides), self.document, phase_closed_at)

    def skill_groups(self):
        groups = {}
        for name in GROUPS:
            skills = {"candidate": Skill(("sv1-ef1", 0, TASK, "pass", self.code(name)), 1, 0, False)}
            if name == "second-family":
                skills["skip"] = Skill(("sv0-ef0", 0, TASK, None, SKIPPED_CODE), 1, 1, True)
            groups[name] = skills, oracle.program_population(skills)
        return groups

    def replace_event(self, ordinal, **fields):
        lines = [evidence.decode_evidence(line) for line in self.events.read_bytes().splitlines()]
        lines[ordinal].update(fields)
        self.write_events(lines)

    def write_events(self, lines):
        payload = (encoded(dict(line, sequence=index)).replace(b"\n", b"") + b"\n"
                   for index, line in enumerate(lines))
        self.events.write_bytes(b"".join(payload))
        self.review()


class DepartmentOracleCaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = REPO / ".runtime"
        temporary.mkdir(exist_ok=True)
        workspace = TemporaryDirectory(prefix="p2-r-case-capture-test-", dir=temporary)
        self.addCleanup(workspace.cleanup)
        self.fixture = CaptureFixture(Path(workspace.name).resolve())

    def test_emits_verifies_and_scores_original_case_indices_across_three_groups(self):
        fixture = self.fixture
        transcript, packet = fixture.validate()
        self.assertEqual("SYNTHETIC_FIXTURE", packet["evidenceScope"])
        self.assertEqual("v0.0.0-fixture", packet["provenance"]["runtimeVersion"])
        self.assertEqual(SESSION, packet["provenance"]["sessionId"])
        self.assertEqual(PHASE_CLOSED, packet["provenance"]["acceptedRegenerationClosedAtUtc"])
        self.assertEqual(sha(fixture.operator.read_bytes()), packet["provenance"]["reviewedOperatorAttestationSha256"])
        self.assertEqual(sha(fixture.events.read_bytes()), transcript["captureProvenance"]["caseEventFileSha256"])
        self.assertEqual({"outcome": "TIMEOUT", "timedOutCaseIndex": 1, "failedCaseIndices": []},
                         transcript["groups"]["second-family"]["programs"][0]["entry"])
        self.assertEqual([0, 2], [row["caseIndex"] for row in packet["observations"]["groups"]["second-family"]
                                 ["programs"][0]["entryAndTest"]["cases"]])
        score = oracle.interpret_transcript(transcript, fixture.document["manifest"], fixture.skill_groups(),
                                            fixture.contract)
        for name in GROUPS:
            self.assertEqual(1, score[name]["labels"]["asRun"]["diagnostics"]["confusion"]["fp"])
            self.assertEqual(1, score[name]["labels"]["entryAndTest"]["diagnostics"]["confusion"]["tp"])
        self.assertEqual(1, score["second-family"]["historicalSkips"])

    def test_cli_capture_produce_and_score_use_the_same_review_and_evidence(self):
        fixture = self.fixture
        parsed = fixture.args()
        common = ["--regeneration-bundle", str(fixture.root),
                  "--phase-receipt-sha256", fixture.document["manifest"]["binding"]["phaseReceiptSha256"],
                  "--replay-manifest", str(fixture.manifest_file), "--replay-manifest-sha256", fixture.manifest_sha,
                  "--capture-directory", str(fixture.directory), "--operator-review", str(fixture.operator),
                  "--operator-review-sha256", parsed.operator_review_sha256, "--evidence-mode", "synthetic"]
        groups = fixture.skill_groups()

        def run(action, output, *additional):
            argv = [str(oracle.__file__), action, *common, *additional, "--out", str(output)]
            stream = BytesIO()
            phase = patch.multiple(oracle, prepare=lambda: fixture.worklist, rule_contract=lambda: fixture.contract,
                                   accepted_population=lambda *_: (fixture.document["manifest"], groups),
                                   archive_readback=lambda *_: {})
            with phase, patch.object(sys, "argv", argv), patch.object(sys, "stdout", Namespace(buffer=stream)):
                self.assertEqual(0, oracle.main())
            self.assertEqual(stream.getvalue(), output.read_bytes())
            return evidence.decode_evidence(stream.getvalue())

        packet = run("capture", fixture.root / "verified-capture.json")
        transcript_path = fixture.root / "replay-transcript.json"
        transcript = run("produce", transcript_path)
        scored = run("score", fixture.root / "score-report.json", "--replay-transcript", str(transcript_path),
                     "--replay-transcript-sha256", sha(transcript_path.read_bytes()))
        self.assertEqual(packet["provenance"], transcript["captureProvenance"])
        self.assertEqual(packet["provenance"], scored["captureProvenance"])
        self.assertEqual("SYNTHETIC_REPLAY_TRANSCRIPT_SCORED", scored["scope"])
        self.assertEqual(0, scored["formalRunsStartedByReport"])
        self.assertEqual(0, scored["candidateExecutionsByReport"])

    def test_rejects_changed_artifact_runtime_invocation_and_events_against_independent_review(self):
        fixture = self.fixture
        for name in ("evaluator.bin", "node.bin", "invocation.json", capture.EVENTS_FILE):
            with self.subTest(name=name):
                path = fixture.directory / name
                original = path.read_bytes()
                path.write_bytes(original + b"changed evidence")
                try:
                    with self.assertRaisesRegex(ValueError, "capture files differ from the independent operator review"):
                        fixture.validate()
                finally:
                    path.write_bytes(original)

    def test_rejects_operator_scope_digest_and_incomplete_review_inputs(self):
        with self.assertRaisesRegex(ValueError, "scope, phase or manifest differs"):
            self.fixture.validate(evidence_mode="external")
        with self.assertRaisesRegex(ValueError, "file identity differs"):
            self.fixture.validate(operator_review_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "complete operator-reviewed capture inputs"):
            self.fixture.validate(operator_review=None)

    def test_rejects_reapproved_version_or_environment_drift(self):
        fixture = self.fixture
        version = fixture.directory / "version-after.txt"
        original = version.read_bytes()
        version.write_bytes(b"v0.0.1-fixture\n")
        fixture.review()
        with self.assertRaisesRegex(ValueError, "runtime version changed"):
            fixture.validate()
        version.write_bytes(original)
        after = fixture.directory / "environment-after.json"
        environment = evidence.decode_evidence(after.read_bytes())
        after.write_bytes(encoded(dict(environment, timeZone="Asia/Seoul")))
        fixture.review()
        with self.assertRaisesRegex(ValueError, "runtime environment changed"):
            fixture.validate()

    def test_rejects_reapproved_environment_fields_outside_allowlist(self):
        fixture = self.fixture
        for side in ("before", "after"):
            path = fixture.directory / f"environment-{side}.json"
            value = evidence.decode_evidence(path.read_bytes())
            path.write_bytes(encoded(dict(value, unlistedVariable="synthetic-only")))
        fixture.review()
        with self.assertRaisesRegex(ValueError, "runtime environment: missing or unexpected"):
            fixture.validate()

    def test_rejects_reapproved_case_index_identity_changes(self):
        self.fixture.replace_event(4, caseBindingSha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "does not bind the original bench case"):
            self.fixture.validate()

    def test_rejects_truncated_capture_and_session_changes_without_inferred_timeouts(self):
        fixture = self.fixture
        original = fixture.events.read_bytes()
        fixture.events.write_bytes(b"\n".join(original.splitlines()[:-1]) + b"\n")
        fixture.review()
        with self.assertRaisesRegex(ValueError, "case capture boundary"):
            fixture.validate()
        fixture.events.write_bytes(original)
        fixture.replace_event(4, sessionId=sha(b"different fixture session"))
        with self.assertRaisesRegex(ValueError, "sequence or session differs"):
            fixture.validate()

    def test_rejects_operator_attestation_before_capture_closure(self):
        self.fixture.review(reviewed_at=START)
        with self.assertRaisesRegex(ValueError, "operator review precedes the end"):
            self.fixture.validate()

    def test_rejects_relabelled_synthetic_invocation_and_capture_boundaries(self):
        fixture = self.fixture
        external = "OPERATOR_REVIEWED_EXTERNAL_REPLAY"
        fixture.review(scope=external)
        with self.assertRaisesRegex(ValueError, "evaluator invocation scope differs"):
            fixture.validate(evidence_mode="external")
        invocation = fixture.directory / "invocation.json"
        value = evidence.decode_evidence(invocation.read_bytes())
        invocation.write_bytes(encoded(dict(value, evidenceScope=external)))
        fixture.review(scope=external)
        with self.assertRaisesRegex(ValueError, "capture boundary scope differs"):
            fixture.validate(evidence_mode="external")

    def test_rejects_capture_before_accepted_regeneration_closure(self):
        with self.assertRaisesRegex(ValueError, "capture begins before regeneration closure"):
            self.fixture.validate(phase_closed_at=FINISH)

    def test_direct_capture_api_rejects_incomplete_prefix_in_a_closed_reviewed_session(self):
        fixture = self.fixture
        lines = [evidence.decode_evidence(line) for line in fixture.events.read_bytes().splitlines()]
        self.assertEqual("TIMEOUT", lines[5]["result"])
        fixture.write_events([event for i, event in enumerate(lines) if i != 5])
        with self.assertRaisesRegex(ValueError, "stopped before all retained cases without a timeout"):
            capture.read_capture(fixture.directory, fixture.operator.read_bytes(), fixture.document,
                                 fixture.manifest_file.read_bytes(), "SYNTHETIC_FIXTURE")


if __name__ == "__main__":
    unittest.main()
