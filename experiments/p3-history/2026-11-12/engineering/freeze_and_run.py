from pathlib import Path
import datetime as dt,hashlib,json,os,subprocess,sys
C=Path(__file__).resolve().parent;W=Path('/Users/mac/.cache/aijade-ch7-qualification-20261112/worktree');E=W/'experiments/p3-history/2026-11-12'
def sha(p):return hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=W,text=True).strip()
assert subprocess.check_output(['git','status','--porcelain'],cwd=W,text=True)==''
build=json.loads((C/('build-'+commit[:7]+'.json')).read_text());assert len(build['steps'])==2 and all(x['exitCode']==0 for x in build['steps'])
qual=json.loads((C/('qualification-audit-'+commit[:7]+'.json')).read_text());assert qual['status']=='SYNTHETIC_RAW_RECONSTRUCTION_PASS' and qual['rows']==15
protected=json.loads((W/'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json').read_text())
for row in protected['files']:assert sha(W/row['path'])==row['sha256']
assembly=W/'tests/Aijade.Tests/obj/Release/net10.0/Aijade.Tests.AssemblyInfo.cs';assert '0.1.0+'+commit in assembly.read_text()
sources=[p for p in E.glob('*') if p.is_file()]+[W/'tests/Aijade.Tests/HistoryRecordingSupport.cs',W/'tests/Aijade.Tests/ProductHistoryRecordingTests.cs']
frozen=dict(status='CLEAN_COMMITTED_QUALIFIED_BUILD_FROZEN_BEFORE_ADMISSION',commit=commit,checkedAt=dt.datetime.now(dt.timezone.utc).isoformat(),
 planCommit=subprocess.check_output(['git','rev-parse','4acf473'],cwd=W,text=True).strip(),planSha256=sha(W/'experiments/plans/2026-11-12-p3-history-question-recording.md'),
 assemblyInfoText=assembly.read_text(),assemblyInfoSha256=sha(assembly),binaries={p.name:sha(p) for p in (W/'tests/Aijade.Tests/bin/Release/net10.0').glob('*.dll')},
 earlierProtectedSources=len(protected['files']),sources={str(p.relative_to(W)):sha(p) for p in sources},
 corpusSha256=sha(Path('/Users/mac/.local/share/aijade-data/locomo10.json')),inputFrameSha256=sha(E/'input-frame.json.gz'),
 oracleSha256=sha(E/'eligibility-oracle.json.gz'),buildReceipt=build,qualificationAudit=qual,
 qualificationFiles={str(p.relative_to(C)):sha(p) for p in (C/('qualification-'+commit[:7])).rglob('*') if p.is_file()})
freeze=C/'frozen-build.json';assert not freeze.exists();freeze.write_text(json.dumps(frozen,indent=2)+'\n')
env=dict(os.environ,PATH='/Users/mac/.dotnet:'+os.environ.get('PATH',''),DOTNET_ROOT='/Users/mac/.dotnet',DOTNET_PROCESSOR_COUNT='2',
 MSBUILDDISABLENODEREUSE='1',DOTNET_CLI_USE_MSBUILD_SERVER='0',AIJADE_TEST_DATABASE_URL='postgres://aijade:aijade@127.0.0.1:55432/aijade',AIJADE_GIT_COMMIT=commit)
cmd=[sys.executable,str(E/'run.py'),'--repo',str(W),'--out',str(C/'attempt-01'),'--freeze',str(freeze),'--corpus','/Users/mac/.local/share/aijade-data/locomo10.json',
 '--dotnet','/Users/mac/.dotnet/dotnet','--docker','/Users/mac/.local/bin/docker']
with (C/'controller.log').open('x') as log:r=subprocess.run(cmd,cwd=W,env=env,stdout=log,stderr=subprocess.STDOUT)
print(json.dumps(dict(controllerExitCode=r.returncode,output=str(C/'attempt-01'))),flush=True);raise SystemExit(r.returncode)
