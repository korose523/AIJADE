#!/usr/bin/env python3
"""Three destructive changes in disposable copies must be rejected; original packet remains byte-identical."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def run(root, repo):
    before={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in root.rglob('*') if f.is_file()}
    outcomes=[]
    for name in ['missing-case','changed-raw-hash','revoked-positive-reuse']:
        with tempfile.TemporaryDirectory(prefix='aijade-ch7-rejection-') as temp:
            copy=Path(temp)/'copy';shutil.copytree(root,copy)
            file=copy/'attempts/development-02/cases.json'
            cases=json.loads(file.read_text())
            if name=='missing-case':
                cases.pop();file.write_text(json.dumps(cases)+'\n')
            elif name=='revoked-positive-reuse':
                row=next(c for c in cases if c['caseId']=='I7');row['round2']['executed']=True
                file.write_text(json.dumps(cases)+'\n')
            else:
                raw=copy/'attempts/development-02/client/aijade-render-state.jsonl.gz'
                raw.write_bytes(raw.read_bytes()+b'changed')
            if name!='changed-raw-hash':
                # A freshly regenerated manifest must not conceal a contradictory/incomplete case ledger.
                manifest=json.loads((copy/'manifest.json').read_text())
                for row in manifest['files']:
                    if row['path']==str(file.relative_to(copy)):
                        data=file.read_bytes();row.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
                (copy/'manifest.json').write_text(json.dumps(manifest)+'\n')
            result=subprocess.run([sys.executable,str(copy/'verify_archive.py'),'--root',str(copy),'--repo',str(repo)],capture_output=True,text=True)
            if result.returncode==0:raise AssertionError('Archive verifier accepted '+name)
            outcomes.append(dict(case=name,rejected=True,reason=result.stderr.strip()))
    after={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in root.rglob('*') if f.is_file()}
    assert before==after
    return dict(status='PASS',rejected=len(outcomes),originalUnchanged=True,cases=outcomes)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--repo',type=Path,required=True)
    a=parser.parse_args();print(json.dumps(run(a.root,a.repo),indent=2))
