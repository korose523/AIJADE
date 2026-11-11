"""Independent raw-record suffix reconstruction, retained from the first archive audit.

No .NET qualification flags are used as the evidence for state or reuse checks.
"""
import hashlib
import json
from decimal import Decimal
PROMOTED = {'H','I3','I7','S1'}
REUSED = {'H','I3','S1'}
def sha(data): return hashlib.sha256(data).hexdigest()
def require(condition, reason):
    if not condition: raise ValueError(reason)

def applied_hashes(record):
    applied = {'morph.'+k:v for k,v in record['expressions_applied'].items()}
    applied.update({'bone.'+k:v for k,v in record['avatar_state']['bones'].items()})
    keys = sorted(applied, key=lambda k:k.encode('utf-16-be'))
    renderer = '\n'.join(k+'='+format(applied[k], '.6f') for k in keys)
    def number(v):
        # These archived overlay values have at most six fractional digits and
        # are in JSON.stringify's fixed-notation range; refuse an unhandled case.
        require(v == 0 or 1e-6 <= abs(v) < 1e21, 'unhandled canonical numeric range')
        text = format(Decimal(str(v)), 'f')
        if '.' in text: text = text.rstrip('0').rstrip('.')
        return '0' if v == 0 else text
    canonical = '{'+','.join(json.dumps(k,ensure_ascii=False)+':'+number(applied[k]) for k in keys)+'}'
    return sha(renderer.encode()), sha(canonical.encode())

def verify_suffix(rows, selection, pre, header):
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
        renderer_hash, server_hash = applied_hashes(record)
        require(renderer_hash == record['applied_params_hash'] and server_hash == selected['appliedParamsHash'] and record['stage'] == 'behavior_overlay_pre_solve', 'receipt applied hash/stage not supported by independently canonicalized renderer parameters')
        traces={c['trace_id'] for c in record.get('consumed',[]) if c.get('trace_id')}
        require(selected['intentId'] in traces and selected['assetVersionHash']==header['pmx_sha256'], 'receipt not supported by actual renderer file')
        require(any(p['request']==selected['request'] for p in posts) and any(p['request']==selected['receipt'] for p in posts), 'selected receipt was not imported')
        require((evidence['intentId']!=selected['intentId']) if case=='I1' else evidence['intentId']==selected['intentId'], 'cross-intent intervention drift')
        promoted=case in PROMOTED; reused=case in REUSED
        expected_state='absent' if case=='I8' else 'revoked' if case=='I7' else 'verified' if promoted else 'failed' if case=='I5' else 'unknown'
        require(final['specs']==int(promoted) and final['reports']==int(promoted), 'partial or wrong promotion count')
        if True:
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
            if True:
                require(final['specRows'][0]['spec']['proposal']==proposal and final['reportRows'][0]['result']['promoted'] is True, 'persisted gate/spec/report mismatch')
        if case=='I1': require(r['commit']['outcome']['reason']=='execution_intent_mismatch','I1 refusal cause')
        if case=='I2':
            require(r['admission']['status']==400 and r['admission']['response']['error']=='INVALID_RENDER_TRACE_REFERENCE','I2 HTTP refusal')
            if True:
                require(r['admission']['diagnosticDirectAppendAttempts']==1 and r['admission']['diagnosticCoreReason']=='asset_version_hash_mismatch' and r['admission']['diagnosticEventCount']==0,'I2 diagnostic or zero-write evidence')
        if case=='I3': require(r['duplicateCommit']['duplicate'] is True and r['duplicateDelivery']['duplicate'] is True and r['duplicateReuse']['executed'] is False and authority[0]['revision']==1,'I3 duplicate write/reuse')
        if case=='I4': require(r['commit']['outcome']['reason']=='execution_unknown','I4 refusal cause')
        if case=='I5': require(r['commit']['outcome']['reason']=='execution_failed' and bool(execution['failures']),'I5 execution failure absent')
        if case=='I6': require(r['commit']['outcome']['reason']=='receipt_stage_insufficient','I6 stage escalation')
        if case=='I7': require(r['round2']['memoryOutcome']['state']=='verified' and authority[0]['state']=='revoked' and r['round2']['reason']=='authority_revoked','I7 old positive restored revocation')
        if case=='I8': require(r['databaseErrorCode']=='P0001' and not final['outcomes'] and r['delivery']['status']=='absent','I8 incomplete rollback')
        if case=='S1': require(r['semanticMismatchConstructed'] is True and prepared['requestedAct']!=prepared['dispatchedAct'] and promoted and reused,'semantic counterexample was hidden or misclassified')
