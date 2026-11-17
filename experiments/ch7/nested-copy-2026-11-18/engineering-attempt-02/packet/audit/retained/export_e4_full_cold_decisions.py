"""Second independent original-guard cold pass; export actual full decisions."""
from pathlib import Path
import hashlib,json,sys,time
B=Path('/Volumes/Untitled/AIJADE');C=B/'.research/runs/ch7-nested-copy-20261118';R=B/'.runtime/posix/nested-20261117/worktree'
RUN=B/'.runtime/posix/runs/ch7-nested-copy-20261118/engineering-02'
sys.path.insert(0,str(R/'experiments/ch7'))
import lifecycle_audit as oracle
import mac_process_guard_v3 as guard
import process_lifecycle as parser
import audit_nested_load as helpers

def sha(raw):return hashlib.sha256(raw).hexdigest()
def main():
 p=helpers.read(C/'engineering-02-passport.json');a=helpers.read(C/'audit/e4-independent-negative-audit-01.json')
 for m in (oracle,guard,parser,helpers):helpers.verify_loaded_module(m,R,p['sourceFiles'])
 paths=[RUN/'settling/telemetry.jsonl',RUN/'process-policy.json',RUN/'lifecycle-journal.jsonl']
 before={str(f):helpers.file_sha(f) for f in paths}
 for f in paths:helpers.need(before[str(f)]==a['inputFiles'][f.relative_to(RUN).as_posix()]['sha256'],'original audit/source bytes differ')
 rows=helpers.jsonl(paths[0]);policy=helpers.read(paths[1]);journal=paths[2].read_bytes()
 helpers.need(len(rows)==153,'actual full original population')
 out=C/'audit/e4-full-cold-decisions-01.jsonl';started=time.monotonic()
 with out.open('xb') as stream:
  for n,row in enumerate(rows):
   decision=oracle._validate_sample(row,policy,journal)
   helpers.need(decision['status']=='PASS' and decision['blockers']==[],'actual original cold decision adverse')
   record=dict(schema='aijade.ch7.actual-full-cold-decision.v1',sourceCommit=p['sourceCommit'],globalIndex=n,
    sampleId=row['sampleId'],originalTelemetrySha256=before[str(paths[0])],
    originalPrefixBytes=row['processObservation']['lifecycle']['journalBytes'],
    originalPrefixSha256=row['processObservation']['lifecycle']['journalSha256'],
    actualFullTypedDecision=decision,method='SECOND_ACTUAL_ORIGINAL_GUARD_COMPLETE_COLD_REPLAY_NO_CACHED_STATUS_RECONSTRUCTION')
   stream.write(helpers.canonical(record)+b'\n');stream.flush()
   if (n+1)%25==0 or n==152:print(json.dumps(dict(stage='EXPORTED_ACTUAL_FULL_COLD_DECISIONS',records=n+1,total=153,seconds=time.monotonic()-started)),flush=True)
 helpers.need(all(helpers.file_sha(f)==before[str(f)] for f in paths),'original input changed during export')
 receipt=dict(schema='aijade.ch7.actual-full-cold-decision-export.v1',status='ALL_153_ORIGINAL_COMPLETE_TYPED_COLD_DECISIONS_EXPORTED',
  sourceCommit=p['sourceCommit'],auditSha256=helpers.file_sha(C/'audit/e4-independent-negative-audit-01.json'),
  output=str(out),outputSha256=helpers.file_sha(out),records=153,inputSha256=before,
  originalGuardSha256=helpers.file_sha(guard.__file__),parserSha256=helpers.file_sha(parser.__file__),
  exportSourceSha256=helpers.file_sha(__file__),secondIndependentColdPass=True,originalInputUnchanged=True,
  noLiveObserverOrModel=True,engineeringRefusalChanged=False,backendQualified=False,seedConstructed=False)
 target=C/'audit/e4-full-cold-decisions-01.json';target.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt),flush=True)
if __name__=='__main__':main()
