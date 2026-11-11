"""Verify published artifacts and recompute P2-A case counts without executing ports."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

from prepare import HERE, REFERENCE, digest_file, read_problems

ROOT=HERE.parents[3]
RESULTS=HERE/'results'


def rows(path):
    opener=gzip.open if str(path).endswith('.gz') else open
    with opener(path,'rt',encoding='utf-8') as stream:
        for line in stream:
            yield json.loads(line)


def verify(expected_summary):
    receipt=json.loads((RESULTS/'receipt.json').read_text())
    assert receipt['schema']=='aijade.p2a.javascript-port.receipt.v1'
    if expected_summary is not None:
        assert digest_file(RESULTS/'summary.json')==expected_summary,'Unexpected summary identity'
    for name,digest in receipt['artifactSha256'].items():
        path=(HERE/name).resolve()
        assert path.is_relative_to(HERE) and digest_file(path)==digest,name
    report=json.loads((RESULTS/'summary.json').read_text())
    assert report['executionCodeCommit']==receipt['executionCodeCommit']
    lock=json.loads((HERE/'input-lock.json').read_text())
    for label in ['release','variants']:
        folder=RESULTS/label
        execution=json.loads((folder/'execution.json').read_text())
        assert execution['final'] and execution['newModelCalls']==0
        assert execution['executionCodeCommit']==report['executionCodeCommit']
        for key in ['packSha256','portsSha256']:
            assert execution[key]==lock[execution['population']][key]
        for name,expected in execution['sourceSha256'].items():
            path=(HERE/name).resolve()
            source=subprocess.check_output(['git','show',execution['executionCodeCommit']+':'+str(path.relative_to(ROOT))],cwd=ROOT)
            assert hashlib.sha256(source).hexdigest()==expected,name
        for name,expected in execution['artifactSha256'].items():
            assert digest_file(folder/name)==expected,name
    prior=json.loads((REFERENCE/'summary.json').read_text())
    direct={r['taskId'] for r in prior['ledger'] if r['staticClass']=='direct'}
    prior_blocked={r['taskId'] for r in prior['ledger'] if r['taskId'] in direct and not r['readyAmongStaticDirect']}
    expected={(p['task_id'],part,i) for _,p in read_problems(REFERENCE/'inputs') if p['task_id'] in direct
              for part in ['base','plus'] for i in range(len(p[part+'_input']))}
    counts=defaultdict(Counter)
    for row in rows(RESULTS/'release/cases.jsonl.gz'):
        key=(row['taskId'],*row['case'])
        expected.remove(key)
        counts[row['taskId']][row['outcome']]+=1
    assert not expected and set(counts)==direct
    assert dict(sum(counts.values(),Counter()))==report['released']['caseCounts']
    assert sum(sum(c.values())==c['PASS'] for c in counts.values())==report['released']['completeAgreement']
    variant_rows=list(rows(RESULTS/'variants/cases.jsonl.gz'))
    assert len({(r['taskId'],*r['case']) for r in variant_rows})==len(variant_rows)==report['exactVariants']['cases']
    assert Counter(r['outcome'] for r in variant_rows)==report['exactVariants']['caseCounts']
    dispositions=list(rows(RESULTS/'blocked-tasks.jsonl'))
    assert len(dispositions)==52 and {r['taskId'] for r in dispositions}==prior_blocked
    assert Counter(r['disposition'] for r in dispositions)==report['previouslyBlocked']['dispositions']
    seen=set()
    semantic_counts=defaultdict(Counter)
    for row in rows(RESULTS/'semantic/semantic-cases.jsonl.gz'):
        key=(row['taskId'],*row['case'])
        assert key not in seen
        seen.add(key)
        semantic_counts[row['taskId']][row['status']]+=1
    for task in dispositions:
        assert dict(semantic_counts[task['taskId']])==task['semanticCounts']
    assert dict(sum(semantic_counts.values(),Counter()))==report['previouslyBlocked']['semanticCases']
    for task in json.loads((RESULTS/'recovery/summary.json').read_text())['tasks'].values():
        for p in task['passes']:
            assert digest_file(RESULTS/'recovery'/p['path'])==p['streamSha256']
    extra=report['additionalStatementCheck']
    nested=RESULTS/'clarified-132'
    assert digest_file(nested/'HumanEval-132.js')==extra['portSha256']
    assert Counter(r['outcome'] for r in rows(nested/'cases.jsonl.gz'))=={'PASS':extra['targetedAgreement']}
    assert json.loads((nested/'statement-check.json').read_text())['disagreementCount']==extra['subsequenceConflicts']
    assert json.loads((RESULTS/'reproduction.json').read_text())['locks']==lock
    return {'status':'PASS','artifactFiles':len(receipt['artifactSha256']),'tasks':len(counts),
            'releasedCases':report['released']['plannedCases'],'variantCases':len(variant_rows),
            'blockedTaskDispositions':len(dispositions),'semanticCases':len(seen),'frozenExecutionCommit':report['executionCodeCommit']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--expected-summary-sha');args=parser.parse_args()
    print(json.dumps(verify(args.expected_summary_sha),indent=2))
