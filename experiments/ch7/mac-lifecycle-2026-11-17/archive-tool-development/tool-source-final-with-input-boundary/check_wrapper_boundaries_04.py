"""Narrow post-03 wrapper controls; no expensive raw replay is repeated."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil
import audit
import refusal_negative_controls as controls

HERE = Path(__file__).resolve().parent
ROOT = HERE / 'packet'
OUT = HERE / 'wrapper-boundary-controls-04'
audit.need(not OUT.exists(), 'BOUNDARY_OUTPUT_MUST_BE_NEW')
OUT.mkdir()
before = controls.fingerprint(ROOT)
receipt = audit.data(ROOT, 'qualification/receipt.json')
baseline = audit.inputs_check(ROOT, receipt)
copy_root = OUT / 'coherent-fourth-seed'
shutil.copytree(ROOT, copy_root, copy_function=controls.copy_file)
audit.manifest_check(copy_root)
audit.inputs_check(copy_root, audit.data(copy_root, 'qualification/receipt.json'))
controls.safe_write(copy_root / 'inputs' / 'construction-seed.json', b'{"controlledSeed":17}\n')
controls.rebind_manifest(copy_root)
audit.manifest_check(copy_root)
try:
    audit.inputs_check(copy_root, audit.data(copy_root, 'qualification/receipt.json'))
    raise AssertionError('fourth coherent seed file was accepted')
except audit.Refused as error:
    audit.need(str(error) == 'KNOWN_INPUT_CLOSED_POPULATION', 'WRONG_FOURTH_INPUT_REJECTION')
    fourth = str(error)
try:
    audit.need(before != controls.fingerprint(ROOT), 'NO_OP_CONTROL_REFUSED:unchanged_actual_baseline')
    raise AssertionError('no-op passed the mutation effectiveness guard')
except audit.Refused as error:
    audit.need(str(error).startswith('NO_OP_CONTROL_REFUSED:'), 'WRONG_NO_OP_REJECTION')
    noop = str(error)
audit.need(controls.fingerprint(ROOT) == before, 'ORIGINAL_PACKET_CHANGED')
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
result = dict(schema='aijade.ch7.lifecycle-terminal-wrapper-boundaries.v1',
    status='NARROW_INPUT_POPULATION_AND_NO_OP_BOUNDARIES_PASS',
    checkedAt=datetime.now(timezone.utc).isoformat(),
    auditSourceSha256=sha(HERE / 'audit.py'),
    rawReplayAdapterSha256=sha(HERE / 'terminal_replay.py'),
    precedingFullControls=12, precedingSourceCapture=str(HERE / 'tool-source-before-controls-03'),
    rows=[dict(name='exact_original_three_inputs', passed=True, derived=baseline),
          dict(name='coherently_rebound_fourth_seed', passed=True, reason=fourth),
          dict(name='unchanged_actual_baseline_no_op', passed=True, reason=noop)],
    fullRawReplayRepeated=False, originalPacketUnchanged=True,
    changes='Only inputs_check wrapper gained exact physical/logical population. Frozen raw predicate is unchanged.',
    notThirteenFullControls=True, newObservation=False, newWindow=False)
(OUT / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
