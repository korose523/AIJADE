"""Prepare an explicit reviewed post-terminal E4 config; does not archive."""
from pathlib import Path
import ast,json
from packet_common import need,read,file_sha,new,encoded,text_source,relative

B=Path('/Volumes/Untitled/AIJADE');C=B/'.research/runs/ch7-nested-copy-20261118';T=C/'archive-tools'
R=B/'.runtime/posix/nested-20261117/worktree';RUN=B/'.runtime/posix/runs/ch7-nested-copy-20261118/engineering-02'
Q='8231d8b9d67e5188787b69225a72145f2d4c5a63'


def main():
    disposition=C/'audit/root-disposition-01.json';need(disposition.is_file(),'actual independent root disposition required')
    audit=read(C/'audit/e4-independent-negative-audit-01.json');root=read(disposition)
    need(root['sourceCommit']==audit['sourceCommit']==Q and root['engineeringEnvelopeAccepted'] is False,
         'actual reviewed partial outcome required')
    need(root['independentAuditSha256']==file_sha(C/'audit/e4-independent-negative-audit-01.json'),
         'actual root reviewed audit bytes differ')
    artifacts=[];destinations=set()
    def add(p,destination,role):
        p=text_source(p);relative(destination)
        if destination in destinations:return
        destinations.add(destination);artifacts.append(dict(path=str(p),packetPath=destination,role=role))
    for p,dest,role in [
        (C/'source-qe3-publication.json','publication/source-qe3-publication.json','source-publication'),
        (C/'engineering-freeze-publication.json','publication/engineering-freeze-publication.json','passport-publication'),
        (C/'engineering-prelaunch-check.json','publication/engineering-prelaunch-check.json','launch-preflight'),
        (C/'source-freeze-qe3.json','publication/source-freeze-qe3.json','source-closure'),
        (C/'startup-budget-design-decision.json','history/startup-budget-design-decision.json','preparation-history')]:add(p,dest,role)
    control=read(C/'control-evidence-map.json')
    for row in control['files']:
        need(file_sha(Path(row['path']))==row['sha256'],'actual prelaunch control/source SHA changed: '+row['name'])
        add(Path(row['path']),'prelaunch/'+row['name'],'EXACT_SOURCE_BOUND_PRELAUNCH_CONTROL_OR_DEVELOPMENT_HISTORY')
    for row in read(C/'prelaunch-artifacts.json')['files']:
        add(Path(row['path']),'prelaunch/'+row['name'],'EXACT_ACTUAL_PRELAUNCH_ARTIFACT')
    excluded={'engineering-02-passport.json','engineering-02-launch.json','engineering-02-launch.terminal.json',
        'engineering-02-launch.log','launch_nested_load.py','source-qe3-ci.json'}
    for p in sorted(C.iterdir()):
        if p.is_file() and p.name not in excluded and p.suffix in ('.json','.py','.log','.md'):
            add(p,'history/preparation/'+p.name,'EXACT_PREPARATION_PUBLICATION_AND_RETAINED_FAILED_CONTROL_HISTORY')
    for p in sorted((C/'audit').iterdir()):
        if p.is_file() and p.name not in ('e4-independent-negative-audit-01.json','root-disposition-01.json','e4-writer-stability-01.json'):
            add(p,'audit/retained/'+p.name,'POST_TERMINAL_INDEPENDENT_AUDIT_AND_RETAINED_INCOMPLETE_EXTRA_AUDIT')
    for p in sorted((T/'source-before-e4').glob('*.py')):
        add(p,'archive-tools/source-before-e4/'+p.name,'RETAINED_ARCHIVE_SOURCE_BEFORE_E4_ADAPTATION')
    for p in [T/'test_actual_e4_packet_controls.py',T/'prepare_actual_e4_refusal_config.py',T/'prepared-config-contract.json']:
        add(p,'archive-tools/'+p.name,'POSTHOC_ARCHIVE_PREPARATION_SOURCE_NOT_MEASUREMENT')
    for p in T.glob('*.py'):ast.parse(p.read_text(),filename=str(p))
    config=dict(schema='aijade.ch7.nested-archive-config.v1',repo=str(R),sourceCommit=Q,runRoot=str(RUN),
        packetRoot=str(C/'audit/engineering-02-packet'),packetReceiptPath=str(C/'audit/engineering-02-packet-preparation.json'),
        passportPath=str(C/'engineering-02-passport.json'),parentLaunchRecord=str(C/'engineering-02-launch.json'),
        parentTerminal=str(C/'engineering-02-launch.terminal.json'),parentLog=str(C/'engineering-02-launch.log'),
        launcherSource=str(C/'launch_nested_load.py'),finalCiPath=str(C/'source-qe3-ci.json'),
        independentAudit=str(C/'audit/e4-independent-negative-audit-01.json'),rootDisposition=str(disposition),
        writerStability=str(C/'audit/e4-writer-stability-01.json'),outcomeKind='partial-refusal',requireWorkingSourceMatch=True,
        artifacts=artifacts)
    path=T/'actual-e4-refusal-config-01.json';new(path,encoded(config))
    review=dict(schema='aijade.ch7.e4-archive-source-readiness.v1',status='ACTUAL_PARTIAL_CONFIG_READY_FOR_ROOT_SOURCE_REVIEW_NO_PACKET_CREATED',
        configPath=str(path),configSha256=file_sha(path),artifactCount=len(artifacts),actualArchivesCreated=0,
        originalSourceCommit=Q,sourceFiles=[dict(path=str(p),sha256=file_sha(p)) for p in sorted(T.glob('*.py'))],
        requiredRawRunFiles='Complete original before/after inventory including11 actual files, parent initializer, empty admission and all153 raw records; no four-child initializer claimed because no child registered.',
        oldRefusalHistory='Fixed originalE3 summary+manifest and P4 summary from exactQe3 Git object, separately archived.',
        outcomeScope='Partial refusal only; no fullPASS auditor dispatch, scientific qualification or source mutation.')
    target=T/'actual-e4-source-review-01.json';new(target,encoded(review));print(json.dumps(review,indent=2))
if __name__=='__main__':main()
