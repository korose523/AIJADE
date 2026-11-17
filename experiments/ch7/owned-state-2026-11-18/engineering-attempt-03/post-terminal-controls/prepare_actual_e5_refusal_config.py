"""Prepare explicit actual E5 refusal transport configuration, without archiving."""
from pathlib import Path
import ast,json
from packet_common import need,read,file_sha,new,encoded,text_source,relative,root_engineering_accepted
B=Path('/Volumes/Untitled/AIJADE');C=B/'.research/runs/ch7-owned-state-20261118';T=C/'archive-tools'
R=B/'.runtime/posix/nested-20261117/worktree';RUN=B/'.runtime/posix/runs/ch7-owned-state-20261118/engineering-03'
Q='48299b12847c11d5a629b0292ea19d57fe771cd4'

def main():
    disposition=C/'audit/root-disposition-01.json';audit=read(C/'audit/e5-independent-negative-audit-01.json');root=read(disposition)
    need(root['sourceCommit']==audit['sourceCommit']==Q and root_engineering_accepted(root) is False,'actual reviewed E5 partial outcome')
    need(root['independentAuditSha256']==file_sha(C/'audit/e5-independent-negative-audit-01.json'),'reviewed audit identity')
    artifacts=[];destinations={}
    def add(p,destination,role):
        p=text_source(p);relative(destination)
        if destination in destinations:
            need(destinations[destination]==p,'different original reused logical destination');return
        destinations[destination]=p;artifacts.append(dict(path=str(p),packetPath=destination,role=role))
    for name,destination,role in [
        ('source-qe5-publication.json','publication/source-qe5-publication.json','source-publication'),
        ('engineering-freeze-publication.json','publication/engineering-freeze-publication.json','passport-publication'),
        ('engineering-prelaunch-check.json','publication/engineering-prelaunch-check.json','launch-preflight'),
        ('source-freeze-qe5.json','publication/source-freeze-qe5.json','source-closure'),
        ('prelaunch-method-description-correction.json','history/prelaunch-method-description-correction.json','preparation-history')]:add(C/name,destination,role)
    for map_name in ('control-evidence-map.json','prelaunch-artifacts.json'):
        for row in read(C/map_name)['files']:
            p=Path(row['path'])
            if 'sha256' in row:need(file_sha(p)==row['sha256'],'retained prelaunch control source SHA changed: '+row['name'])
            add(p,'prelaunch/'+row['name'],'EXACT_SOURCE_BOUND_PRELAUNCH_CONTROL_OR_DEVELOPMENT_HISTORY')
    excluded={'engineering-03-passport.json','engineering-03-launch.json','engineering-03-launch.terminal.json',
        'engineering-03-launch.log','launch_nested_load.py','source-qe5-ci.json','ACTUAL-E5-RESULT-STATE.json'}
    for p in sorted(C.iterdir()):
        if p.is_file() and p.name not in excluded and p.suffix in ('.json','.py','.log','.md','.index'):
            add(p,'history/preparation/'+p.name,'EXACT_PREPARATION_PUBLICATION_AND_RETAINED_SUPERSEDED_HISTORY')
    core={'e5-independent-negative-audit-01.json','root-disposition-01.json','e5-writer-stability-01.json',
          'writer-closure-01.json','listener-cause-precision-correction-01.json'}
    for p in sorted((C/'audit').iterdir()):
        if p.is_file() and p.name not in core:
            add(p,'audit/retained/'+p.name,'POST_TERMINAL_ACTUAL_NEGATIVE_COLD_AUDIT_SOURCE_LOG_EXPORT_OR_ATTEMPT')
    for p in sorted((C/'diagnostics/listener-e5').glob('*')):
        if p.is_file():add(p,'audit/diagnostics/listener-e5/'+p.name,'POSTHOC_DIAGNOSTIC_NOT_UNIQUE_CAUSAL_PROOF')
    for d in ('source-before-e5','history-before-codec-v2'):
        for p in sorted((T/d).glob('*.py')):add(p,'archive-tools/'+d+'/'+p.name,'RETAINED_ARCHIVE_SOURCE_HISTORY_NOT_MEASUREMENT')
    for p in sorted((C/'archive-preparation').rglob('*')):
        if p.is_file() and p.suffix in ('.py','.json','.md','.log') and 'fixtures' not in p.parts:
            add(p,'archive-preparation/'+p.relative_to(C/'archive-preparation').as_posix(),'LOSSLESS_TRANSPORT_SOURCE_AND_ACTUAL_27_CONTROLS_NOT_ENGINEERING')
    for name in ('test_actual_e5_packet_controls.py','prepare_actual_e5_refusal_config.py','prepared-config-contract.json'):
        add(T/name,'archive-tools/'+name,'POSTHOC_ARCHIVE_PREPARATION_SOURCE_NOT_MEASUREMENT')
    for p in T.glob('*.py'):ast.parse(p.read_text(),filename=str(p),feature_version=(3,9))
    config=dict(schema='aijade.ch7.nested-archive-config.v1',repo=str(R),sourceCommit=Q,runRoot=str(RUN),
        packetRoot=str(C/'audit/engineering-03-packet'),packetReceiptPath=str(C/'audit/engineering-03-packet-preparation.json'),
        passportPath=str(C/'engineering-03-passport.json'),parentLaunchRecord=str(C/'engineering-03-launch.json'),
        parentTerminal=str(C/'engineering-03-launch.terminal.json'),parentLog=str(C/'engineering-03-launch.log'),
        launcherSource=str(C/'launch_nested_load.py'),finalCiPath=str(C/'source-qe5-ci.json'),
        independentAudit=str(C/'audit/e5-independent-negative-audit-01.json'),rootDisposition=str(disposition),
        writerStability=str(C/'audit/e5-writer-stability-01.json'),rootAdditionalWriterClosure=str(C/'audit/writer-closure-01.json'),
        causePrecisionCorrection=str(C/'audit/listener-cause-precision-correction-01.json'),
        provisionalResultState=str(C/'ACTUAL-E5-RESULT-STATE.json'),outcomeKind='partial-refusal',requireWorkingSourceMatch=True,artifacts=artifacts)
    out=T/'actual-e5-refusal-config-01.json';new(out,encoded(config))
    review=dict(schema='aijade.ch7.e5-archive-source-readiness.v1',status='ACTUAL_PARTIAL_CONFIG_READY_NO_PACKET_YET',
        configPath=str(out),configSha256=file_sha(out),artifactCount=len(artifacts),actualArchivesCreated=0,sourceCommit=Q,
        sourceFiles=[dict(path=str(p),sha256=file_sha(p)) for p in sorted(T.glob('*.py'))],
        expectedOriginalRunFiles=11,expectedFrozenGitSources=48,all174ColdDecisionsRetained=True,
        scope='Transport v2 bounded16MiB decoded single-gzip members; all logical full bytes retained. No kernel replay by portable verifier, no complete engineering/scientific acceptance.',
        causeClassification='UNRESOLVED_OR')
    new(T/'actual-e5-source-review-01.json',encoded(review));print(json.dumps(review,indent=2))
if __name__=='__main__':main()
