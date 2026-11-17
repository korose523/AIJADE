"""Add one actual copied-baseline control to fourteen retained controls; no live work."""
from pathlib import Path
from datetime import datetime,timezone
import json,shutil
import test_actual_e5_packet_controls as base
from packet_common import read,decode,encoded,new,sha,file_sha,need,typed_equal,verify_packet
B=Path('/Volumes/Untitled/AIJADE');C=B/'.research/runs/ch7-owned-state-20261118';T=C/'archive-tools'
PRIMARY=C/'audit/engineering-03-packet';FIXTURES=T/'packet-controls-15-fixtures'

def fake_last_outer_call(root):
    receipt_name='run/engineering-03/receipt.json'
    receipt=decode(base.body(root,receipt_name));stats=receipt['outerCursor']
    raw=[decode(v) for v in base.body(root,'run/engineering-03/settling/telemetry.jsonl').splitlines()]
    last=raw[-1]['processObservation']['lifecycle'];previous=raw[-2]['processObservation']['lifecycle']
    decisions=[decode(v) for v in base.body(root,'audit/retained/e5-full-cold-decisions-01.jsonl').splitlines()]
    decision=decisions[-1]['actualFullTypedDecision'];size=len(json.dumps(decision,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode())
    # This deliberately claims the outer cursor reached the final raw UNKNOWN,
    # contradicting its source-bound require-PASS-before-dispatch short circuit.
    for key in ('calls','privateStateValidations','guardEvaluations','detachedDecisionCopies'):stats[key]+=1
    stats['detachedDecisionCanonicalBytes']+=size
    stats['fullPrefixReadBytes']+=last['journalBytes'];stats['fullPrefixComparedBytes']+=previous['journalBytes']
    tail_bytes=last['journalBytes']-previous['journalBytes'];tail_events=last['lastSequence']-previous['lastSequence']
    stats['parsedBytes']+=tail_bytes;stats['parsedEvents']+=tail_events
    stats['hashUpdatedBytes']+=tail_bytes;stats['builtinTailEvents']+=tail_events
    stats['latestPrefixBytes']=last['journalBytes']
    stats['retainedEvents']=last['lastSequence'];stats['retainedLeases']=receipt['innerCursor']['retainedLeases']
    base.put_json(root,receipt_name,receipt)
    audit=decode(base.body(root,'audit/independent-audit.json'))
    audit['initializationAudit']['results']['outer']['finalStatistics']=stats
    audit['initializationAudit']['results']['outer']['actualCalls']+=1
    base.put_json(root,'audit/independent-audit.json',audit)
    base.coherent_numbers(root,'outerActualGuardEvaluations',174)
    base.coherent_numbers(root,'outerDetachedDecisionCanonicalBytes',stats['detachedDecisionCanonicalBytes'])
    base.coherence(root)

def main():
    prior=read(T/'packet-controls-01.json')
    need(prior['status']=='FOURTEEN_ADVERSARIAL_POST_TERMINAL_CONTROLS_PASS' and prior['passed']==14,'actual prior fourteen controls required')
    need(not FIXTURES.exists(),'never overwrite additional copied control history')
    original=base.table(PRIMARY);baseline=verify_packet(PRIMARY)
    need(prior['actualPrimaryManifestSha256']==baseline['manifestSha256'],'prior/current primary differ')
    FIXTURES.mkdir();copy=FIXTURES/'15-coherent-fictitious-final-outer-call';shutil.copytree(PRIMARY,copy)
    base.FIXTURES=FIXTURES
    verify_packet(copy);before=base.table(copy);fake_last_outer_call(copy)
    need(not typed_equal(before,base.table(copy)),'fictitious call control is no-op')
    predicate='retained E5 actual per-owner prefix/read/compare/tail/eval/canonical counter population differs'
    try:
        verify_packet(copy);raise AssertionError('fictitious final outer evaluation accepted')
    except ValueError as error:
        need(predicate in str(error),'wrong additional adverse predicate: '+str(error))
        final=dict(control='coherent-fictitious-final-outer-call',baselineAccepted=True,mutationNonNoOp=True,
            expectedPredicate=predicate,actualError=str(error),status='REJECTED_EXPECTED_PREDICATE',fixture=str(copy),
            mutatedManifestSha256=file_sha(copy/'packet-manifest.json'),controlSourceSha256=file_sha(Path(__file__)))
    need(base.table(PRIMARY)==original,'primary immutable packet changed')
    controls=[dict(row,controlSourceSha256=prior['controlSourceSha256']) for row in prior['controls']]+[final]
    result=dict(schema='aijade.ch7.e5-post-terminal-packet-controls.v2',status='FIFTEEN_ADVERSARIAL_POST_TERMINAL_CONTROLS_PASS',
        checkedAt=datetime.now(timezone.utc).isoformat(),controls=controls,discovered=15,passed=15,failed=0,
        execution='Fourteen original controls completed in one actual process; one additional copied-baseline control completed separately, all on the identical immutable primary manifest.',
        originalFourteenReceiptSha256=file_sha(T/'packet-controls-01.json'),originalFourteenSourceSha256=file_sha(T/'test_actual_e5_packet_controls.py'),
        additionalControlSourceSha256=file_sha(Path(__file__)),actualPrimaryManifestSha256=baseline['manifestSha256'],
        commonSourceSha256=file_sha(T/'packet_common.py'),verifierSourceSha256=file_sha(T/'verify_e5_packet.py'),
        codecSourceSha256=file_sha(T/'lossless_members.py'),semanticsSourceSha256=file_sha(T/'e5_refusal_semantics.py'),
        originalPrimaryUnchanged=True,independentColdNegativeAuditUnmodified=True,backendQualified=False,independentHumanReview=False,
        scope='Post-terminal copied archive controls; no live measurement, original kernel cold replay or scientific acceptance.')
    out=T/'packet-controls-final-15.json';new(out,encoded(result));print(json.dumps(result,indent=2))
if __name__=='__main__':main()
