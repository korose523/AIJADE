from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,subprocess,sys
C=Path(__file__).resolve().parent;W=C/'worktree';DOTNET=Path('/Users/mac/.dotnet/dotnet');ART=W/'.runtime'/'build-artifacts'
source=json.loads((C/'execution-source-publication.json').read_text());head=source['commit']
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=W,text=True).strip()==head
assert subprocess.check_output(['git','status','--porcelain'],cwd=W,text=True)==''
env=dict(os.environ,**json.loads((C/'service-environment.json').read_text()),AIJADE_GIT_COMMIT=head,
    AIJADE_TEST_DATABASE_URL='postgres://aijade:aijade@127.0.0.1:55432/aijade')
env.pop('REDIS_URL',None)
env['AIJADE_ARTIFACTS']=str(ART)
steps=[]
for name,args in [('clean-default-env-corrected-source',[str(DOTNET),'clean','--configuration','Release','--disable-build-servers']),
                  ('complete-default-env-corrected-regression',[str(DOTNET),'test','--configuration','Release','--logger','trx','--results-directory',str(C/'default-env-corrected-regression'),'--disable-build-servers'])]:
    with (C/(name+'.log')).open('x') as log:r=subprocess.run(args,cwd=W,env=env,stdout=log,stderr=subprocess.STDOUT)
    steps.append(dict(step=name,exitCode=r.returncode,command=args));assert r.returncode==0,(name,r.returncode)
assert subprocess.check_output(['git','status','--porcelain'],cwd=W,text=True)==''
dlls=[p for p in ART.rglob('Aijade.Tests.dll') if p.with_suffix('.runtimeconfig.json').is_file()];assert len(dlls)==1,dlls;dll=dlls[0]
metadata=list(ART.rglob('Aijade.Tests.AssemblyInfo.cs'));assert len(metadata)==1
text=metadata[0].read_text();version=re.search(r'AssemblyInformationalVersionAttribute\("([^"\n]+)"\)',text).group(1)
assert version=='0.1.0+'+head and version.encode() in dll.read_bytes()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
frozen=dict(status='CLEAN_COMMITTED_BUILD_FROZEN_BEFORE_QUALIFICATION',commit=head,checkedAt=datetime.now(timezone.utc).isoformat(),
    assemblyInformationalVersion=version,assemblyInfo=text,assemblyPath=str(dll),
    files={str(p.relative_to(dll.parent)):sha(p) for p in sorted(dll.parent.rglob('*')) if p.is_file()},
    steps=steps,artifactsRoot=str(ART),protectedSourceFiles=331,independentHumanReview=False,formalHardwareQualification=False)
(C/'frozen-build.json').write_text(json.dumps(frozen,indent=2)+'\n')
(C/'build-regression-status.json').write_text(json.dumps(dict(status='CLEAN_COMMITTED_BUILD_AND_COMPLETE_DEFAULT_REGRESSION_PASS',commit=head,assemblyPath=str(dll),dependencyFiles=len(frozen['files']),steps=steps),indent=2)+'\n')
print(json.dumps(dict(status='CLEAN_BUILD_AND_DEFAULT_REGRESSION_PASS',commit=head,assembly=str(dll),dependencyFiles=len(frozen['files']))))
