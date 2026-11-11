#!/usr/bin/env python3
"""Exercise complete-archive refusal on isolated links/copies, without service calls."""
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024**2),b''):h.update(block)
    return h.hexdigest()


def read(path):
    if path.suffix=='.gz':
        with gzip.open(path,'rt') as f:return json.load(f)
    return json.loads(path.read_text())


def replace_json(path,value):
    # Every original is linked read-only by convention. Break the link before writing.
    path.unlink()
    if path.suffix=='.gz':
        with path.open('xb') as raw:
            with gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as f:
                f.write((json.dumps(value,ensure_ascii=False)+'\n').encode())
    else:path.write_text(json.dumps(value,indent=2)+'\n')


def main(root,out):
    root=root.resolve();assert root not in out.resolve().parents and out.resolve()!=root
    assert not out.exists(),'Preserve an existing refusal report.'
    spec=importlib.util.spec_from_file_location('longmem_archive',root/'verify_archive.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    positive=module.verify(root)
    manifest_sha=sha(root/'manifest.json');checks=[]
    mutations=[('primary-denominator','results/product-summary.json'),
               ('unknown-attribution-flag','results/product/question-000-captures.json.gz'),
               ('missing-final-request','results/product/question-499-raw-boundaries.jsonl.gz')]
    original_hashes={rel:sha(root/rel) for _,rel in mutations}
    for name,rel in mutations:
        with tempfile.TemporaryDirectory(prefix='aijade-lme-refusal-') as folder:
            clone=Path(folder)
            for p in root.rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts:
                    dst=clone/p.relative_to(root);dst.parent.mkdir(parents=True,exist_ok=True);dst.symlink_to(p)
            target=clone/rel
            if name=='missing-final-request':target.unlink()
            else:
                value=read(target)
                if name=='primary-denominator':value['primaryQuestions']=471
                else:value[0]['attributable']=not value[0]['attributable']
                replace_json(target,value)
                manifest=read(clone/'manifest.json')
                row=next(r for r in manifest['files'] if r['path']==rel)
                row.update(bytes=target.stat().st_size,sha256=sha(target))
                replace_json(clone/'manifest.json',manifest)
            try:module.verify(clone)
            except AssertionError as error:
                checks.append(dict(case=name,rejected=True,errorType=type(error).__name__,
                                   manifestRegenerated=name!='missing-final-request'))
            else:raise AssertionError('A malformed complete archive was accepted: '+name)
        assert sha(root/'manifest.json')==manifest_sha and sha(root/rel)==original_hashes[rel]
    result=dict(status='PASS',positiveArchiveCheck=positive,rejectionCases=checks,
                testedStageManifestSha256=manifest_sha,originalFilesUnchanged=True,
                newServiceCalls=0,newModelCalls=0,
                scope='Missing capture, wrong primary denominator and contradictory unknown flag; not an adversarial-forgery proof or scientific approval.')
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();main(args.root,args.out)
