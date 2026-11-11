#!/usr/bin/env python3
"""Audit actual persisted-spec to second-render command delivery; no expected outcome filter."""
import argparse
import copy
import json
from pathlib import Path

from audit_live_manifest import verify as verify_base
from audit_retrieval_led import raw, load, lines, sha, timestamp
from audit_retrieval_suffix import require, applied_hashes

COMMANDS = {
    'inform': ([0, .4, .5, .5], [0, 0, 0, 0], 'neutral_attentive'),
    'comfort': ([.1, .25, .5, .5], [0, -.05, .15, -.15], 'neutral_attentive'),
    'celebrate': ([.4, .65, .5, .5], [0, 0, 0, 0], 'bright_smile'),
}


def verify(root, repo):
    base = verify_base(root, repo)
    receipt=load(root,'receipt.json'); identity=load(root,'input-identities.json')
    require(receipt['study']=='known_second_round_persisted_act_delivery' and receipt['round2Status']=='OBSERVATIONS_COMPLETE','extension status')
    require(identity['study']==receipt['study'] and identity['assemblyInfo']['embeddedGitRevision']==receipt['codeCommit'],'clean build provenance')
    require('0.1.0+'+receipt['codeCommit'] in identity['assemblyInfo']['text'],'embedded assembly source')
    require(sha(identity['assemblyInfo']['text'].encode())==identity['assemblyInfo']['sha256'],'assembly metadata bytes')
    admission=load(root,'admission.json'); samples=lines(root,'admission-telemetry.jsonl')
    require(admission['admitted'] is True and admission['windowReset'] is False and samples[0]['elapsedSeconds']<1 and samples[-1]['elapsedSeconds']>=120,'whole idle window')
    require(all(0 < b['elapsedSeconds']-a['elapsedSeconds']<=3 for a,b in zip(samples,samples[1:])),'admission sampling gaps')
    require(admission['samples']==len(samples) and admission['minimumAvailableBytes']==min(x['availableBytes'] for x in samples)>=4*1024**3,'idle memory admission')
    require(admission['swapRangeBytes']==max(x['swapUsedBytes'] for x in samples)-min(x['swapUsedBytes'] for x in samples)<=64*1024**2,'idle swap admission')
    require(all(not x['researchProcesses'] for x in samples),'admission not unloaded')
    require(timestamp(samples[-1]['utc'])<=timestamp(receipt['phases']['flow']['startedAt']),'research before admission')
    require(all(p['exitCode']==0 for p in receipt['phases'].values()),'owned process not successful')
    require(timestamp(receipt['phases']['renderer']['endedAt'])<=timestamp(receipt['phases']['renderer-round2']['startedAt']),'overlapping renderers')
    runtime=load(root,'runtime-manifest.json'); rows=load(root,'cases.json')
    order=[(c['caseId'],a) for c in runtime['cases'] for a in c['conditions']]
    definitions={c['caseId']:c for c in runtime['cases']}
    before=load(root,'round2/actions-prepared.json')
    sent=load(root,'round2/actions-dispatched.json')
    actions=load(root,'round2/actions.json')
    require(all([(r['caseId'],r['condition']) for r in data]==order for data in [before,sent,actions]),'missing/reordered second condition')
    require(len(actions)==receipt['round2ObservationRows']==20,'complete second dispositions')
    require(sha(raw(root,'round2/actions-prepared.json'))==load(root,'round2/renderer-request.json')['preparedSha256'],'second handoff hash')
    journal=lines(root,'round2/journal.jsonl'); bj=lines(root,'journal.jsonl')
    require([j['sequence'] for j in journal]==list(range(1,len(journal)+1)),'second journal sequence')
    require(all(b['monotonicTicks']>a['monotonicTicks'] and timestamp(b['utc'])>=timestamp(a['utc']) for a,b in zip(journal,journal[1:])),'second time reversal')
    require(len({j['frequency'] for j in journal})==1,'second clock scale')
    def phase(key,name):
        found=[j for j in journal if j['caseId']==key and j['phase']==name]
        require(len(found)==1,'missing/duplicate second phase '+key+':'+name)
        return found[0]
    ready=phase('batch','renderer.ready'); closed=phase('batch','renderer.closed'); selected=phase('batch','selections.complete')
    require(selected['sequence']<ready['sequence']<closed['sequence'],'second session chronology')
    require(timestamp(selected['utc'])<timestamp(receipt['phases']['renderer-round2']['startedAt']),'second render before selected database sources')
    require(timestamp(receipt['phases']['renderer-round2']['endedAt'])<=timestamp(closed['utc']),'second imported before process exit')
    state=raw(root,'round2/client/aijade-render-state.jsonl'); chunks=state.splitlines(keepends=True)
    header=json.loads(chunks[0]); end=json.loads(chunks[-1]); first_header=json.loads(raw(root,'client/aijade-render-state.jsonl').splitlines()[0])
    require(end['complete'] is True and end['lines']==len(chunks)-1 and end['sha256']==sha(b''.join(chunks[:-1])),'second renderer closure')
    require(header['session_id']==first_header['session_id']+'-round2' and header['renderer_context_id']!=first_header['renderer_context_id'],'fresh second session/context')
    require(header['presented_frame_observed'] is False and header['pmx_sha256']==identity['modelSha256'],'second stage/asset')
    manifest=load(root,'round2/manifest.json'); registry=lines(root,'round2/registry.jsonl')
    require(sha(state)==manifest['file_sha256']==load(root,'round2/renderer-closed.json')['stateSha256'],'second closed state hash')
    require(registry[0]['session_id']==manifest['session_id']==header['session_id'] and registry[0]['renderer_context_id']==header['renderer_context_id'],'second registry identity')
    eligible=[r for r in before if r['disposition']=='prepared']
    require(len(registry)==len(eligible)+1 and manifest['expected_intents']==len(eligible),'second registration population')
    require([r['intent_id'] for r in registry[1:]]==[r['mappedIntent']['id'] for r in eligible],'second dispatch order')
    events=[json.loads(s) for s in chunks[1:-1] if json.loads(s).get('packet_type')=='RenderStatePacket']
    pre={header['renderer_context_id']+':'+str(r['seq']):r for r in events}
    require(manifest['actual_pre_solve_rows']==len(events),'second pre-solve row count')
    require(manifest['complete'] is True and manifest['end_state']=='closed','second sealed manifest')
    disposition=load(root,'round2/receipt-dispositions.json')
    require(not disposition['fileReasons'],'second file rejected')
    summaries={a:dict(scheduled=10,reuseRefused=0,configurationUnavailable=0,dispatched=0,receiptKnown=0,
                       commandWitnessKnown=0,commandWitnessUnknown=0,requestMatches=0,requestMismatches=0,
                       serverImportsAccepted=0) for a in ['C1','C2']}
    result=[]
    for b,p,s,a in zip(rows,before,sent,actions):
        cid=a['caseId']; arm=a['condition']; key=cid+'/'+arm; definition=definitions[cid]
        require(p['baseRound2']==s['baseRound2']==a['baseRound2']==b['round2'],'actual reuse source substituted')
        require(p['requestedActReference']==s['requestedActReference']==a['requestedActReference']==definition['requestedAct'],'request reference substituted')
        require(p['databaseBefore']==a['databaseBefore']==a['databaseAfter']==b['databaseBefore'],'second database continuity')
        start=phase(key,'selection.begin'); finish=phase(key,'selection.end'); done=phase(key,'case.complete')
        prior=next(j for j in bj if j['caseId']==key and j['phase']=='case.complete')
        disposed=next(j for j in bj if j['caseId']==key and j['phase']=='database.disposed')
        require(timestamp(prior['utc'])<=timestamp(start['utc']) and start['sequence']<finish['sequence']<selected['sequence']<closed['sequence']<done['sequence'] and timestamp(done['utc'])<=timestamp(disposed['utc']),'second per-case chronology')
        require(p==finish['detail'] and a==done['detail'],'second source/final journal binding')
        for field in ['specRows','reportRows','authority','outcomes','outboxCount','outcomeMemoryCount','reuseCount']:
            require(a['snapshotAfterRender'][field]==b['final'][field],'second delivery changed learning/reuse state')
        summary=summaries[arm]
        item=dict(caseId=cid,condition=arm,disposition=a['disposition'],requestedAct=definition['requestedAct'],
                  persistedAct=p.get('persistedAct'),mappedAct=p.get('mappedAct'),requestAgreement=None,commandWitnessKnown=False)
        if b['round2']['executed'] is not True:
            require(p['disposition']==a['disposition']=='reuse_refused' and a['dispatched'] is False and a['receipt'] is None and not a['importPosts'],'dispatch after refused reuse')
            require('mappedIntent' not in a and 'packets' not in a,'hidden forbidden dispatch')
            summary['reuseRefused']+=1
        else:
            if p['disposition']=='configuration_unavailable':
                require(not a['dispatched'] and a['receipt'] is None and not a['importPosts'],'dispatch after unavailable configuration')
                summary['configurationUnavailable']+=1
            else:
                require(p['authorityAfterReuse']==b['round2']['authority'],'authority source after reuse')
                require(json.loads(p['specText'])==p['specification'] and sha(p['specText'].encode())==p['specTextSha256'],'actual SQL specification bytes')
                require(p['specId']==p['authorityAfterReuse']['specId'],'wrong persisted spec id')
                stored=next(x['spec'] for x in b['final']['specRows'] if x['id']==p['specId'])
                require(stored==p['specification'],'database source row substituted')
                params=stored['proposal']['candidateParams']; require(set(params)=={'emotion.preset'} and params['emotion.preset'] in COMMANDS,'closed persisted act')
                require(p['persistedAct']==params['emotion.preset'] and p['mappedAct']==(p['persistedAct'] if b['round2']['execution']['ok'] else 'inform'),'act was not sourced from persisted spec/verdict')
                require(a['dispatched'] and s['dispatched'] and s['disposition']=='prepared','actual second dispatch absent')
                for k in ['authorityAfterReuse','specId','specText','specTextSha256','specification','persistedAct','mappedAct','mappedIntent']:
                    require(a[k]==s[k]==p[k],'source changed after preparation '+k)
                require(a['registered']==s['registered'] and a['packets']==s['packets'],'packets changed after dispatch')
                reg=phase(key,'intent.registered'); send=phase(key,'intent.sent')
                require(ready['sequence']<reg['sequence']<send['sequence']<closed['sequence'],'registration/send order')
                require(reg['detail']==s['registered'] and send['detail']==s,'actual second send binding')
                packets=a['packets']; intent=a['mappedIntent']; require(len(packets)==2 and all(x['trace_id']==intent['id'] and x['run_id']==header['session_id'] for x in packets),'second packet identity')
                require([x['packet_type'] for x in packets]==['AffectToAvatarPacket','ControlToAvatarPosePacket'],'second packet types')
                summary['dispatched']+=1
                if a['receipt'] is None:
                    require(a['disposition']=='render_unknown' and not a['importPosts'],'missing receipt must remain unknown')
                    candidates=[e for e in events if {v['trace_id'] for v in e['consumed']}=={intent['id']}]
                    require(not any(applied_hashes(e)[0]==e['applied_params_hash'] for e in candidates),'observed second receipt hidden as missing')
                    summary['commandWitnessUnknown']+=1
                else:
                    r=a['receipt']; actual=pre[r['renderRef']]
                    require(a['disposition']=='applied_known' and r['intentId']==intent['id'] and r['assetVersionHash']==header['pmx_sha256'],'second receipt link')
                    require(actual['stage']=='behavior_overlay_pre_solve','second receipt stage escalation')
                    consumed=[{k:x[k] for k in ['packet_type','run_id','seq','t_sim','trace_id']} for x in packets]
                    require(actual['consumed']==consumed,'foreign or incomplete consumed commands')
                    rh,sh=applied_hashes(actual); require(rh==actual['applied_params_hash'] and sh==r['appliedParamsHash'],'second independently rebuilt hashes')
                    posts=a['importPosts']; require(len(posts)==2 and [x['request'] for x in posts]==[r['request'],r['receipt']],'second server import records')
                    if all(200<=x['status']<300 for x in posts): summary['serverImportsAccepted']+=1
                    summary['receiptKnown']+=1
                    vector,pose,hint=COMMANDS[p['mappedAct']]
                    witness=(packets[0]['avatar_emotion_vector']==vector and packets[1]['pose_params']==pose
                             and packets[0]['animation_state_hint']==hint
                             and actual['avatar_state']['hints']['animation_state_hint']==hint)
                    item['commandWitnessKnown']=witness
                    if witness:
                        agreement=p['mappedAct']==definition['requestedAct']
                        item['requestAgreement']=agreement
                        summary['commandWitnessKnown']+=1
                        summary['requestMatches' if agreement else 'requestMismatches']+=1
                    else: summary['commandWitnessUnknown']+=1
        result.append(item)
    for a,s in summaries.items():
        require(s['scheduled']==s['reuseRefused']+s['configurationUnavailable']+s['dispatched'],'disposition denominator')
        require(s['dispatched']==s['commandWitnessKnown']+s['commandWitnessUnknown'],'witness denominator')
    return dict(schema='aijade.ch7.round2-render-audit.v1',status='KNOWN_SECOND_ROUND_COMMAND_OBSERVATIONS_AUDITED',
                conditionCounts=summaries,byCase=result,baseIntegrityCounts=base['conditionCounts'],
                completeOriginalDatabases=20,separateRendererSessions=2,heldOutCases=0,modelRequests=0,
                independentHumanReview=False,formalHardwareQualification=False,round2DialogueAnswerQuality='NOT_MEASURED',
                semanticScope='Exact requested-act versus persisted-command agreement with a pre-solve delivery witness; no pixel, conversational appropriateness, human benefit or held-out claim.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--repo',type=Path,required=True)
    a=p.parse_args();print(json.dumps(verify(a.root,a.repo),indent=2))
