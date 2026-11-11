from pathlib import Path
import json,os,subprocess,datetime as dt,ast
C=Path(__file__).resolve().parent
W=Path('/Users/mac/.cache/aijade-ch7-qualification-20261112/worktree')
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=W,text=True).strip()
assert subprocess.check_output(['git','status','--porcelain'],cwd=W,text=True)==''
for p in (W/'experiments/p3-history/2026-11-12').glob('*.py'):ast.parse(p.read_text())
env=dict(os.environ,PATH='/Users/mac/.dotnet:'+os.environ.get('PATH',''),DOTNET_ROOT='/Users/mac/.dotnet',
 DOTNET_PROCESSOR_COUNT='2',MSBUILDDISABLENODEREUSE='1',DOTNET_CLI_USE_MSBUILD_SERVER='0',
 AIJADE_TEST_DATABASE_URL='postgres://aijade:aijade@127.0.0.1:55432/aijade',AIJADE_GIT_COMMIT=commit,
 AIJADE_P3_HISTORY_QUAL_OUT=str(C/('qualification-'+commit[:7])))
env.pop('AIJADE_P3_HISTORY_OUT',None)
records=[]
for name,cmd in [('clean',['/Users/mac/.dotnet/dotnet','clean','--configuration','Release','-p:UseSharedCompilation=false']),
 ('tests',['/Users/mac/.dotnet/dotnet','test','--configuration','Release','-p:UseSharedCompilation=false'])]:
 p=C/('build-'+commit[:7]+'-'+name+'.log');assert not p.exists()
 print(json.dumps(dict(step=name,commit=commit)),flush=True)
 with p.open('w') as stream:r=subprocess.run(cmd,cwd=W,env=env,stdout=stream,stderr=subprocess.STDOUT)
 records.append(dict(step=name,exitCode=r.returncode,log=str(p),finishedAt=dt.datetime.now(dt.timezone.utc).isoformat()))
 (C/('build-'+commit[:7]+'.json')).write_text(json.dumps(dict(commit=commit,steps=records),indent=2)+'\n')
 if r.returncode:print(p.read_text()[-12000:],flush=True);raise SystemExit(r.returncode)
print(json.dumps(dict(status='CLEAN_BUILD_AND_FULL_REGRESSION_PASS',commit=commit)),flush=True)
