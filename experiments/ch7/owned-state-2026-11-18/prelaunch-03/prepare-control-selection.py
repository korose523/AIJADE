"""Freeze actual local controls and explicit public prelaunch payload selection.

Component inputs are not a live qualification. This script only indexes actual
existing files; it refuses missing receipts and never creates passed results.
"""
from pathlib import Path
import hashlib,json
C=Path(__file__).resolve().parent
B=Path('/Volumes/Untitled/AIJADE')
def row(path,name):
 raw=path.read_bytes()
 assert path.is_file() and not path.is_symlink() and len(raw)<=32*1024**2
 return dict(path=str(path),name=name,sha256=hashlib.sha256(raw).hexdigest())
files=[];categories={k:[] for k in ['cursorControls','pairedBootstrapProbe','launcherControls','retainedHistory']}
for directory in ['implementation','audit/e5-candidate','audit/ci-integration','launcher-history','before-method-description-correction','archive-preparation']:
 for path in sorted((C/directory).rglob('*')):
  if path.is_file() and path.suffix!='.pyc' and '__pycache__' not in path.parts:
   name='controls/'+path.relative_to(C).as_posix();files.append(row(path,name))
   category='cursorControls' if directory.startswith('audit/') else 'retainedHistory'
   if any(v.startswith('replay-') or v=='core-mutation-controls-01' for v in path.relative_to(C).parts):category='pairedBootstrapProbe'
   categories[category].append(name)
for filename in ['launcher-controls-final.json','launcher-controls-owned-final.log','launcher-controls-01.log','launcher-controls-02.log','launcher-controls-03-portable-deduplicated.log','test_nested_launcher.py','test_owned_launcher_adverse.py','testdata/nested-engineering-protocol.fixture.json','static_chain_bound.py','static-chain-bound.json','static-chain-bound.log','binary-application.json','audit-application.json','ci-python-version-decision.json','source-precommit-review.json','prelaunch-method-description-correction.json','source-freeze-qe4.json','source-qe4-publication.json','source-qe4-ci.json','source-qe4-ci-full.log','collect-superseded-source-ci.py','ci-receipt-location-preparation-01.json']:
 name='controls/'+filename;files.append(row(C/filename,name));categories['launcherControls' if ('launcher' in filename or filename.startswith('testdata/')) else 'retainedHistory'].append(name)
assert all(categories.values()) and len({v['path'] for v in files})==len(files)==len({v['name'] for v in files})
out=dict(schema='aijade.ch7.actual-engineering-control-evidence-map.v1',files=files,categories=categories,
 scope='Complete current local component sources/results and rejected development inputs retained. Generated synthetic binary bulk is not published; its generators, actual input hashes, complete read/counter records and timings are. No live acceptance.')
with (C/'control-evidence-map.json').open('x') as f:json.dump(out,f,indent=2);f.write('\n')
selection=[dict(path=v['path'],name=v['name']) for v in files]
for name in ['engineering-03-passport.json','source-qe5-ci.json','source-qe5-ci-full.log','complete-source-ci.py','source-qe5-publication.json','source-freeze-qe5.json','control-evidence-map.json','prelaunch-artifacts.json','prepare-control-selection.py','prepare-engineering-passport.py','publish-engineering-freeze.py','verify-qe5-publication.py']:
 selection.append(dict(path=str(C/name),name=name))
selection.append(dict(path=str(B/'.runtime/run-local.sh'),name='runtime/run-local.sh'))
assert len({v['path'] for v in selection})==len(selection)==len({v['name'] for v in selection})
with (C/'prelaunch-artifacts.json').open('x') as f:json.dump(dict(schema='aijade.ch7.explicit-prelaunch-artifact-selection.v1',files=selection),f,indent=2);f.write('\n')
print(json.dumps(dict(status='ACTUAL_CONTROL_MAP_AND_PRELAUNCH_SELECTION_FROZEN_NO_WINDOW',controlFiles=len(files),selectedPayload=len(selection))))
