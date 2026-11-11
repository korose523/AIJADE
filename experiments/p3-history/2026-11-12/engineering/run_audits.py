from pathlib import Path
import json,subprocess,sys
C=Path(__file__).resolve().parent;W=Path('/Users/mac/.cache/aijade-ch7-qualification-20261112/worktree');E=W/'experiments/p3-history/2026-11-12'
receipt=json.loads((C/'attempt-01/controller-receipt.json').read_text());assert receipt['status']=='COMPLETE'
commands=[('audit',[sys.executable,str(E/'audit.py'),'--root',str(C/'attempt-01'),'--frame',str(E/'input-frame.json.gz'),
 '--oracle',str(E/'eligibility-oracle.json.gz'),'--out',str(C/'analysis')]),
 ('rejections',[sys.executable,str(E/'test_rejections.py'),'--root',str(C/'attempt-01'),'--frame',str(E/'input-frame.json.gz'),
 '--oracle',str(E/'eligibility-oracle.json.gz'),'--out',str(C/'analysis/rejections.json')]),
 ('summary',[sys.executable,str(E/'analyze.py'),'--metrics',str(C/'analysis/metrics.jsonl.gz'),'--out',str(C/'analysis/summary.json')]),
 ('aggregation',[sys.executable,str(E/'check_aggregation.py'),'--metrics',str(C/'analysis/metrics.jsonl.gz'),'--summary',str(C/'analysis/summary.json'),'--out',str(C/'analysis/aggregation-check.json')]),
 ('extra',[sys.executable,str(C/'extra_controls.py'),'--root',str(C/'attempt-01'),'--frame',str(E/'input-frame.json.gz'),
 '--oracle',str(E/'eligibility-oracle.json.gz'),'--scripts',str(E),'--out',str(C/'extra-rejections.json')])]
steps=[]
for name,command in commands:
 out=C/(name+'-first.stdout');err=C/(name+'-first.stderr');assert not out.exists() and not err.exists()
 print(json.dumps(dict(starting=name)),flush=True)
 with out.open('w') as stdout,err.open('w') as stderr:run=subprocess.run(command,cwd=W,stdout=stdout,stderr=stderr)
 steps.append(dict(step=name,exitCode=run.returncode));(C/'audit-stage-status.json').write_text(json.dumps(steps,indent=2)+'\n')
 print(out.read_text()[-3500:],flush=True)
 if run.returncode:print(err.read_text()[-8000:],flush=True);raise SystemExit(run.returncode)
print(json.dumps(dict(status='ALL_FROZEN_AUDITS_AND_CONTROLS_PASS')),flush=True)
