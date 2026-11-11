#!/usr/bin/env python3
"""Reconstruct Chapter 7 finite development outcomes from complete raw records. No model, database or Godot required."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

IDS = ['H', 'I1', 'I2', 'I3', 'I4', 'I5', 'I6', 'I7', 'I8', 'S1']
PROMOTED = {'H', 'I3', 'I7', 'S1'}
REUSED = {'H', 'I3', 'S1'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def manifest(root):
    value = load(root / 'manifest.json')
    paths = set()
    for row in value['files']:
        rel = row['path']
        require(rel not in paths and not Path(rel).is_absolute() and '..' not in Path(rel).parts, 'unsafe/duplicate manifest path')
        paths.add(rel)
        f = root / rel
        require(f.is_file() and not f.is_symlink(), 'missing manifest file: ' + rel)
        data = f.read_bytes()
        require(len(data) == row['bytes'] and sha(data) == row['sha256'], 'manifest bytes/hash: ' + rel)
    return value


def verify(root, repo):
    listing = manifest(root)
    for item in load(root/'logical-files.json'):
        raw=gzip.decompress((root/item['path']).read_bytes())
        require(len(raw)==item['uncompressedBytes'] and sha(raw)==item['uncompressedSha256'],'lossless archive differs from original logical bytes')
    selection = load(root / 'selection.json')
    for rel, expected in selection['sources'].items():
        require(sha((repo / rel).read_bytes()) == expected, 'historical source changed: ' + rel)
    source = repo / 'experiments/rq-c/redo/rq-c-s42-ollama-t30-r5/candidates.jsonl'
    trials = source.with_name('trials.jsonl')
    cs = [json.loads(l) for l in source.read_text().splitlines()]
    ts = [json.loads(l) for l in trials.read_text().splitlines()]
    for name, expected_ok in [('usable', True), ('unusable', False)]:
        row = selection[name]
        require(row['candidate'] == cs[row['line']-1] and row['trial'] == ts[row['line']-1], 'historical selected row mismatch')
        require(row['trial']['selfVerdict'] == 'pass' and row['trial']['execOk'] is expected_ok, 'historical pass/execution mismatch')
        require(sha(row['code'].encode()) == row['codeSha256'], 'selected code hash mismatch')
    require(selection['unusable']['code'] == load(repo/'experiments/rq-c/oracle-audit.json')['example']['code'], 'wrong candidate changed from unchanged behavior-failure example')
    summaries = []
    for attempt in ['development-01', 'development-02']:
        directory = root / 'attempts' / attempt
        receipt = load(directory/'receipt.json')
        identity = load(directory/'input-identities.json')
        rows = load(directory/'cases.json')
        require([r['caseId'] for r in rows] == IDS, 'incomplete/changed development cases')
        require(receipt['completedCases'] == 10 and receipt['heldOutCases'] == 0 and receipt['conditionsMeasured'] == ['C2'], 'invalid study denominator/condition')
        require(receipt['codeCommit'] == identity['codeCommit'] and receipt['modelRequests'] == 0 and receipt['formalHardwareQualification'] is False, 'identity/scope mismatch')
        require(receipt['wallSeconds'] <= 1200, 'wall limit exceeded')
        telemetry = [json.loads(l) for l in gzip.decompress((directory/'telemetry.jsonl.gz').read_bytes()).decode().splitlines()]
        require(bool(telemetry), 'missing resource telemetry')
        require(max(t['rssBytes'] for t in telemetry) <= receipt['peak']['rssBytes'], 'RSS receipt under-reports raw samples')
        require(max(t['swapIncreaseBytes'] for t in telemetry) <= receipt['peak']['swapIncreaseBytes'], 'swap receipt under-reports samples')
        require(min(t['availableBytes'] for t in telemetry) >= receipt['peak']['minAvailableBytes'], 'available-memory receipt inconsistency')
        timers = {}
        for t in telemetry:
            for key, crossed in [('rss',t['rssBytes']>2*1024**3),('available',t['availableBytes']<3*1024**3),('swap',t['swapIncreaseBytes']>1024**3)]:
                if not crossed:timers.pop(key,None)
                else:
                    timers.setdefault(key,t['elapsedSeconds'])
                    require(t['elapsedSeconds']-timers[key]<30,'unreported sustained resource stop')
        raw = gzip.decompress((directory/'client/aijade-render-state.jsonl.gz').read_bytes())
        lines = raw.splitlines(keepends=True)
        header = json.loads(lines[0]); end = json.loads(lines[-1])
        require(end['complete'] is True and end['lines']==len(lines)-1 and end['sha256']==sha(b''.join(lines[:-1])), 'invalid renderer seal')
        require(header['schema']=='mosaic-render-state-log-v2' and header['presented_frame_observed'] is False, 'incorrect renderer stage/display scope')
        require(header['pmx_sha256']==identity['modelSha256'],'renderer asset hash differs from fixed input')
        for key,name in [('initial_clip_sha256','companion-rest.vmd'),('behavior_plan_sha256','companion-plan.json')]:
            require(header[key]==sha((repo/'experiments/p1/external-renderer/preset'/name).read_bytes()),'renderer clip/behavior input differs from fixed public preset')
        registry=[json.loads(l) for l in gzip.decompress((directory/'registry.jsonl.gz').read_bytes()).decode().splitlines()]
        require(registry[0]['session_id']==header['session_id'] and registry[0]['renderer_context_id']==header['renderer_context_id'],'registered session identity differs from renderer')
        require([r['intent_id'] for r in registry[1:]]==[r['prepared']['intentId'] for r in rows],'registration/case sequence mismatch')
        client_rows = [json.loads(l) for l in lines[1:-1]]
        pre = {f"{header['renderer_context_id']}:{r['seq']}":r for r in client_rows if r.get('packet_type')=='RenderStatePacket'}
        require(load(directory/'manifest.json')['file_sha256']==sha(raw), 'sealed file differs from manifest')
        for r in rows:
            case = r['caseId']; final=r['final']; evidence=r['evidence']; prepared=r['prepared']; selected=r['selectedReceipt']
            require(r['batch']=='development_qualification_only' and r['condition']=='C2' and r['gatewayAttempts']==0, 'invalid condition or provider attempt')
            require(prepared['codeSha256']==sha(prepared['code'].encode())==evidence['codeSha256'], 'executed code binding')
            expected_selection=selection['unusable' if case=='I5' else 'usable']
            require(prepared['code']==expected_selection['code'] and prepared['taskId']==expected_selection['taskId'], 'candidate selection drift')
            execution=prepared['execution']
            require((execution is None) if case=='I4' else execution['ok'] is (case!='I5'), 'execution result differs from declared case')
            require(r['initialWrite']['status']==201 and r['initialRead']['status']==200 and len(r['initialRead']['response']['items'])==1, 'initial actual memory path absent')
            posts=r['importPosts']
            require(len(posts)==20 and all(p['status']==201 for p in posts), 'receipt import did not exercise all request/receipt HTTP writes')
            record=pre[selected['renderRef']]
            traces={c['trace_id'] for c in record.get('consumed',[]) if c.get('trace_id')}
            require(selected['intentId'] in traces and selected['assetVersionHash']==header['pmx_sha256'], 'receipt not supported by actual renderer file')
            require(any(p['request']==selected['request'] for p in posts) and any(p['request']==selected['receipt'] for p in posts), 'selected receipt was not imported')
            require((evidence['intentId']!=selected['intentId']) if case=='I1' else evidence['intentId']==selected['intentId'], 'cross-intent intervention drift')
            promoted=case in PROMOTED; reused=case in REUSED
            expected_state='absent' if case=='I8' else 'revoked' if case=='I7' else 'verified' if promoted else 'failed' if case=='I5' else 'unknown'
            require(final['specs']==int(promoted) and final['reports']==int(promoted), 'partial or wrong promotion count')
            if attempt=='development-02':
                require(len(final['specRows'])==final['specs'] and len(final['reportRows'])==final['reports'], 'persisted promotion JSON absent')
            authority=final['authority']
            require((not authority) if case=='I8' else len(authority)==1 and authority[0]['state']==expected_state, 'authority state')
            require(r['round2']['executed'] is reused and final['reuseCount']==int(reused), 'impossible or missing positive reuse')
            require(final['outboxCount']==(0 if case=='I8' else 1) and final['outcomeMemoryCount']==(0 if case=='I8' else 1), 'outbox/actual memory count')
            if case!='I8':
                outcome=r['commit']['outcome']
                require(outcome['promoted'] is promoted and outcome['codeSha256']==evidence['codeSha256'], 'committed outcome binding')
                require(r['delivery']['httpStatus']==201 and r['round2']['retrieved'] is True, 'outcome did not traverse actual perception/retrieval')
            if promoted:
                job=r['commit']['job']; proposal=r['proposal']
                require(job['proposalId']==proposal['proposalId'] and job['inputHash']==proposal['inputHash'], 'adapter promotion-job identity')
                require(job['evaluationPack']['unitContractPropertyTests']['passed'] is True, 'promotion missing execution pack')
                if attempt=='development-02':
                    require(final['specRows'][0]['spec']['proposal']==proposal and final['reportRows'][0]['result']['promoted'] is True, 'persisted gate/spec/report mismatch')
            if case=='I1': require(r['commit']['outcome']['reason']=='execution_intent_mismatch','I1 refusal cause')
            if case=='I2':
                require(r['admission']['status']==400 and r['admission']['response']['error']=='INVALID_RENDER_TRACE_REFERENCE','I2 HTTP refusal')
                if attempt=='development-02':
                    require(r['admission']['diagnosticDirectAppendAttempts']==1 and r['admission']['diagnosticCoreReason']=='asset_version_hash_mismatch' and r['admission']['diagnosticEventCount']==0,'I2 diagnostic or zero-write evidence')
            if case=='I3': require(r['duplicateCommit']['duplicate'] is True and r['duplicateDelivery']['duplicate'] is True and r['duplicateReuse']['executed'] is False and authority[0]['revision']==1,'I3 duplicate write/reuse')
            if case=='I4': require(r['commit']['outcome']['reason']=='execution_unknown','I4 refusal cause')
            if case=='I5': require(r['commit']['outcome']['reason']=='execution_failed' and bool(execution['failures']),'I5 execution failure absent')
            if case=='I6': require(r['commit']['outcome']['reason']=='receipt_stage_insufficient','I6 stage escalation')
            if case=='I7': require(r['round2']['memoryOutcome']['state']=='verified' and authority[0]['state']=='revoked' and r['round2']['reason']=='authority_revoked','I7 old positive restored revocation')
            if case=='I8': require(r['databaseErrorCode']=='P0001' and not final['outcomes'] and r['delivery']['status']=='absent','I8 incomplete rollback')
            if case=='S1': require(r['semanticMismatchConstructed'] is True and prepared['requestedAct']!=prepared['dispatchedAct'] and promoted and reused,'semantic counterexample was hidden or misclassified')
        failed=[r['caseId'] for r in rows if not r['qualified']]
        if attempt=='development-01':
            require(receipt['status']=='STOPPED' and failed==['I2'],'first failed observer attempt not retained')
        else:
            require(receipt['status']=='PASS_DEVELOPMENT_QUALIFICATION_ONLY' and not failed,'qualification not complete')
        summaries.append(dict(attempt=attempt,rows=len(rows),qualificationFlags=10-len(failed),promotions=sum(r['final']['specs'] for r in rows),
                              round2Executions=sum(r['round2']['executed'] for r in rows),semanticCounterexamplesAdmitted=1))
    return dict(status='PASS',manifestFiles=len(listing['files']),attempts=summaries,primaryAttempt='development-02',
                acceptedDevelopmentCases=10,heldOutCases=0,C1Comparisons=0,modelRequests=0,formalHardwareQualification=False,
                interpretation='Finite constructed development qualification; AI-assisted, no independent human review or population inference.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--repo',type=Path)
    args=parser.parse_args()
    repo=args.repo or next(p for p in args.root.resolve().parents if (p/'src/Aijade.Research').is_dir())
    try: print(json.dumps(verify(args.root.resolve(),repo.resolve()),ensure_ascii=False,indent=2))
    except (OSError,ValueError,KeyError,AssertionError,ET.ParseError) as error:
        print(type(error).__name__+': '+str(error),file=sys.stderr);raise SystemExit(1)
