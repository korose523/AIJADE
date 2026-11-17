"""Narrow archive/computed error binding; no raw predicate replay."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import audit
import refusal_negative_controls as controls


def main(root, computed_path, output):
    audit.need(not output.exists(), 'RUNTIME_BINDING_OUTPUT_MUST_BE_NEW')
    output.mkdir(parents=True)
    before = controls.fingerprint(root)
    computed = json.loads(computed_path.read_text())['terminalReplay']['independentReplay']
    original = audit.data(root, 'audit/independent-lifecycle-refusal-audit.json')
    audit.runtime_refusal_check(original, computed)
    results = [dict(name='actual_original_vs_actual_full03_computed', passed=True,
        actualErrorEqualsComputed=True, actualSourceShaEqualsComputed=True)]
    for name, field in [('coherent_same_phrase_error_changed', 'error'),
                        ('coherent_runtime_source_sha_changed', 'sourceSha256')]:
        copy_root = output / name
        shutil.copytree(root, copy_root, copy_function=controls.copy_file)
        audit.manifest_check(copy_root)
        audit.runtime_refusal_check(audit.data(copy_root, 'audit/independent-lifecycle-refusal-audit.json'), computed)
        def change(value):
            runtime = value['frozenRuntimeAuditor']
            if field == 'error':
                runtime[field] += ' [coherent archive alteration]'
            else:
                runtime[field] = '0' * 64
        controls.alter(copy_root, 'audit/independent-lifecycle-refusal-audit.json', change)
        controls.rebind_manifest(copy_root)
        audit.manifest_check(copy_root)
        changed = audit.data(copy_root, 'audit/independent-lifecycle-refusal-audit.json')
        audit.need(controls.fingerprint(copy_root) != before, 'RUNTIME_BOUNDARY_NO_OP')
        try:
            audit.runtime_refusal_check(changed, computed)
            raise AssertionError('coherent runtime error/source alteration accepted')
        except audit.Refused as error:
            audit.need(str(error) == 'RUNTIME_REFUSAL_EXACT_ERROR_SOURCE_BINDING', 'WRONG_RUNTIME_BINDING_REJECTION')
            results.append(dict(name=name, baselineAccepted=True, mutationWasEffective=True,
                manifestCoherentlyRebound=True, passed=True, reason=str(error)))
    try:
        audit.need(before != controls.fingerprint(root), 'NO_OP_CONTROL_REFUSED:actual_unchanged_runtime_baseline')
        raise AssertionError('unchanged baseline passed no-op guard')
    except audit.Refused as error:
        audit.need(str(error).startswith('NO_OP_CONTROL_REFUSED:'), 'WRONG_RUNTIME_NO_OP_REJECTION')
        results.append(dict(name='actual_unchanged_baseline_no_op', passed=True, reason=str(error)))
    audit.need(controls.fingerprint(root) == before, 'ORIGINAL_PACKET_CHANGED')
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    report = dict(schema='aijade.ch7.lifecycle-terminal-runtime-binding.v1',
        status='NARROW_RUNTIME_ERROR_AND_SOURCE_BINDING_PASS', checkedAt=datetime.now(timezone.utc).isoformat(),
        rows=results, auditSourceSha256=sha(Path(audit.__file__)),
        actualArchivedAuditSha256=sha(root / 'audit/independent-lifecycle-refusal-audit.json'),
        actualComputedBaselineSha256=sha(computed_path), precedingFullControls=12,
        tracebackCompared=False, originalPacketUnchanged=True, fullRawReplayRepeated=False,
        newObservation=False, newWindow=False, notAdditionalFullCorruptionControls=True)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=here / 'packet')
    parser.add_argument('--computed', type=Path, default=here / 'archive-controls-03/baseline-01.json')
    parser.add_argument('--output', type=Path, default=here / 'runtime-binding-controls-05')
    args = parser.parse_args()
    main(args.root.resolve(), args.computed.resolve(), args.output.resolve())
