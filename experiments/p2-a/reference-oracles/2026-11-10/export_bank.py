"""Keep proposed task statements separate from mechanically prepared reference expectations."""
import argparse
import gzip
import json
from pathlib import Path

from oracle_core import canonical, digest_file, js_value, read_problems

HERE=Path(__file__).resolve().parent


def main(args):
    summary=json.loads(args.summary.read_text())
    ready={r['taskId'] for r in summary['ledger'] if r['readyAmongStaticDirect']}
    assert not args.out.exists();args.out.mkdir(parents=True)
    statements=[]
    for dataset,p in read_problems(HERE/'inputs'):
        if p['task_id'] in ready:
            statements.append({'taskId':p['task_id'],'dataset':dataset,'originalPythonPrompt':p['prompt'],
                               'entryPoint':p['entry_point'],'scope':'Statement source only; JavaScript translation and semantic test audit still required.'})
    assert len(statements)==len(ready)
    with gzip.open(args.out/'statements-only.json.gz','wt',encoding='utf-8') as stream:
        stream.write(canonical(statements)+'\n')
    counts={key:0 for key in ready}
    with gzip.open(args.folder/'pass-1/rows.jsonl.gz','rt',encoding='utf-8') as source,gzip.open(args.out/'oracle-only.jsonl.gz','wt',encoding='utf-8') as dest:
        for line in source:
            row=json.loads(line)
            if row['kind']=='case' and row['taskId'] in ready:
                assert row['status']=='OK'
                dest.write(canonical({'taskId':row['taskId'],'partition':row['partition'],'index':row['index'],
                                      'args':js_value(row['input']),'expected':js_value(row['output'])})+'\n')
                counts[row['taskId']]+=1
    for row in summary['ledger']:
        if row['taskId'] in ready:assert counts[row['taskId']]==row['passes']['1']['expectedCases']
    report={'tasks':len(ready),'cases':sum(counts.values()),'taskCaseCounts':dict(sorted(counts.items())),
            'summarySha256':digest_file(args.summary),
            'artifactSha256':{n:digest_file(args.out/n) for n in ['statements-only.json.gz','oracle-only.jsonl.gz']},
            'scope':'Mechanically prepared subset of old direct classes; not final eligibility, a JavaScript port, semantic certification or a model-facing test-result channel.'}
    (args.out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'tasks':report['tasks'],'cases':report['cases']}))


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('folder',type=Path);p.add_argument('--summary',type=Path,required=True);p.add_argument('--out',type=Path,required=True);main(p.parse_args())
