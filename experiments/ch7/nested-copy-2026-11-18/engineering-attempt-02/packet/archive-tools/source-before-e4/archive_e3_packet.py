"""Create one exclusive post-terminal E3 packet; never execute on a live run."""
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
                           file_sha,new,inventory,parent_wait_known,verify_packet,TEXT_SUFFIXES,FORBIDDEN_PARTS)

OLD_P4_SUMMARY='experiments/ch7/mac-prefix-v4-2026-11-17/qualification-attempt-01/packet/summary.json'
OLD_P4_SHA='7dbe9435d07f4357d8282200c3f540429b6bc7e4ed0b898166d328283d337b26'
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
                  'independentAudit','rootDisposition','outcomeKind','artifacts'],
        outcomeKind=['complete-engineering-accepted','partial-refusal'],
        artifacts='Each {path,packetPath,role}; required roles source-publication/passport-publication/launch-preflight/source-closure/preparation-history. Add all actual audit logs/checkpoints/controls and original before-live CI/preparation failures explicitly.',
        source='Original passport sourceFiles, all extracted from actual sourceCommit Git objects; default requireWorkingSourceMatch=true; no HEAD substitution.',
        disposition=dict(schema='aijade.ch7.nested-engineering-root-disposition.v1',
            required=['sourceCommit','independentAuditSha256','parentTerminalSha256','engineeringEnvelopeAccepted','numbers','scope']),
        rootDispositionScope={key:False for key in FALSE_SCOPE},
        actualArchivesCreated=0,scientificCasesCreated=0)


def run(config_path):
    c=read(path(config_path));need(c['schema']=='aijade.ch7.nested-archive-config.v1','archive config schema')
    repo,run_root,packet=path(c['repo']),path(c['runRoot']),path(c['packetRoot'])
    receipt_path=path(c['packetReceiptPath'])
    need(not packet.exists() and not receipt_path.exists(),'never overwrite packet or preparation receipt')
    q=c['sourceCommit'];need(type(q) is str and len(q)==40 and all(ch in '0123456789abcdef' for ch in q),'actual full Qe2 commit')
    need(git(repo,'rev-parse',q+'^{commit}').decode().strip()==q,'fixed actual Qe2 missing')
    p=read(path(c['passportPath']));need(p['schema']=='aijade.ch7.nested-load-passport.v1' and p['sourceCommit']==q,
        'actual original passport source identity')
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
    need(disposition['schema']=='aijade.ch7.nested-engineering-root-disposition.v1'
         and disposition['sourceCommit']==q and disposition['independentAuditSha256']==file_sha(path(c['independentAudit']))
         and disposition['parentTerminalSha256']==file_sha(path(c['parentTerminal'])), 'independent root disposition binding')
    need(type(audit.get('numbers')) is dict and typed_equal(disposition['numbers'],audit['numbers']),
         'complete numeric values/types differ from independently reviewed audit')
    need(all(disposition['scope'].get(key) is False for key in FALSE_SCOPE),'engineering disposition promotes scientific gates')
    kind=c['outcomeKind'];need(kind in ('complete-engineering-accepted','partial-refusal'),'explicit outcome kind')
    accepted=kind=='complete-engineering-accepted'
    need(disposition['engineeringEnvelopeAccepted'] is accepted,'root outcome disposition differs')
    need(audit['sourceCommit']==q and audit['status']==(FULL_STATUS if accepted else PARTIAL_STATUS),'wrong full/partial audit path')
    need(audit.get('writerStabilityAccepted') is True if not accepted else audit.get('inputFiles') is not None,
         'stable original writer/evidence audit required')
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
            'lifecycle-journal.jsonl','process-policy.json','engineering-passport.json','preflight-continuity.json','receipt.json'}
        required|={f'block-{n}/{name}' for n in range(1,5) for name in
            ('telemetry.jsonl','service-events.jsonl','service-events.terminal.json','ready.json','receipt.json')}
        need(required<=set(before['files']),'complete E3 required original artifact population absent')
    if run_receipt is not None:
        need(run_receipt['sourceCommit']==q and run_receipt['passportSha256']==file_sha(path(c['passportPath'])),
             'original producer receipt source/passport binding')
    ci=read(path(c['finalCiPath']))
    need(ci['headSha']==q and ci['status']=='completed' and ci['conclusion']=='success','actual final Qe2 successful CI required')
    selected=[];physical_names=set();logical_names=set()
    def select(original,destination,role):
        original=text_source(original);destination=relative(destination)
        zipped=original.suffix=='.jsonl' and original.stat().st_size>0
        physical=destination+'.gz' if zipped else destination
        key=unicodedata.normalize('NFC',physical).casefold()
        need(key not in physical_names and destination not in logical_names,'packet destination collision')
        physical_names.add(key);logical_names.add(destination)
        selected.append(dict(original=original,logical=destination,physical=physical,role=role,compress=zipped))
    for name in before['files']:
        select(run_root/name,'run/engineering-01/'+name,'ACTUAL_COMPLETE_OR_PARTIAL_ORIGINAL_RUN')
    originals={'parentLaunchRecord':'launch/engineering-01-launch.json','parentTerminal':'launch/engineering-01-launch.terminal.json',
        'parentLog':'launch/engineering-01-launch.log','launcherSource':'launch/launch_nested_load.py',
        'passportPath':'publication/engineering-01-passport.json','finalCiPath':'publication/final-source-ci.json',
        'independentAudit':'audit/independent-audit.json','rootDisposition':'audit/root-disposition.json'}
    for key,destination in originals.items():select(path(c[key]),destination,'EXACT_ORIGINAL_'+key)
    roles=set()
    for row in c['artifacts']:
        need(set(row)=={'path','packetPath','role'} and type(row['role']) is str and row['role'],'explicit artifact schema')
        roles.add(row['role']);select(path(row['path']),row['packetPath'],row['role'])
    need({'source-publication','passport-publication','launch-preflight','source-closure','preparation-history'}<=roles,
         'actual Qe2/F/preflight/closure and before-live history receipts required')
    for tool in ('archive_e3_packet.py','packet_common.py','verify_e3_packet.py','inspect_partial_nested_refusal.py'):
        select(Path(__file__).parent/tool,'archive-tools/'+tool,'POSTHOC_ARCHIVE_TOOL_NOT_MEASUREMENT_SOURCE')
    packet.mkdir(parents=True)
    mapping=[];proofs=[]
    def archive_selected(row):
        original=row['original'];start=original.stat();digest=file_sha(original);target=packet/row['physical'];target.parent.mkdir(parents=True,exist_ok=True)
        with original.open('rb') as stream,target.open('xb') as output:
            if row['compress']:
                with gzip.GzipFile(filename='',fileobj=output,mode='wb',compresslevel=6,mtime=0) as zipper:
                    shutil.copyfileobj(stream,zipper,1024*1024)
            else:shutil.copyfileobj(stream,output,1024*1024)
        finish=original.stat()
        need((start.st_dev,start.st_ino,start.st_size,start.st_mtime_ns)==
             (finish.st_dev,finish.st_ino,finish.st_size,finish.st_mtime_ns),'original changed during archive')
        mapping.append(dict(originalPath=str(original),logicalPacketPath=row['logical'],packetPath=row['physical'],
            role=row['role'],originalSha256=digest,originalSizeBytes=start.st_size,
            compressedDeterministically=row['compress']))
    for row in selected:archive_selected(row)
    for name,expected in sorted(p['sourceFiles'].items()):
        relative(name);need(Path(name).suffix.lower() in TEXT_SUFFIXES
             and not any(part.casefold() in FORBIDDEN_PARTS for part in Path(name).parts),
             'nontext/private frozen executable source dependency')
        raw=git(repo,'show',q+':'+name)
        need(b'\0' not in raw and sha(raw)==expected,'frozen original Git source SHA differs')
        current=repo/name;working_hash=file_sha(current) if current.is_file() and not current.is_symlink() else None
        need(c.get('requireWorkingSourceMatch',True) is False or working_hash==expected,'working source changed; never substitute it for fixed Qe2')
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
    summary=dict(schema='aijade.ch7.real-nested-engineering-summary.v1',
        status='COMPLETE_REAL_NESTED_ENGINEERING_ENVELOPE_ACCEPTED_NOT_QUALIFIED' if accepted else 'REFUSED_REAL_NESTED_ENGINEERING_ATTEMPT',
        sourceCommit=q,passportSha256=file_sha(path(c['passportPath'])),independentAuditSha256=file_sha(path(c['independentAudit'])),
        rootDispositionSha256=file_sha(path(c['rootDisposition'])),numbers=audit['numbers'],
        rawProducerStatus=run_receipt.get('status') if run_receipt else None,
        rawProducerErrors=run_receipt.get('errors') if run_receipt else None,
        enclosingParentStatus=terminal['status'],enclosingParentExitCode=terminal['controllerExitCode'],
        engineeringEnvelopeAccepted=accepted,
        scope={**{key:False for key in FALSE_SCOPE},'freshHeldoutCases':0,'table7_3':'NOT_RUN',
            'runDirectoryExists':before['exists'],'actualTerminalParentWaitKnown':True,
            'fullIndependentEngineeringAuditAccepted':accepted,'partialRefusalIsNotCompleteEngineeringPass':not accepted},
        numericPolicy='Complete audit numbers copied with exact scalar/container types; unknown/missing fields are never zero-filled.',
        oldP4RefusalSummarySha256=OLD_P4_SHA,originalProducerPendingFieldsModified=False,
        reviewStatus='ROOT_PACKET_REVIEW_REQUIRED_BEFORE_PUBLICATION',
        interpretation='Finite engineering prefix/topology evidence only. No backend/hardware/human/author/seed/heldout qualification or 4800-second worst-case certificate.')
    new(packet/'summary.json',encoded(summary))
    new(packet/'metadata/run-directory-state.json',encoded(dict(schema='aijade.ch7.original-run-directory-state.v1',originalRoot=str(run_root),**before)))
    new(packet/'metadata/source-map.json',encoded(dict(schema='aijade.ch7.real-nested-source-map.v1',originalSources=mapping)))
    new(packet/'metadata/frozen-source-proofs.json',encoded(dict(schema='aijade.ch7.frozen-source-proofs.v1',
        sourceCommit=q,sourceFiles=p['sourceFiles'],observerSources=p['observerSources'],sources=proofs,
        originalGitSourceSelected=True,currentHeadUsedAsSource=False,privateBinaryBodiesIncluded=False)))
    new(packet/'README.md',encoded(dict(description='Original full or partial real nested engineering record.',
        outcomeKind=kind,originalPendingFieldsPreserved=True,nonemptyJsonl='deterministic gzip mtime0',
        sdkModelAssetOrAuthBodiesIncluded=False,scientificQualification=False)))
    rows=[]
    for f in sorted(packet.rglob('*')):
        if not f.is_file():continue
        name=f.relative_to(packet).as_posix();row=dict(path=name,sha256=file_sha(f),sizeBytes=f.stat().st_size)
        match=next((m for m in mapping if m['packetPath']==name),None)
        if match:
            row.update(logicalPath=match['logicalPacketPath'],logicalSha256=match['originalSha256'],
                logicalSizeBytes=match['originalSizeBytes'],compressedDeterministically=match['compressedDeterministically'])
        rows.append(row)
    manifest=dict(schema='aijade.ch7.real-nested-packet-manifest.v1',sourceCommit=q,
        passportSha256=summary['passportSha256'],outcomeKind=kind,
        independentAuditSha256=summary['independentAuditSha256'],rootDispositionSha256=summary['rootDispositionSha256'],files=rows)
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
