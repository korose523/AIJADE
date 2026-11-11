#!/usr/bin/env python3
"""Reconstruct paired inputs, actual chronology, transactions and fixed-window scores."""
import argparse
import copy
import json
from pathlib import Path

from audit_retrieval_led import load, raw, lines, sha, timestamp
from audit_retrieval_suffix import require, applied_hashes, verify_suffix
from score_paired_development import CONTRACT_SHA256, LAYOUT_SHA256, IDS, score_directory


def verify(root, repo):
    receipt=load(root,'receipt.json'); identity=load(root,'input-identities.json')
    layout=load(root,'layout.json'); selection=load(root,'selection.json'); rows=load(root,'cases.json')
    require(receipt['status']=='PASS_PAIRED_KNOWN_DEVELOPMENT_ONLY' and receipt['completedCases']==20 and receipt['plannedPairs']==10,'incomplete paired batch')
    require(receipt['heldOutCases']==0 and receipt['conditionsMeasured']==['C1','C2'] and receipt['modelRequests']==0 and receipt['formalHardwareQualification'] is False,'scope changed')
    require(receipt['codeCommit']==identity['codeCommit'],'source identity')
    require(sha(raw(root,'scoring-contract.json'))==identity['scoringContractSha256']==CONTRACT_SHA256,'scoring contract identity')
    require(sha(raw(root,'layout.json'))==identity['layoutSha256']==LAYOUT_SHA256,'layout identity')
    for rel, expected in selection['sources'].items():
        require(sha((repo/rel).read_bytes())==expected,'historical source changed: '+rel)
    order=[(p['caseId'],c) for p in layout['cases'] for c in p['conditions']]
    require([(r['caseId'],r['condition']) for r in rows]==order and len(order)==20,'missing/reordered arm or case')
    require(sum(p['conditions'][0]=='C1' for p in layout['cases'])==5,'unbalanced first-arm order')
    journal=lines(root,'journal.jsonl')
    require([j['sequence'] for j in journal]==list(range(1,len(journal)+1)),'journal sequence')
    require(all(b['monotonicTicks']>a['monotonicTicks'] and timestamp(b['utc'])>=timestamp(a['utc']) for a,b in zip(journal,journal[1:])),'journal time reversal')
    require(len({j['frequency'] for j in journal})==1,'clock scale changed')

    def phase(key,name):
        found=[j for j in journal if j['caseId']==key and j['phase']==name]
        require(len(found)==1,'missing/duplicate phase '+key+':'+name)
        return found[0]

    prefix_done=phase('batch','prefixes.complete');ready=phase('batch','renderer.ready');closed=phase('batch','renderer.closed')
    require(prefix_done['sequence']<ready['sequence']<closed['sequence'],'batch phase order')
    require(timestamp(receipt['phases']['renderer']['startedAt'])>timestamp(prefix_done['utc']),'renderer started before all actual prefixes')
    require(timestamp(receipt['phases']['renderer']['endedAt'])<=timestamp(closed['utc']),'suffix before renderer exit')
    prepared=load(root,'prepared.json')
    require([(p['caseId'],p['condition']) for p in prepared]==order,'prefix handoff order')
    require(sha(raw(root,'prepared.json'))==load(root,'renderer-request.json')['preparedSha256'],'prefix handoff hash')
    state=raw(root,'client/aijade-render-state.jsonl'); state_lines=state.splitlines(keepends=True)
    header=json.loads(state_lines[0]);end=json.loads(state_lines[-1])
    require(end['complete'] is True and end['lines']==len(state_lines)-1 and end['sha256']==sha(b''.join(state_lines[:-1])),'renderer seal')
    require(header['presented_frame_observed'] is False and header['pmx_sha256']==identity['modelSha256'],'renderer scope/asset')
    require(sha(state)==load(root,'renderer-closed.json')['stateSha256']==load(root,'manifest.json')['file_sha256'],'closed-file hash')
    for key,name in [('initial_clip_sha256','companion-rest.vmd'),('behavior_plan_sha256','companion-plan.json')]:
        require(header[key]==sha((repo/'experiments/p1/external-renderer/preset'/name).read_bytes()),'fixed renderer preset changed')
    registry=lines(root,'registry.jsonl')
    require(registry[0]['session_id']==header['session_id'] and registry[0]['renderer_context_id']==header['renderer_context_id'],'registered session/context')
    require(len(registry)==11 and [r['intent_id'] for r in registry[1:]]==[next(r['prepared']['intentId'] for r in rows if r['caseId']==p['caseId']) for p in layout['cases']],'ten shared registrations')
    pre={f"{header['renderer_context_id']}:{r['seq']}":r for r in map(json.loads,state_lines[1:-1]) if r.get('packet_type')=='RenderStatePacket'}
    databases=[]
    for row in rows:
        case=row['caseId'];condition=row['condition'];key=case+'/'+condition;p=row['prepared'];final=row['final']
        require(row['batch']=='paired_known_development' and row['policyVersion']==('strong-local-v1' if condition=='C1' else 'cross-module-v1'),'declared policy/batch')
        require(row['gatewayAttempts']==0 and row['sharedRenderedIntent'] is True and 'qualified' not in row,'provider or misleading qualification flag')
        names=['database.open','memory.write.begin','memory.write.end','memory.read.begin','memory.read.end','route.selected','execution.begin','execution.end','intent.mapped',
               'shared_intent.sent','database.resumed','import.begin','import.end','admission.begin','admission.end','commit.begin','commit.end','delivery.begin','delivery.end','round2.begin','round2.end','case.complete','database.disposed']
        events=[phase(key,n) for n in names]
        require(all(b['sequence']>a['sequence'] for a,b in zip(events,events[1:])),'case/arm phase order')
        require(phase(key,'intent.mapped')['sequence']<phase(case,'pair.inputs_equal')['sequence']<prefix_done['sequence'],'prefix/parity order')
        require(ready['sequence']<phase(case,'intent.registered')['sequence']<phase(key,'shared_intent.sent')['sequence']<closed['sequence']<phase(key,'database.resumed')['sequence'],'shared dispatch and suffix order')
        require(row['databaseBefore']==row['databaseAfter']==p['databaseBefore']==phase(key,'database.open')['detail']==phase(key,'database.resumed')['detail'],'database continuity changed')
        databases.append(row['databaseBefore']['database'])
        require(len(row['databaseBefore']['token'])==32,'missing database state token')
        require(row['initialWrite']==phase(key,'memory.write.end')['detail'] and row['initialRead']==phase(key,'memory.read.end')['detail'],'raw memory journal binding')
        require(row['initialWrite']['status']==201 and row['initialRead']['status']==200 and len(row['initialRead']['response']['items'])==1,'actual route write/read absent')
        content=row['initialRead']['response']['items'][0]['content']
        require(content==row['initialWrite']['request']['content'] and content.startswith('ch7_route_'+case+' '),'route not from returned content')
        cue=json.loads(content.split(' ',1)[1]); route=p['route']
        require(set(cue)=={'caseId','taskId','codeSha256','requestedAct'},'extra labels/fields in route cue')
        require(cue['caseId']==case and cue['taskId']==p['taskId'] and cue['codeSha256']==p['codeSha256']==sha(p['code'].encode()),'route/code binding')
        require(route['memoryContentSha256']==sha(content.encode()) and route['program']['code']==p['code'] and route==phase(key,'route.selected')['detail'],'route selection record')
        selected=selection['unusable' if case=='I5' else 'usable']
        require(p['code']==selected['code'] and p['taskId']==selected['taskId'],'closed catalogue changed')
        execution=p['execution']
        require((execution is None) if case=='I4' else execution['ok'] is (case!='I5'),'declared execution control')
        require(execution==phase(key,'execution.end')['detail'],'actual execution journal')
        require(cue['requestedAct']==p['requestedAct']=='comfort' and p['mapperInputAct']==('celebrate' if case=='S1' else 'comfort'),'act or unrecorded semantic override')
        require(p['dispatchedAct']==('inform' if case in ['I4','I5'] else p['mapperInputAct']),'execution fallback')
        initial_source=next(v for v in prepared if v['caseId']==case and v['condition']==condition)
        require(initial_source==phase(key,'intent.mapped')['detail']=={k:v for k,v in p.items() if k not in ['registered','packets']},'prefix mutated after handoff')
        require(p==phase(key,'shared_intent.sent')['detail'] and row==phase(key,'case.complete')['detail'],'dispatch/final journal binding')
        require(len(p['packets'])==2 and all(v['trace_id']==p['intentId'] for v in p['packets']),'packet identity/count')
        posts=row['importPosts'];receipt_row=row['selectedReceipt'];actual=pre[receipt_row['renderRef']]
        require(len(posts)==20 and all(q['status']==201 for q in posts),'actual receipt import incomplete')
        require(receipt_row['intentId'] in {c['trace_id'] for c in actual['consumed']},'selected receipt not consumed')
        renderer_hash,server_hash=applied_hashes(actual)
        require(renderer_hash==actual['applied_params_hash'] and server_hash==receipt_row['appliedParamsHash'],'applied values/hash conventions')
        require(any(q['request']==receipt_row['request'] for q in posts) and any(q['request']==receipt_row['receipt'] for q in posts),'selected receipt not imported')
        require(receipt_row['assetVersionHash']==header['pmx_sha256'],'receipt asset mismatch')
        require(len(final['specRows'])==final['specs'] and len(final['reportRows'])==final['reports'],'persisted raw rows')
        for spec in final['specRows']:
            require(spec['spec']['proposal']==row['proposal'] and all(spec['spec']['gates'][g] is True for g in ['unitContractPropertyTests']),'actual persisted promotion proposal/gate')
        for report in final['reportRows']:require(report['result']['promoted'] is True,'persisted promotion report')
        for call in row['promotionAttempts']:
            require(call['transactionMode']==('service_owned' if condition=='C1' else 'caller_owned'),'transaction mode')
            require(call['job']['proposal']==row['proposal'] and call['job']['evaluationPack']['unitContractPropertyTests']['passed'] is True,'service received actual proposal/execution pack')
        if case=='I8':
            require(row['databaseErrorCode']=='P0001' and not final['authority'] and not final['outcomes'] and final['outboxCount']==0 and final['outcomeMemoryCount']==0,'controlled state failure rollback')
            require(len(row['promotionAttempts'])==1 and row['promotionAttempts'][0]['serviceResult']['ok'] is True,'transient promotion observation missing')
            require(final['specs']==final['reports']==(1 if condition=='C1' else 0),'durable/rolled-back promotion conflated')
        else:
            require(row['commit'] is not None and final['outboxCount']==final['outcomeMemoryCount']==1 and row['delivery']['httpStatus']==201,'outcome actual delivery absent')
        if case in ['I4','I5']:
            require(not row['promotionAttempts'] and final['specs']==0,'local execution check removed')
        if case=='I2':require(row['admission']['status']==400 and row['admission']['diagnosticCoreReason']=='asset_version_hash_mismatch' and row['admission']['diagnosticEventCount']==0 and not row['promotionAttempts'],'common admission removed')
        if case=='I3':require(row['duplicateCommit']['duplicate'] is True and row['duplicateDelivery']['duplicate'] is True and row['duplicateReuse']['executed'] is False and final['reuseCount']==1,'common deduplication removed')
        if case=='I7':require(row['round2']['memoryOutcome']['state']=='verified' and row['round2']['reason']=='authority_revoked' and row['round2']['executed'] is False,'common revocation removed')
    require(len(set(databases))==20,'case/arm isolation')
    for case in IDS:
        a,b=[next(r for r in rows if r['caseId']==case and r['condition']==c) for c in ['C1','C2']]
        require(a['initialWrite']['request']==b['initialWrite']['request'] and a['initialRead']==b['initialRead'],'unequal actual memory inputs')
        for name in ['evidence','proposal','selectedReceipt']:
            require(a[name]==b[name],'unequal available '+name)
        require([p['request'] for p in a['importPosts']]==[p['request'] for p in b['importPosts']],'unequal raw receipt inputs')
        require(a['admission']['request']==b['admission']['request'] and a['admission']['status']==b['admission']['status'],'unequal admission input/result')
        names=['code','codeSha256','taskId','benchSha256','route','requestedAct','mapperInputAct','dispatchedAct','mappedIntent','intentId','executionId','registered','packets']
        for name in names:require(a['prepared'][name]==b['prepared'][name],'unequal prefix input '+name)
        ea=copy.deepcopy(a['prepared']['execution']);eb=copy.deepcopy(b['prepared']['execution'])
        if ea is not None:ea.pop('durationMs');eb.pop('durationMs')
        require(ea==eb,'unequal executable oracle result')
        for p,q in zip(a['promotionAttempts'],b['promotionAttempts']):require(p['job']==q['job'],'extra promotion-job information')
    # Adapt only the metadata label to reuse the independently implemented old
    # C2 suffix audit. No raw outcome, count, evidence or verdict is substituted.
    c2=[copy.deepcopy(r) for r in rows if r['condition']=='C2']
    for r in c2:r['batch']='development_qualification_only'
    verify_suffix(c2,selection,pre,header)
    cleanup=load(root,'database-cleanup.json')
    require({r['database'] for r in cleanup}==set(databases) and all(r['remaining']==0 for r in cleanup),'owned database cleanup incomplete')
    telemetry=lines(root,'telemetry.jsonl');require(telemetry and receipt['wallSeconds']<=1200,'resource record/wall limit')
    require(max(t['rssBytes'] for t in telemetry)==receipt['peak']['rssBytes'] and min(t['availableBytes'] for t in telemetry)==receipt['peak']['minAvailableBytes'],'resource extrema')
    timers={}
    for t in telemetry:
        for name,crossed in [('rss',t['rssBytes']>2*1024**3),('available',t['availableBytes']<3*1024**3),('swap',t['swapIncreaseBytes']>1024**3)]:
            if not crossed:timers.pop(name,None)
            else:
                timers.setdefault(name,t['elapsedSeconds']);require(t['elapsedSeconds']-timers[name]<30,'unreported sustained resource stop')
    result=score_directory(root)
    if (root/'scoring.json').is_file():require(load(root,'scoring.json')==result,'archived score/denominator differs from raw reconstruction')
    require(all(r['engineeringExpectationMatched'] for r in rows),'unmatched development engineering expectation')
    return dict(status='PASS',developmentPairs=10,conditionRows=20,sharedRenderedIntents=10,continuedDatabases=20,heldOutCases=0,modelRequests=0,
                scoring={c:{k:v for k,v in result['arms'][c].items() if k!='byCase'} for c in ['C1','C2']},
                round2SemanticActCorrectness='NOT_MEASURED',interpretation=result['interpretation'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--repo',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(verify(args.root,args.repo),indent=2))
