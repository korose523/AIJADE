"""Portable E6 retained-native transcript reconstruction; no OS/source execution."""
from pathlib import Path
import math
import json
from packet_common import decode,need,sha,typed_equal,file_sha
import listener_evidence as listener

NATIVE_MODE='native-ready-release-v1'
NATIVE_PHASES=listener.PHASE_FIELDS
LISTENER_SHA='45617a0a4ee8cec0c10f76151adfe4bd82f9fab4ca67dcd5b78b0f3a444ac2f2'

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
def exact(a,b,label):need(typed_equal(a,b),label)
def real(value,label):
    need(type(value) in (int,float) and math.isfinite(value) and value>=0,label);return value


def verify_native(body,summary,audit,events,rows,passport):
    expected=Path(__file__).with_name('listener_evidence.py').resolve()
    need(Path(listener.__file__).resolve()==expected and file_sha(expected)==LISTENER_SHA,
         'exact normal colocated frozen pure listener helper required')
    policy=decode(body('run/engineering-04/process-policy.json'))
    need(sha(body('run/engineering-04/process-policy.json'))==passport['policySha256'],
         'original native policy bytes differ')
    finite=[e for e in events if e['event']=='FINITE_REGISTER']
    need(len(finite)==3202 and all(e['data']['shimSha256']==policy['nativeExec']['binarySha256'] for e in finite),
         'every actual finite lease must retain one frozen native shim')
    state=dict(leases={},events=[]);cursor=0;records=[]
    def advance(cutoff):
        nonlocal cursor
        while cursor<cutoff:
            e=events[cursor];cursor+=1;state['events'].append(e);d=e['data'];kind=e['event']
            if kind in ('CONTROLLER_REGISTER','FINITE_REGISTER'):
                state['leases'][d['leaseId']]=dict(d,registerSeq=e['seq'],registerMonotonic=e['monotonicSeconds'],
                    releaseSeq=None,releaseMonotonic=None,waitSeq=None,exitCode=None,reapedMonotonic=None)
            elif kind=='RELEASE':state['leases'][d['leaseId']].update(releaseSeq=e['seq'],releaseMonotonic=e['monotonicSeconds'])
            elif kind=='WAIT':state['leases'][d['leaseId']].update(waitSeq=e['seq'],exitCode=d['exitCode'],reapedMonotonic=d['reapedMonotonic'])
    for i,row in enumerate(rows):
        obs=row['processObservation'];advance(obs['lifecycle']['lastSequence'])
        for phase in ('before','after'):
            frame=obs['evidence'][phase];saved=frame['listener'];t=saved['transcript'];clock=frame['listenerReadClock']
            outcome=listener.verify_transcript(t,state,policy,
                parser_source_sha256=passport['sourceFiles']['experiments/ch7/listener_evidence.py'],
                caller_source_sha256=passport['sourceFiles']['experiments/ch7/mac_process_guard_v3.py'],outer_clock=clock)
            claimed={k:saved[k] for k in ('state','code','reasons','records') if k in saved}
            actual={k:outcome[k] for k in ('state','code','reasons','records') if k in outcome}
            need(typed_equal(claimed,actual),'Native raw-byte/deadline/provenance reasons differ')
            records.append(dict(globalIndex=i,sampleId=row['sampleId'],phase=phase,state=outcome['state'],
                code=outcome.get('code'),reasons=outcome.get('reasons',[]),records=outcome['records'],
                internalRunSeconds=t['runCompletedMonotonic']-t['startedMonotonic'],
                internalParseSeconds=t['parseCompletedMonotonic']-t['startedMonotonic'],
                wholeCallSeconds=clock['finishedMonotonic']-clock['startedMonotonic'],
                returnCode=t['returnCode'],exception=t['exception'],stdout=t['stdout'],stderr=t['stderr'],
                nativeLeaseId=t['nativeLaunch']['leaseId'],actualNativeWaitSequence=t['nativeLaunch']['waitSequence'],
                nativeSourcePins=t['sourcePins'],originalRawTranscriptComplete=True))
    advance(len(events))
    rec=decode(body('run/engineering-04/receipt.json'));proof=rec['preflightCommands'][0]
    for row in rec['preflightCommands'][1:]+rec['prefixPaddingCommands']:
        need('firstNativeProofLaunchEvidence' not in row and 'firstNativeProofEvidenceCompletedMonotonic' not in row,
             'additional Native first-use diagnostic is not authorized')
    value=proof['firstNativeProofLaunchEvidence'];lease=state['leases'][value['leaseId']]
    owner=lease['parentIdentity'];context=dict(policy=policy,passport=passport)
    first=[verify_first_native_proof(proof,lease,state,owner,context,rows[0]['monotonicSeconds'])]
    result=dict(schema='aijade.ch7.e6-native-transcript-and-first-proof-audit.v1',
        lifecycleExecMode=passport['lifecycleExecMode'],observerSourceCount=21,finiteNativeShimBindings=len(finite),
        firstExistingSourceProofs=first,firstExistingSourceProofCount=len(first),rawTranscripts=len(records),
        observedTranscripts=sum(v['state']=='OBSERVED' for v in records),unknownTranscripts=sum(v['state']=='UNKNOWN' for v in records),
        beforeObserved=sum(v['phase']=='before' and v['state']=='OBSERVED' for v in records),
        afterObserved=sum(v['phase']=='after' and v['state']=='OBSERVED' for v in records),
        afterUnknown=sum(v['phase']=='after' and v['state']=='UNKNOWN' for v in records),
        internalCallDeadlineExceeded=sum('INTERNAL_CALL_DEADLINE_EXCEEDED' in v['reasons'] for v in records),
        wholeCallDeadlineExceeded=sum('WHOLE_CALL_DEADLINE_EXCEEDED' in v['reasons'] for v in records),
        actualNativeWaitZero=sum(type(v['returnCode']) is int and v['returnCode']==0 for v in records),
        noException=sum(v['exception'] is None for v in records),completeStdout=sum(v['stdout']['truncated'] is False for v in records),
        emptyStderr=sum(v['stderr']['totalBytes']==0 for v in records),constructorCalls=0,currentPhysicalBinaryAuthenticationCalls=0,
        sourcePins=dict(adapter=passport['nativeExec']['adapterSourceSha256'],CSource=passport['nativeExec']['sourceSha256'],
            binary=passport['nativeExec']['binarySha256'],listener=passport['sourceFiles']['experiments/ch7/listener_evidence.py'],
            guard=passport['sourceFiles']['experiments/ch7/mac_process_guard_v3.py']),summaries=records,lastAfter=records[-1],
        interpretation='Every complete original before/after transcript checked cold against its actual cutoff and direct owner WAIT; deadline reasons reproduced, no new listener execution or underlying-cause inference.')
    need(typed_equal(result,audit['nativeLifecycleAudit']),'complete typed336-transcript Native audit object differs')
    return dict(rawTranscripts=len(records),observed=335,unknown=1,firstExistingProofs=1,
                originalReasonsRecomputed=True,newKernelExecution=False)

# Exact own frozen1a246 function below, independently source-bound in metadata.
def verify_first_native_proof(record, lease, state, owner, context, end_boundary):
    """Independently bind the first existing Git proof, with no extra command."""
    policy,passport=context['policy'],context['passport'];binding=policy['nativeExec']
    value=record['firstNativeProofLaunchEvidence']
    fields={'schema','mode','leaseId','stageId','role','identity','commandSha256','executableSha256',
        'shimSha256','adapterSourceSha256','shimSourceSha256','phaseClocks','readyMonotonic',
        'actualReapedMonotonic','waitEventMonotonic','waitSequence','exitCode','waitSource',
        'captureLock','sourceProofBefore','sourceProofReady','sourceProofAfter','executedShimIdentity'}
    need(type(value) is dict and set(value)==fields and value['schema']=='aijade.lifecycle.native-launch.v1'
         and value['mode']==NATIVE_MODE,'first native proof schema/mode')
    for key in ('leaseId','stageId','role','identity','commandSha256','executableSha256','shimSha256','readyMonotonic'):
        exact(value[key],lease[key],'first native proof original lease binding: '+key)
    exact(lease['parentIdentity'],owner,'first native proof belongs to another controller')
    need(value['role']=='finite' and value['commandSha256']==sha(canonical(record['command']))
         and value['executableSha256']==passport['toolExecutableSha256']['git']
         and value['adapterSourceSha256']==binding['adapterSourceSha256']
         and value['shimSourceSha256']==binding['sourceSha256']
         and value['shimSha256']==binding['binarySha256'],'first native proof command/source/executable')
    phases=value['phaseClocks']
    need(type(phases) is dict and set(phases)==set(NATIVE_PHASES),'first native proof complete phase population')
    clocks=[real(record['startedMonotonic'],'first native source proof start')]+[
        real(phases[k],'first native proof actual phase clock') for k in NATIVE_PHASES]
    need(all(a<=b for a,b in zip(clocks,clocks[1:])),'first native proof phase order')
    completed=real(record['completedMonotonic'],'first native source proof complete')
    diagnostic=real(record['firstNativeProofEvidenceCompletedMonotonic'],'first native proof diagnostic complete')
    ready=real(value['readyMonotonic'],'first native proof declared READY')
    reaped=real(value['actualReapedMonotonic'],'first native proof actual Popen.wait')
    waited=real(value['waitEventMonotonic'],'first native proof actual WAIT event')
    need(phases['popenStartedMonotonic']<=ready<=phases['readyReadCompletedMonotonic']
         and phases['returnedMonotonic']<=completed<=diagnostic<=end_boundary
         and phases['gateWrittenMonotonic']<=reaped<=waited<=completed,
         'first native proof actual READY/run/reap/diagnostic envelope')
    exact(value['waitSequence'],lease['waitSeq'],'first native proof canonical WAIT sequence')
    exact(value['actualReapedMonotonic'],lease['reapedMonotonic'],'first native proof canonical reap clock')
    exact(value['exitCode'],0,'first native proof actual zero exit')
    need(value['waitSource']=='Popen.wait','first native proof actual direct parent wait source')
    events={}
    for event in state['events']:
        if event['data'].get('leaseId')==lease['leaseId'] and event['event'] in ('FINITE_REGISTER','RELEASE','WAIT'):
            need(event['event'] not in events,'first native proof duplicate canonical event')
            events[event['event']]=event
    need(set(events)=={'FINITE_REGISTER','RELEASE','WAIT'},'first native proof missing canonical trace')
    reg,release,wait=(events[k] for k in ('FINITE_REGISTER','RELEASE','WAIT'))
    for event in (reg,release,wait):exact(event['writer'],owner,'first native proof canonical writer')
    need(type(value['waitSequence']) is int and reg['seq']==lease['registerSeq']<release['seq']==lease['releaseSeq']
         <wait['seq']==value['waitSequence'] and wait['monotonicSeconds']==waited
         and phases['registerStartedMonotonic']<=reg['monotonicSeconds']<=phases['registerCompletedMonotonic']
         and phases['releaseStartedMonotonic']<=release['monotonicSeconds']<=phases['releaseCompletedMonotonic'],
         'first native proof canonical trace phase binding')
    proof_fields={'path','sha256','device','inode','sizeBytes','mtimeNs','mode'}
    for key in ('sourceProofBefore','sourceProofReady','sourceProofAfter'):
        proof=value[key]
        need(type(proof) is dict and set(proof)=={'adapter','source','binary'},'first native proof source population')
        for name,expected in [('adapter',binding['adapterSourceSha256']),('source',binding['sourceSha256']),('binary',binding['binarySha256'])]:
            item=proof[name]
            need(type(item) is dict and set(item)==proof_fields and type(item['path']) is str
                 and item['path'].startswith('/') and '..' not in Path(item['path']).parts
                 and item['sha256']==expected and all(type(item[k]) is int and item[k]>=0
                     for k in ('device','inode','sizeBytes','mtimeNs','mode'))
                 and item['inode']>0 and item['sizeBytes']>0,'first native proof source identity/schema')
        need(proof['source']['path']==binding['sourcePath'] and proof['binary']['path']==binding['binaryPath']
             and str(Path(proof['adapter']['path']).with_name('lifecycle_exec_native.c'))==binding['sourcePath']
             and Path(proof['adapter']['path']).name=='native_exec_registry.py'
             and proof['binary']['mode']==0o755,'first native proof original logical source/binary paths')
    exact(value['sourceProofBefore'],value['sourceProofReady'],'first native proof READY source generation')
    exact(value['sourceProofBefore'],value['sourceProofAfter'],'first native proof final source generation')
    executed=value['executedShimIdentity']
    need(type(executed) is dict and set(executed)=={'pid','createTimeMicros','parentPid','executable','argvSha256'},
         'first native proof executed gated image schema')
    exact({k:executed[k] for k in ('pid','createTimeMicros','parentPid')},lease['identity'],
          'first native proof executed gated image identity')
    need(executed['executable']==binding['binaryPath'] and type(executed['argvSha256']) is str
         and len(executed['argvSha256'])==64 and all(c in '0123456789abcdef' for c in executed['argvSha256']),
         'first native proof executed shim image/argv')
    lock=value['captureLock']
    need(type(lock) is dict and set(lock)=={'schema','pathSha256','maxWaitSeconds','state','waitSeconds',
         'acquiredMonotonic','nested','initialIdentity','finalIdentity','releasedMonotonic'}
         and lock['schema']=='aijade.lifecycle.capture-lock.v1' and lock['nested'] is False
         and lock['state']=='HELD_AND_RELEASED' and type(lock['maxWaitSeconds']) is float and lock['maxWaitSeconds']==1.25
         and lock['pathSha256']==sha(policy['lifecycle']['coordinationLockPath'].encode())
         and real(lock['waitSeconds'],'first native proof capture wait')<=1.25,
         'first native proof own capture lock schema/path')
    need(phases['captureRequestedMonotonic']<=real(lock['acquiredMonotonic'],'first native capture acquired')
         <=phases['captureAcquiredMonotonic'] and phases['postProvenanceCompletedMonotonic']
         <=real(lock['releasedMonotonic'],'first native capture released')<=phases['returnedMonotonic'],
         'first native proof own capture lock clock envelope')
    ident=lock['initialIdentity'];exact(ident,lock['finalIdentity'],'first native capture inode changed')
    need(type(ident) is dict and set(ident)=={'device','inode','regular','singleLink','ownedByCurrentUser'}
         and type(ident['device']) is int and ident['device']>=0 and type(ident['inode']) is int and ident['inode']>0
         and all(ident[k] is True for k in ('regular','singleLink','ownedByCurrentUser')),'first native capture lock identity')
    return dict(leaseId=lease['leaseId'],actualWaitSequence=value['waitSequence'],
                commandSha256=value['commandSha256'],diagnosticCompletedMonotonic=diagnostic)

