#!/usr/bin/env python3
"""Reconstruct operational manifests, actual raw dataflow and paired window counts.

No legacy case name or expected C1/C2 performance selects an outcome. The audit
checks capture/input/chronology coherence; adverse policy outcomes are scored.
"""
import argparse
import copy
import json
from pathlib import Path

from audit_paired_development import wire_proposal_of_dto
from audit_retrieval_led import load, raw, lines, sha, timestamp
from audit_retrieval_suffix import require, applied_hashes
from score_live_manifest import score_directory


def verify(root, repo):
    receipt = load(root, 'receipt.json'); identity = load(root, 'input-identities.json')
    runtime = load(root, 'runtime-manifest.json'); selection = load(root, 'selection.json'); rows = load(root, 'cases.json')
    cases = {c['caseId']: c for c in runtime['cases']}; n = len(cases)
    require(1 <= n <= 10 and receipt['plannedPairs'] == n and receipt['completedCases'] == receipt['plannedCases'] == 2*n, 'incomplete live population')
    require(receipt['status'] == 'COMPLETE_LIVE_MANIFEST_KNOWN_OBSERVATIONS' and receipt['codeCommit'] == identity['codeCommit'], 'execution status/source')
    require(receipt['heldOutCases'] == receipt['modelRequests'] == 0 and receipt['formalHardwareQualification'] is False, 'scope inflated')
    require(runtime['purpose'] == 'known_development_qualification_only', 'nondevelopment runtime')
    require(sha(raw(root, 'runtime-manifest.json')) == identity['runtimeManifestSha256'] == sha((repo/'experiments/ch7/live-manifest-known-input-v1.json').read_bytes()), 'runtime input identity')
    require(sha(raw(root, 'window-template.json')) == identity['windowTemplateSha256'], 'window template identity')
    require(sha(raw(root, 'selection.json')) == identity['selectionSha256'] == runtime['selectionSha256'], 'candidate selection identity')
    for rel, expected in selection['sources'].items():
        require(sha((repo/rel).read_bytes()) == expected, 'archived candidate/test source changed')
    for rel, expected in identity['liveSources'].items():
        require(sha((repo/rel).read_bytes()) == expected, 'frozen live implementation changed: '+rel)
    order = [(c['caseId'], a) for c in runtime['cases'] for a in c['conditions']]
    require([(r['caseId'], r['condition']) for r in rows] == order and len(set(order)) == 2*n, 'missing/reordered live case or arm')
    journal = lines(root, 'journal.jsonl')
    require([j['sequence'] for j in journal] == list(range(1, len(journal)+1)), 'journal sequence')
    require(all(b['monotonicTicks'] > a['monotonicTicks'] and timestamp(b['utc']) >= timestamp(a['utc']) for a,b in zip(journal,journal[1:])), 'journal time reversal')
    require(len({j['frequency'] for j in journal}) == 1, 'clock scale changed')

    def phase(key, name):
        found = [j for j in journal if j['caseId'] == key and j['phase'] == name]
        require(len(found) == 1, 'missing/duplicate phase '+key+':'+name)
        return found[0]

    require(phase('batch','batch.begin')['detail'] == runtime, 'runtime not the actual driver input')
    prefix_done = phase('batch','prefixes.complete'); ready = phase('batch','renderer.ready'); closed = phase('batch','renderer.closed')
    require(prefix_done['sequence'] < ready['sequence'] < closed['sequence'], 'batch chronology')
    require(timestamp(receipt['phases']['renderer']['startedAt']) > timestamp(prefix_done['utc']), 'render before retrieved prefixes')
    require(timestamp(receipt['phases']['renderer']['endedAt']) <= timestamp(closed['utc']), 'suffix before renderer exit')
    prepared = load(root,'prepared.json')
    require([(p['caseId'],p['condition']) for p in prepared] == order, 'prepared case/arm order')
    require(sha(raw(root,'prepared.json')) == load(root,'renderer-request.json')['preparedSha256'], 'prefix handoff bytes')
    state = raw(root,'client/aijade-render-state.jsonl'); state_lines = state.splitlines(keepends=True)
    header = json.loads(state_lines[0]); end = json.loads(state_lines[-1])
    require(end['complete'] is True and end['lines'] == len(state_lines)-1 and end['sha256'] == sha(b''.join(state_lines[:-1])), 'renderer closure seal')
    require(header['presented_frame_observed'] is False and header['pmx_sha256'] == identity['modelSha256'], 'render stage/asset scope')
    require(sha(state) == load(root,'renderer-closed.json')['stateSha256'] == load(root,'manifest.json')['file_sha256'], 'closed-file hash')
    for key,name in [('initial_clip_sha256','companion-rest.vmd'),('behavior_plan_sha256','companion-plan.json')]:
        require(header[key] == sha((repo/'experiments/p1/external-renderer/preset'/name).read_bytes()), 'renderer preset changed')
    registry = lines(root,'registry.jsonl')
    require(registry[0]['session_id'] == header['session_id'] and registry[0]['renderer_context_id'] == header['renderer_context_id'], 'registered session/context')
    require(len(registry) == n+1 and receipt['registeredIntentCount'] == n, 'actual registration count')
    intent_by_case = {cid:next(r['prepared']['intentId'] for r in rows if r['caseId']==cid) for cid in cases}
    require([r['intent_id'] for r in registry[1:]] == [intent_by_case[c['caseId']] for c in runtime['cases']], 'shared dispatch order')
    pre = {f"{header['renderer_context_id']}:{r['seq']}":r for r in map(json.loads,state_lines[1:-1]) if r.get('packet_type')=='RenderStatePacket'}
    databases = []
    for row in rows:
        cid=row['caseId']; arm=row['condition']; key=cid+'/'+arm; definition=cases[cid]; op=definition['operations']; p=row['prepared']; final=row['final']
        require(row['runtimeInput'] == definition == p['runtimeCase'], 'runtime operation substitution')
        require(row['batch']=='live_manifest_known_development' and row['dataOrigin']=='fresh_known_scenario_execution', 'incorrect live origin')
        require(not {'expected','qualified','engineeringExpectationMatched','semanticMismatchConstructed'} & set(row), 'outcome oracle/label in raw driver record')
        require(row['policyVersion']==('strong-local-v1' if arm=='C1' else 'cross-module-v1') and row['gatewayAttempts']==0, 'condition/provider scope')
        names=['database.open','memory.write.begin','memory.write.end','memory.read.begin','memory.read.end','route.selected','execution.begin','execution.end','intent.mapped',
               'shared_intent.sent','database.resumed','import.begin','import.end','admission.begin','admission.end','commit.begin','commit.end','delivery.begin','delivery.end','round2.begin','round2.end','database.completed','case.complete','database.disposed']
        events=[phase(key,name) for name in names]
        require(all(b['sequence']>a['sequence'] for a,b in zip(events,events[1:])), 'case chronology')
        require(phase(key,'intent.mapped')['sequence'] < phase(cid,'pair.inputs_equal')['sequence'] < prefix_done['sequence'], 'prefix/arm equality order')
        require(ready['sequence'] < phase(cid,'intent.registered')['sequence'] < phase(key,'shared_intent.sent')['sequence'] < closed['sequence'] < phase(key,'database.resumed')['sequence'], 'register/render/suffix order')
        if op['revokeBeforeReuse']:
            require(phase(key,'delivery.end')['sequence'] < phase(key,'revoke.begin')['sequence'] < phase(key,'revoke.end')['sequence'] < phase(key,'round2.begin')['sequence'], 'revocation timing')
        require(row['databaseBefore']==row['databaseAfter']==p['databaseBefore']==phase(key,'database.open')['detail']==phase(key,'database.resumed')['detail']==phase(key,'database.completed')['detail'], 'database continuity')
        databases.append(row['databaseBefore']['database']); require(len(row['databaseBefore']['token'])==32, 'missing continuity token')
        require(row['initialWrite']==phase(key,'memory.write.end')['detail'] and row['initialRead']==phase(key,'memory.read.end')['detail'], 'actual memory capture/journal binding')
        require(row['initialWrite']['status']==201 and row['initialRead']['status']==200 and len(row['initialRead']['response']['items'])==1, 'actual prefix memory calls')
        content=row['initialRead']['response']['items'][0]['content']
        require(content==row['initialWrite']['request']['content'] and content.startswith('ch7_route_'+cid+' '), 'route did not come from actual read')
        cue=json.loads(content.split(' ',1)[1]); route=p['route']
        require(set(cue)=={'caseId','taskId','codeSha256','requestedAct'} and cue['caseId']==cid, 'runtime cue fields/identity')
        require(cue['taskId']==definition['taskId']==p['taskId'] and cue['codeSha256']==definition['codeSha256']==p['codeSha256']==sha(p['code'].encode()), 'retrieved programme binding')
        catalogue=[selection[k] for k in ['usable','unusable']]
        selected=next(c for c in catalogue if c['taskId']==p['taskId'] and c['codeSha256']==p['codeSha256'])
        require(p['code']==selected['code'] and p['archivedSelfVerdict']==selected['trial']['selfVerdict'], 'archived code/self-verdict substitution')
        require(route['memoryContentSha256']==sha(content.encode()) and route['program']['code']==p['code'] and route==phase(key,'route.selected')['detail'], 'returned-route selection')
        execution=p['execution']
        require(execution==phase(key,'execution.end')['detail'], 'fresh execution journal binding')
        require((execution is None) if op['execution']=='omit' else isinstance(execution,dict) and type(execution.get('ok')) is bool, 'execution operation not observed')
        act=op['mapperActOverride'] or cue['requestedAct']
        require(cue['requestedAct']==definition['requestedAct']==p['requestedAct'] and p['mapperInputAct']==act, 'returned act/declared override')
        require(p['dispatchedAct']==(act if execution is not None and execution['ok'] else 'inform'), 'actual execution fallback')
        initial=next(x for x in prepared if (x['caseId'],x['condition'])==(cid,arm))
        require(initial==phase(key,'intent.mapped')['detail']=={k:v for k,v in p.items() if k not in ['registered','packets']}, 'prefix changed after handoff')
        require(p==phase(key,'shared_intent.sent')['detail'] and row==phase(key,'case.complete')['detail'], 'dispatch/final observation journal binding')
        require(len(p['packets'])==2 and all(v['trace_id']==p['intentId'] for v in p['packets']), 'actual intent packet identity/count')
        chosen=row['selectedReceipt']; actual=pre[chosen['renderRef']]
        require(chosen['intentId']==intent_by_case[op['receiptCaseId']] and chosen['intentId'] in {c['trace_id'] for c in actual['consumed']}, 'selected foreign/own receipt binding')
        renderer_hash, server_hash=applied_hashes(actual)
        require(actual['stage']=='behavior_overlay_pre_solve' and renderer_hash==actual['applied_params_hash'] and server_hash==chosen['appliedParamsHash'], 'actual stage/full applied hashes')
        require(chosen['assetVersionHash']==header['pmx_sha256'], 'actual selected asset')
        posts=row['importPosts']
        require(len(posts)==2*n and all(post['status']==201 for post in posts), 'actual receipt import population')
        require(any(post['request']==chosen['request'] for post in posts) and any(post['request']==chosen['receipt'] for post in posts), 'selected receipt absent from imports')
        evidence=row['evidence']
        require(evidence['codeSha256']==p['codeSha256'] and evidence['intentId']==p['intentId'] and evidence['receiptIntentId']==chosen['intentId'], 'actual evidence intent/code')
        require(evidence['assetVersion']==(op['assetVersionOverride'] or chosen['assetVersionHash']) and evidence['claimedStage']==op['claimedStage'], 'unrecorded asset/stage intervention')
        require(evidence['selfVerdict']==p['archivedSelfVerdict'] and evidence['executionOk']==(execution['ok'] if execution is not None else None), 'self/execution evidence')
        require(len(final['specRows'])==final['specs'] and len(final['reportRows'])==final['reports'], 'durable rows/counts')
        require(row['beforeDelivery']['specRows']==final['specRows'] and row['beforeDelivery']['reportRows']==final['reportRows'], 'durable promotion rows hidden after commit observation')
        for spec in final['specRows']:
            require(spec['spec']['proposal']==row['proposal'], 'persisted proposal substitution')
        for call in row['promotionAttempts']:
            require(call['transactionMode']==('service_owned' if arm=='C1' else 'caller_owned'), 'transaction condition')
            require(wire_proposal_of_dto(call['job']['proposal'])==row['proposal'], 'actual called job/proposal binding')
        if row['commit'] is not None:
            require(row['commit']['outcome'] in final['outcomes'], 'committed outcome missing from final observations')
        require((row['duplicateCommit'] is not None)==op['repeatOutcome'] and (row['duplicateReuse'] is not None)==op['repeatOutcome'], 'actual duplicate-operation observations')
    require(len(set(databases))==2*n, 'case/arm database isolation')
    for cid in cases:
        a,b=[next(r for r in rows if (r['caseId'],r['condition'])==(cid,arm)) for arm in ['C1','C2']]
        require(a['initialWrite']['request']==b['initialWrite']['request'] and a['initialRead']==b['initialRead'], 'unequal actual memory input')
        for field in ['runtimeInput','evidence','proposal','selectedReceipt']:
            require(a[field]==b[field], 'unequal decision-facing '+field)
        require([p['request'] for p in a['importPosts']]==[p['request'] for p in b['importPosts']], 'unequal imported receipts')
        require(a['admission']['request']==b['admission']['request'] and a['admission']['status']==b['admission']['status'], 'unequal admission')
        for field in ['runtimeCase','code','codeSha256','taskId','benchSha256','archivedSelfVerdict','route','requestedAct','mapperInputAct','dispatchedAct','mappedIntent','intentId','executionId','registered','packets']:
            require(a['prepared'][field]==b['prepared'][field], 'unequal prefix '+field)
        ea=copy.deepcopy(a['prepared']['execution']); eb=copy.deepcopy(b['prepared']['execution'])
        if ea is not None: ea.pop('durationMs'); eb.pop('durationMs')
        require(ea==eb, 'unequal actual execution result')
        for x,y in zip(a['promotionAttempts'],b['promotionAttempts']): require(x['job']==y['job'], 'extra job information')
    cleanup=load(root,'database-cleanup.json')
    require({r['database'] for r in cleanup}==set(databases) and all(r['remaining']==0 for r in cleanup), 'exact owned lease cleanup')
    telemetry=lines(root,'telemetry.jsonl'); require(telemetry and receipt['wallSeconds']<=1200, 'resource trace/wall limit')
    require(max(t['rssBytes'] for t in telemetry)==receipt['peak']['rssBytes'] and min(t['availableBytes'] for t in telemetry)==receipt['peak']['minAvailableBytes'], 'resource extrema')
    timers={}
    for t in telemetry:
        for name,crossed in [('rss',t['rssBytes']>2*1024**3),('available',t['availableBytes']<3*1024**3),('swap',t['swapIncreaseBytes']>1024**3)]:
            if not crossed: timers.pop(name,None)
            else:
                timers.setdefault(name,t['elapsedSeconds']); require(t['elapsedSeconds']-timers[name]<30, 'unreported resource stop')
    scored=score_directory(root)
    if (root/'scoring.json').is_file(): require(load(root,'scoring.json')==scored, 'actual raw/window score reconstruction')
    return dict(status='LIVE_MANIFEST_DATAFLOW_AUDIT_PASS', knownScenarioPairs=n, measuredConditionRows=2*n,
                retainedOriginalDatabases=2*n, sharedRenderedIntents=n, heldOutCases=0, modelRequests=0,
                conditionCounts={arm:{k:v for k,v in scored['arms'][arm].items() if k!='byCase'} for arm in ['C1','C2']},
                round2SemanticActCorrectness='NOT_MEASURED', interpretation=scored['interpretation'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True); parser.add_argument('--repo',type=Path,required=True)
    args=parser.parse_args(); print(json.dumps(verify(args.root,args.repo),indent=2))
