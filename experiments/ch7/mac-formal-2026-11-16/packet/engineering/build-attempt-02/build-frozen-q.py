from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,subprocess,xml.etree.ElementTree as ET
C=Path(__file__).resolve().parent;W=C.parent/'worktree';DOTNET=Path('/Users/mac/.dotnet/dotnet');ART=W/'.runtime/build-artifacts'
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=W,text=True).strip()
assert subprocess.check_output(['git','status','--porcelain'],cwd=W,text=True)==''
env={k:v for k,v in os.environ.items() if not k.startswith('AIJADE_CH7_') and not k.startswith('AIJADE_E2E')}
env.update(AIJADE_GIT_COMMIT=head,AIJADE_TEST_DATABASE_URL='postgres://aijade:aijade@127.0.0.1:55432/aijade',AIJADE_ARTIFACTS=str(ART),AIJADE_CH7_FINITE_BANK_CONTROL=str(C/'candidate-bank-control.json'))
env.pop('REDIS_URL',None)
args=[str(DOTNET),'test','--configuration','Release','--logger','trx','--results-directory',str(C/'default-regression'),'--disable-build-servers']
with (C/'default-regression.log').open('x') as log:r=subprocess.run(args,cwd=W,env=env,stdout=log,stderr=subprocess.STDOUT)
steps=[dict(step='complete-default-regression-clean-Q',exitCode=r.returncode,command=args)]
assert r.returncode==0,r.returncode
assert subprocess.check_output(['git','status','--porcelain'],cwd=W,text=True)==''
dlls=[p for p in ART.rglob('Aijade.Tests.dll') if p.with_suffix('.runtimeconfig.json').is_file()];assert len(dlls)==1,dlls;dll=dlls[0]
metadata=list(ART.rglob('Aijade.Tests.AssemblyInfo.cs'));assert len(metadata)==1
text=metadata[0].read_text();version=re.search(r'AssemblyInformationalVersionAttribute\("([^"\n]+)"\)',text).group(1)
assert version=='0.1.0+'+head and version.encode() in dll.read_bytes()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
trx=[]
for path in sorted((C/'default-regression').glob('*.trx')):
 root=ET.fromstring(path.read_bytes());ns={'t':'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'};results=root.findall('.//t:UnitTestResult',ns);counts={}
 for item in results:counts[item.attrib['outcome']]=counts.get(item.attrib['outcome'],0)+1
 counter=root.find('.//t:Counters',ns)
 trx.append(dict(file=path.name,sha256=sha(path),individualOutcomes=counts,rawCounters=counter.attrib if counter is not None else None))
frozen=dict(status='CLEAN_COMMITTED_BUILD_FROZEN_BEFORE_QUALIFICATION',commit=head,checkedAt=datetime.now(timezone.utc).isoformat(),assemblyInformationalVersion=version,assemblyInfo=text,assemblyPath=str(dll),files={str(p.relative_to(dll.parent)):sha(p) for p in sorted(dll.parent.rglob('*')) if p.is_file()},steps=steps,artifactsRoot=str(ART),protectedSourceFiles=331,independentHumanReview=False,formalHardwareQualification=False,trx=trx)
(C/'frozen-build.json').write_text(json.dumps(frozen,indent=2)+'\n')
(C/'build-regression-status.json').write_text(json.dumps(dict(status='CLEAN_COMMITTED_BUILD_AND_COMPLETE_DEFAULT_REGRESSION_PASS',commit=head,assemblyPath=str(dll),dependencyFiles=len(frozen['files']),steps=steps,trx=trx),indent=2)+'\n')
print(json.dumps(dict(status='CLEAN_BUILD_AND_DEFAULT_REGRESSION_PASS',commit=head,assembly=str(dll),dependencyFiles=len(frozen['files']),trx=trx)))
