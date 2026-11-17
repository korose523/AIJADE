"""Create one exclusive post-terminal E5 packet; never execute on a live run."""
import argparse
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unicodedata

from packet_common import (BASE,need,typed_equal,read,encoded,sha,path,relative,text_source,
                           file_sha,new,inventory,parent_wait_known,verify_packet,TEXT_SUFFIXES,FORBIDDEN_PARTS,root_engineering_accepted,CODEC_SHA,codec_module)

OLD_P4_SUMMARY='experiments/ch7/mac-prefix-v4-2026-11-17/qualification-attempt-01/packet/summary.json'
OLD_P4_SHA='7dbe9435d07f4357d8282200c3f540429b6bc7e4ed0b898166d328283d337b26'
OLD_E4_ROOT='experiments/ch7/nested-copy-2026-11-18/engineering-attempt-02/packet/'
OLD_E4_SUMMARY_SHA='8d4f66480ec234c097a033165e48649a1c4128ce30f97a497ec256bb068187d1'
OLD_E4_MANIFEST_SHA='819cde4e8f7b8197f74181ec2ac6ec5d2ef82aeda6a6d56e1c949617de917e59'
OLD_E3_ROOT='experiments/ch7/nested-load-2026-11-17/engineering-attempt-01/packet/'
OLD_E3_SUMMARY_SHA='af8c9488554d254fefa86435871d8278389fae98640cf4176e696ce7195d51e9'
OLD_E3_MANIFEST_SHA='75f8d31201824cf437a7142e160a9aab43d49f0c7e9a507cd47fb89df5d3a56b'
FULL_STATUS='ENGINEERING_REAL_NESTED_RAW_AUDIT_PASS_NOT_BACKEND_QUALIFIED'
PARTIAL_STATUS='REFUSED_NESTED_PARTIAL_RECORDS_INVENTORIED_NOT_ENGINEERING_ACCEPTED'
FALSE_SCOPE=('backendQualified','scientificAcceptance','formalHardwareQualification',
             'independentHumanReview','authorApproval','seedConstructed','heldoutComparisonComplete',
             'currentProductInheritsResearchQualification')


def git(repo,*args):
    return subprocess.check_output(['git','--no-replace-objects','-C',str(repo),*args],stderr=subprocess.DEVNULL)


def config_contract():
    return dict(status='ARCHIVE_TOOLS_PREPARATION_ONLY_NO_RUN_DATA_READ',
        schema='aijade.ch7.nested-archive-config.v1',
        required=['repo','sourceCommit','runRoot','packetRoot','packetReceiptPath','passportPath',
                  'parentLaunchRecord','parentTerminal','parentLog','launcherSource','finalCiPath',
                  'independentAudit','rootDisposition','writerStability','rootAdditionalWriterClosure','causePrecisionCorrection','provisionalResultState','outcomeKind','artifacts'],
        outcomeKind=['complete-engineering-accepted','partial-refusal'],
        artifacts='Each {path,packetPath,role}; required roles source-publication/passport-publication/launch-preflight/source-closure/preparation-history. Add all actual audit logs/checkpoints/controls and original before-live CI/preparation failures explicitly.',
        source='Original passport sourceFiles, all extracted from actual sourceCommit Git objects; default requireWorkingSourceMatch=true; no HEAD substitution.',
        disposition=dict(schema='aijade.ch7.e5-root-disposition.v1',
            required=['sourceCommit','independentAuditSha256','writerStabilityProofSha256','engineeringAccepted','numbers','scope']),
        rootDispositionScope={key:False for key in FALSE_SCOPE},
        partialScope='Structural retained-record inventory only; actual started children derive from journal leases, never completed receipt population; outcome-specific cold negative analysis requires later explicit implementation.',
        requiredAcceptedInitializerArtifacts=['initialization.json',*[f'block-{n}/initialization.json' for n in range(1,5)]],
        actualArchivesCreated=0,scientificCasesCreated=0)


def run(config_path):
    c=read(path(config_path));need(c['schema']=='aijade.ch7.nested-archive-config.v1','archive config schema')
    repo,run_root,packet=path(c['repo']),path(c['runRoot']),path(c['packetRoot'])
    receipt_path=path(c['packetReceiptPath'])
    need(not packet.exists() and not receipt_path.exists(),'never overwrite packet or preparation receipt')
    q=c['sourceCommit'];need(type(q) is str and len(q)==40 and all(ch in '0123456789abcdef' for ch in q),'actual full Qe5 commit')
    need(git(repo,'rev-parse',q+'^{commit}').decode().strip()==q,'fixed actual Qe5 missing')
    p=read(path(c['passportPath']));need(p['schema']=='aijade.ch7.nested-load-passport.v1' and p['sourceCommit']==q,
        'actual original passport source identity')
    need(type(p['observerSources']) is dict and len(p['observerSources'])==18
         and 'experiments/ch7/newowned_guard_cursor.py' in p['observerSources']
         and p['onlineReplayMode']=='owned-guard-state-exact-prefix-v1'
         and p['onlineReplayInitializationMode']=='paired-source-verified-owned-state-v1'
         and p['onlineReplaySourceSha256']==p['sourceFiles']['experiments/ch7/newowned_guard_cursor.py'],
         'complete E5 eighteen-source initializer closure required')
    need(path(p['repo'])==repo and path(p['output'])==run_root,'original repo/output binding')
    launch=read(path(c['parentLaunchRecord']));terminal=read(path(c['parentTerminal']))
    waited=parent_wait_known(terminal)
    need(launch['sourceCommit']==terminal['sourceCommit']==q
         and terminal['passportSha256']==launch['passportSha256']==file_sha(path(c['passportPath'])),
         'original parent/source/passport binding')
    need(terminal['launchRecordSha256']==file_sha(path(c['parentLaunchRecord']))
         and terminal['logSha256']==file_sha(path(c['parentLog'])),'original parent record/log bytes differ')
    need(launch['launcherSha256']==terminal['launcherSha256']==p['launcherSha256']==file_sha(path(c['launcherSource'])),
         'actual launcher source identity')
    audit=read(path(c['independentAudit']));disposition=read(path(c['rootDisposition']))
    need(disposition['schema']=='aijade.ch7.e5-root-disposition.v1'
         and disposition['sourceCommit']==q and disposition['independentAuditSha256']==file_sha(path(c['independentAudit']))
         and audit['parentTerminalSha256']==file_sha(path(c['parentTerminal']))
         and disposition['writerStabilityProofSha256']==file_sha(path(c['writerStability']))
         and disposition['rootAdditionalWriterClosureSha256']==file_sha(path(c['rootAdditionalWriterClosure']))
         and disposition['causePrecisionCorrectionSha256']==file_sha(path(c['causePrecisionCorrection'])), 'independent root disposition binding')
    need(type(audit.get('numbers')) is dict and typed_equal(disposition['numbers'],audit['numbers']),
         'complete numeric values/types differ from independently reviewed audit')
    need(all(disposition['scope'].get(key) is False for key in FALSE_SCOPE if key!='currentProductInheritsResearchQualification'),'engineering disposition promotes scientific gates')
    kind=c['outcomeKind'];need(kind in ('complete-engineering-accepted','partial-refusal'),'explicit outcome kind')
    accepted=kind=='complete-engineering-accepted'
    need(root_engineering_accepted(disposition) is accepted,'root outcome disposition differs')
    need(audit['sourceCommit']==q and audit['status']==(FULL_STATUS if accepted else PARTIAL_STATUS),'wrong full/partial audit path')
    need(audit.get('writerStabilityAccepted') is True if not accepted else audit.get('inputFiles') is not None,
         'stable original writer/evidence audit required')
    stability=read(path(c['writerStability']))
    need(stability['writerStabilityAccepted'] is True and stability['allOriginalWritersTerminatedOrClosed'] is True
         and stability['unresolvedWriters']==[] and stability['sourceCommit']==q
         and path(stability['runRoot'])==run_root
         and stability['parentTerminalSha256']==file_sha(path(c['parentTerminal'])),
         'separate source-bound writer closure required for all packet outcomes')
    if not accepted:
        need(audit.get('schema') in ('aijade.ch7.nested-partial-negative-record-audit.v2','aijade.ch7.e5-partial-cold-negative-audit.v1')
             and audit['writerStabilityProofSha256']==file_sha(path(c['writerStability']))
             and audit['completeEngineeringAuditAccepted'] is False,
             'E5 partial structural inventory only; never reuse E3 single-sample semantics')
    before=inventory(run_root,absent_allowed=not accepted)
    need(typed_equal(audit['inputFiles'],before['files']),'complete original run file population differs from independent audit')
    run_receipt=read(run_root/'receipt.json') if (run_root/'receipt.json').is_file() else None
    if accepted:
        need(before['exists'] and run_receipt['status']=='ENGINEERING_REAL_NESTED_LOAD_PASS_PENDING_INDEPENDENT_AUDIT'
             and run_receipt['lifecycleJournalStable'] is True and run_receipt['errors']==[], 'full original candidate incomplete')
        need(terminal['controllerExitCode']==0 and terminal['watchdogTimedOut'] is False
             and terminal['watchdogActions']==[] and terminal['errors']==[],'full engineering parent adverse')
        required={'settling/telemetry.jsonl','admission/telemetry.jsonl','process-observations.jsonl',
            'service-events.jsonl','service-events.terminal.json','stage-events.jsonl','phase-events.jsonl',
            'initialization.json','lifecycle-journal.jsonl','process-policy.json','engineering-passport.json','preflight-continuity.json','receipt.json'}
        required|={f'block-{n}/{name}' for n in range(1,5) for name in
            ('initialization.json','telemetry.jsonl','service-events.jsonl','service-events.terminal.json','ready.json','receipt.json')}
        need(required<=set(before['files']),'complete E5 required original artifact population absent')
    if run_receipt is not None:
        need(run_receipt['sourceCommit']==q and run_receipt['passportSha256']==file_sha(path(c['passportPath'])),
             'original producer receipt source/passport binding')
    ci=read(path(c['finalCiPath']))
    need(ci['headSha']==q and ci['status']=='completed' and ci['conclusion']=='success','actual final Qe5 successful CI required')
    codec=codec_module()
    selected=[];logical_names=set()
    def select(original,destination,role):
        original=text_source(original);destination=relative(destination)
        need(destination not in logical_names and not destination.startswith('transport/'),'packet logical destination collision')
        need(all(not destination.startswith(n+'/') and not n.startswith(destination+'/') for n in logical_names),
             'logical file/directory prefix collision')
        logical_names.add(destination);selected.append(dict(original=original,logical=destination,role=role))
    for name in before['files']:
        select(run_root/name,'run/engineering-03/'+name,'ACTUAL_COMPLETE_OR_PARTIAL_ORIGINAL_RUN')
    originals={'parentLaunchRecord':'launch/engineering-03-launch.json','parentTerminal':'launch/engineering-03-launch.terminal.json',
        'parentLog':'launch/engineering-03-launch.log','launcherSource':'launch/launch_nested_load.py',
        'passportPath':'publication/engineering-03-passport.json','finalCiPath':'publication/final-source-ci.json',
        'independentAudit':'audit/independent-audit.json','rootDisposition':'audit/root-disposition.json',
        'writerStability':'audit/writer-stability.json',
        'rootAdditionalWriterClosure':'audit/root-writer-closure.json',
        'causePrecisionCorrection':'audit/listener-cause-precision-correction.json',
        'provisionalResultState':'history/ACTUAL-E5-RESULT-STATE.json'}
    for key,destination in originals.items():select(path(c[key]),destination,'EXACT_ORIGINAL_'+key)
    roles=set()
    for row in c['artifacts']:
        need(set(row)=={'path','packetPath','role'} and type(row['role']) is str and row['role'],'explicit artifact schema')
        roles.add(row['role']);select(path(row['path']),row['packetPath'],row['role'])
    need({'source-publication','passport-publication','launch-preflight','source-closure','preparation-history'}<=roles,
         'actual Qe5/F/preflight/closure and before-live history receipts required')
    for tool in ('archive_e5_packet.py','packet_common.py','verify_e5_packet.py','inspect_partial_nested_refusal.py','e5_refusal_semantics.py','lossless_members.py'):
        select(Path(__file__).parent/tool,'archive-tools/'+tool,'POSTHOC_ARCHIVE_TOOL_NOT_MEASUREMENT_SOURCE')
    packet.mkdir(parents=True)
    mapping=[];proofs=[];logical_rows=[]
    def archive_selected(row):
        original=row['original'];start=original.stat();digest=file_sha(original)
        relative_directory='transport/'+row['logical'];directory=packet/relative_directory
        directory.parent.mkdir(parents=True,exist_ok=True)
        result=codec.encode_file(original,directory,row['logical'])
        need(result['logicalSha256']==digest and result['logicalSizeBytes']==start.st_size,'encoded complete original differs')
        finish=original.stat()
        need((start.st_dev,start.st_ino,start.st_size,start.st_mtime_ns)==
             (finish.st_dev,finish.st_ino,finish.st_size,finish.st_mtime_ns),'original changed during archive')
        envelope_path=relative_directory+'/envelope.json'
        entry=dict(kind='bounded-gzip-members-v1',logicalPath=row['logical'],logicalSha256=digest,
            logicalSizeBytes=start.st_size,envelopePath=envelope_path,envelopeSha256=result['envelopeSha256'])
        logical_rows.append(entry)
        mapping.append(dict(originalPath=str(original),logicalPacketPath=row['logical'],role=row['role'],
            originalSha256=digest,originalSizeBytes=start.st_size,transportEnvelopePath=envelope_path,
            transportEnvelopeSha256=result['envelopeSha256'],memberCount=result['members'],originalBytesRewritten=False))
    for row in selected:archive_selected(row)
    for name,expected in sorted(p['sourceFiles'].items()):
        relative(name);need(Path(name).suffix.lower() in TEXT_SUFFIXES
             and not any(part.casefold() in FORBIDDEN_PARTS for part in Path(name).parts),
             'nontext/private frozen executable source dependency')
        raw=git(repo,'show',q+':'+name)
        need(b'\0' not in raw and sha(raw)==expected,'frozen original Git source SHA differs')
        current=repo/name;working_hash=file_sha(current) if current.is_file() and not current.is_symlink() else None
        need(c.get('requireWorkingSourceMatch',True) is False or working_hash==expected,'working source changed; never substitute it for fixed Qe5')
        tree=git(repo,'ls-tree','-z',q,'--',name).split(b'\0');need(len(tree)==2 and tree[1]==b'','one exact Git source blob')
        metadata,git_name=tree[0].split(b'\t',1);mode,node,oid=metadata.decode().split()
        need(git_name.decode()==name and node=='blob' and mode in ('100644','100755')
             and hashlib.sha1(('blob %d\0'%len(raw)).encode()+raw).hexdigest()==oid,'fixed Git source blob/mode identity')
        destination='source/'+name;need(destination not in logical_names,'frozen source destination collision')
        logical_names.add(destination);new(packet/destination,raw)
        proofs.append(dict(path=name,commit=q,sha256=expected,gitBlob=oid,gitMode=mode,
            workingHashAtArchive=working_hash,workingSourceMatched=working_hash==expected,selectedBytes='FIXED_GIT_OBJECT'))
    old=git(repo,'show',q+':'+OLD_P4_SUMMARY);need(sha(old)==OLD_P4_SHA,'old P4 refusal summary changed')
    new(packet/'history/p4-refusal-summary.json',old)
    for name,expected in [('summary.json',OLD_E3_SUMMARY_SHA),('packet-manifest.json',OLD_E3_MANIFEST_SHA)]:
        prior=git(repo,'show',q+':'+OLD_E3_ROOT+name)
        need(sha(prior)==expected,'immutable E3 refusal summary/manifest changed')
        new(packet/('history/e3-refusal-'+name),prior)
    for name,expected in [('summary.json',OLD_E4_SUMMARY_SHA),('packet-manifest.json',OLD_E4_MANIFEST_SHA)]:
        prior=git(repo,'show',q+':'+OLD_E4_ROOT+name)
        need(sha(prior)==expected,'immutable E4 refusal summary/manifest changed')
        new(packet/('history/e4-refusal-'+name),prior)
    summary=dict(schema='aijade.ch7.real-nested-engineering-summary.v1',
        status='COMPLETE_REAL_NESTED_ENGINEERING_ENVELOPE_ACCEPTED_NOT_QUALIFIED' if accepted else 'REFUSED_REAL_NESTED_ENGINEERING_ATTEMPT',
        sourceCommit=q,passportSha256=file_sha(path(c['passportPath'])),independentAuditSha256=file_sha(path(c['independentAudit'])),
        rootDispositionSha256=file_sha(path(c['rootDisposition'])),numbers=audit['numbers'],
        rawProducerStatus=run_receipt.get('status') if run_receipt else None,
        rawProducerErrors=run_receipt.get('errors') if run_receipt else None,
        enclosingParentStatus=terminal['status'],enclosingParentExitCode=terminal['controllerExitCode'],
        engineeringEnvelopeAccepted=accepted,causeClassification='UNRESOLVED_OR',
        causePrecisionCorrectionSha256=file_sha(path(c['causePrecisionCorrection'])),
        scope={**{key:False for key in FALSE_SCOPE},'freshHeldoutCases':0,'table7_3':'NOT_RUN',
            'runDirectoryExists':before['exists'],'actualTerminalParentWaitKnown':True,
            'fullIndependentEngineeringAuditAccepted':accepted,'partialRefusalIsNotCompleteEngineeringPass':not accepted},
        numericPolicy='Complete audit numbers copied with exact scalar/container types; unknown/missing fields are never zero-filled.',
        oldP4RefusalSummarySha256=OLD_P4_SHA,oldE3RefusalSummarySha256=OLD_E3_SUMMARY_SHA,
        oldE3RefusalManifestSha256=OLD_E3_MANIFEST_SHA,oldE4RefusalSummarySha256=OLD_E4_SUMMARY_SHA,
        oldE4RefusalManifestSha256=OLD_E4_MANIFEST_SHA,originalProducerPendingFieldsModified=False,
        reviewStatus='ROOT_PACKET_REVIEW_REQUIRED_BEFORE_PUBLICATION',
        interpretation='Finite engineering prefix/topology evidence only. No backend/hardware/human/author/seed/heldout qualification or 4800-second worst-case certificate.')
    new(packet/'summary.json',encoded(summary))
    new(packet/'metadata/run-directory-state.json',encoded(dict(schema='aijade.ch7.original-run-directory-state.v1',originalRoot=str(run_root),**before)))
    new(packet/'metadata/source-map.json',encoded(dict(schema='aijade.ch7.real-nested-source-map.v1',originalSources=mapping)))
    new(packet/'metadata/frozen-source-proofs.json',encoded(dict(schema='aijade.ch7.frozen-source-proofs.v1',
        sourceCommit=q,sourceFiles=p['sourceFiles'],observerSources=p['observerSources'],sources=proofs,
        originalGitSourceSelected=True,currentHeadUsedAsSource=False,privateBinaryBodiesIncluded=False)))
    new(packet/'README.md',encoded(dict(description='Original full or partial real nested engineering record.',
        outcomeKind=kind,originalPendingFieldsPreserved=True,allSelectedOriginals='exact bounded16MiB decoded single-gzip members; empty files retain a zero-byte logical envelope; no byte rewriting',
        sdkModelAssetOrAuthBodiesIncluded=False,scientificQualification=False)))
    rows=[];transport_paths={}
    for f in sorted(packet.rglob('*')):
        if not f.is_file():continue
        name=f.relative_to(packet).as_posix()
        rows.append(dict(path=name,sha256=file_sha(f),sizeBytes=f.stat().st_size))
        if not name.startswith('transport/'):
            logical_rows.append(dict(kind='direct',logicalPath=name,packetPath=name,
                logicalSha256=file_sha(f),logicalSizeBytes=f.stat().st_size))
    manifest=dict(schema='aijade.ch7.real-nested-packet-manifest.v2',transportCodecSha256=CODEC_SHA,sourceCommit=q,
        passportSha256=summary['passportSha256'],outcomeKind=kind,
        independentAuditSha256=summary['independentAuditSha256'],rootDispositionSha256=summary['rootDispositionSha256'],files=rows,logicalFiles=sorted(logical_rows,key=lambda r:r['logicalPath']))
    new(packet/'packet-manifest.json',encoded(manifest))
    result=verify_packet(packet)
    need(typed_equal(before,inventory(run_root,absent_allowed=not accepted)),'original run changed during archive')
    need(all(file_sha(Path(m['originalPath']))==m['originalSha256'] for m in mapping),'original artifact changed after archive')
    result.update(schema='aijade.ch7.real-nested-packet-preparation.v1',
        status='ORIGINAL_REAL_NESTED_PACKET_COMPLETE_PENDING_ROOT_PACKET_REVIEW_NOT_PUBLISHED',
        packetRoot=str(packet),outcomeKind=kind,summarySha256=file_sha(packet/'summary.json'),
        sourceCommit=q,sourceDependencies=len(proofs),sourceMapPopulation=len(mapping),
        actualOriginalRunFiles=len(before['files']),originalRunBytesUnchanged=True,
        createdAt=datetime.now(timezone.utc).isoformat(),networkRequests=0,gitMutations=0,svnRequests=0,
        sdkModelAssetAuthBodiesIncluded=False,scientificCasesOrSeedCreated=False)
    new(receipt_path,encoded(result));print(json.dumps(result,indent=2));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--describe',action='store_true')
    parser.add_argument('--config')
    parser.add_argument('--prepare',action='store_true')
    args=parser.parse_args()
    if args.describe or not args.prepare:
        print(json.dumps(config_contract(),indent=2))
    else:
        need(args.config is not None,'actual reviewed post-terminal config required')
        run(args.config)
