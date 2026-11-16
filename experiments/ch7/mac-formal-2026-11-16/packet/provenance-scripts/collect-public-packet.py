from pathlib import Path
import gzip,hashlib,json,shutil
B=Path('/Volumes/Untitled/AIJADE');C=Path(__file__).resolve().parent;W=C/'worktree';D=C/'staging/packet';R=B/'.runtime/posix/runs/ch7-mac-formal-20261116/qualification-01';assert not D.exists();D.mkdir()
def copy(source,relative,compress=False):
 source=Path(source);dest=D/relative;dest.parent.mkdir(parents=True,exist_ok=True);assert source.is_file() and not source.is_symlink() and not dest.exists()
 raw=source.read_bytes();dest.write_bytes(gzip.compress(raw,mtime=0) if compress else raw)
copy(W/'experiments/plans/2026-11-16-ch7-mac-formal-backend.md','plan.md')
copy(C/'build-attempt-02/frozen-build.json','frozen-build.json')
for source,dest in [('qualification-single-launch.json','launch.json'),('qualification-single-launch.terminal.json','terminal.json'),('plan-publication.json','plan.json'),('implementation-final-publication.json','implementation.json'),('binary-freeze-publication.json','binary-freeze.json'),('qualification-fixed-launch.json','fixed-launch-config.json'),('execution-source-ci-final.json','source-ci.json'),('research-plan-publication.json','research-plan.json')]:copy(C/source,'publication/'+dest)
for path in sorted(R.rglob('*')):
 if path.is_file():
  rel=str(path.relative_to(R));compress=rel.endswith('.jsonl');copy(path,'qualification/'+rel+('.gz' if compress else ''),compress)
(D/'qualification/admission').mkdir(exist_ok=True)
for p in sorted((C/'qualification-inputs-fe0fa07').iterdir()):copy(p,'qualification-inputs/'+p.name)
for p in sorted((C/'build-attempt-02').rglob('*')):
 if p.is_file() and p.name!='frozen-build.json':copy(p,'engineering/build-attempt-02/'+str(p.relative_to(C/'build-attempt-02'))+('.gz' if p.suffix=='.trx' else ''),p.suffix=='.trx')
for p in sorted((C/'default-regression').glob('*.trx')):copy(p,'engineering/build-attempt-01/'+p.name+'.gz',True)
for name in ['default-regression.log','frozen-build.json','build-regression-status.json','candidate-bank-control.json','build-attempt-01-not-used.json']:
 if (C/name).is_file():copy(C/name,'engineering/build-attempt-01/'+name)
for name in ['python-controls-source-bound.log','python-controls-source-bound.json','python-controls-source-bound-portable.log','python-controls-source-bound-portable.json','q-ci-failed.log','q-ci-final-snapshot.json','test-portability-fix.json','mac-formal-runtime-controls-portability-fix.log','default-required-controls-final.json','protected-source-final.json','prepared-renderer-final-verification.json','known-launch-assets-preflight.json','runtime-preconditions-readonly.json','runtime-preconditions-readonly.md','real-owned-database-control.json','preflight-database-lease.jsonl','observer-engineering-real.json','observer-engineering-real-controller.log','mac-process-guard-completion.json','sequence-audit-engineering-receipt.json','runtime-engineering-completion.json']:
 if (C/name).is_file():copy(C/name,'engineering/'+name+('.gz' if name.endswith('.jsonl') else ''),name.endswith('.jsonl'))
for p in sorted(C.glob('*controls*.log')):
 if not (D/'engineering'/p.name).exists():copy(p,'engineering/'+p.name)
for name in ['final-controls.py','final-controls-portable.py','build-frozen-q.py','prepare-known-launch.py','create-known-config.py','collect-public-packet.py','verify-service-lifecycle.py','check-observer-engineering-real.py']:
 copy(C/name,'provenance-scripts/'+name)
print(json.dumps(dict(status='PUBLIC_PACKET_COLLECTED_PENDING_INDEPENDENT_AUDIT',files=sum(p.is_file() for p in D.rglob('*')),bytes=sum(p.stat().st_size for p in D.rglob('*') if p.is_file()),root=str(D))))
