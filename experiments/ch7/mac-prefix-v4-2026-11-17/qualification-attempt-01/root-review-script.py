from pathlib import Path
from datetime import datetime,timezone
import gzip,hashlib,json
C=Path(__file__).parent;P=C/'refusal-packet'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
read=lambda path:json.loads(path.read_bytes())
def typed(a,b):
    if type(a) is not type(b):return False
    if type(a) is dict:return a.keys()==b.keys() and all(typed(a[k],b[k]) for k in a)
    if type(a) is list:return len(a)==len(b) and all(typed(x,y) for x,y in zip(a,b))
    return a==b
manifest=read(P/'packet-manifest.json');logical={}
assert len(manifest['files'])==80
assert {p.relative_to(P).as_posix() for p in P.rglob('*') if p.is_file()}=={r['path'] for r in manifest['files']}|{'packet-manifest.json'}
for row in manifest['files']:
    path=P/row['path'];assert not path.is_symlink()
    data=path.read_bytes();assert sha(data)==row['sha256'] and len(data)==row['sizeBytes']
    name=row['path']
    if 'logicalSha256' in row:
        assert name.endswith('.jsonl.gz') and data[4:8]==b'\0'*4
        data=gzip.decompress(data);assert sha(data)==row['logicalSha256'] and len(data)==row['logicalSizeBytes'];name=name[:-3]
    assert name not in logical;logical[name]=data
summary=read(P/'summary.json');core=read(C/'analysis/independent-p4-terminal-audit-01.json')
assert sha(logical['audit/independent-p4-terminal-audit-01.json'])==sha((C/'analysis/independent-p4-terminal-audit-01.json').read_bytes())==summary['independentAuditSha256']
assert all(typed(summary['numbers'][k],v) for k,v in core['numbers'].items())
assert all(typed(summary['scope'][k],v) for k,v in core['scope'].items())
receipt=json.loads(logical['run/qualification-01/receipt.json'])
for name in ('settling','admission'):
    raw=json.loads(logical['run/qualification-01/'+name+'/receipt.json'])
    for suffix,key in [('Samples','samples'),('ValidatedSamples','validatedSamples'),('Seconds','elapsedSeconds')]:
        assert typed(summary['numbers'][name+suffix],raw[key])
assert typed(summary['numbers']['plannedPairs'],receipt['plannedPairs']) and receipt['plannedPairs']==10
assert summary['numbers']['plannedConditionRows']==20 and receipt['status']=='STOPPED'
assert summary['numbers']['completedConditionRows']==receipt['completedConditionRows']==0
assert summary['numbers']['unattemptedConditionRows']==len(receipt['unattemptedCaseIds'])==20
assert summary['scope']['backendQualified'] is summary['scope']['seedConstructed'] is False
assert core['phaseOnlyContinuity']['status']=='PASS'
assert core['wholeRuntimeContinuity']['status']==core['wholeLifecyclePredicate']['status']=='REFUSED'
assert core['recordedLaunchRefusal']['spawnedPid'] is None
mapping=read(P/'metadata/source-map.json')['originalSources']
assert len(mapping)==74
for row in mapping:
    actual=Path(row['originalPath']).read_bytes()
    assert sha(actual)==row['originalSha256'] and actual==logical[row['logicalPacketPath']]
result=dict(schema='aijade.ch7.root-refusal-disposition.v1',status='ROOT_AUDITED_REFUSAL_ACCEPTED_AS_NEGATIVE_RECORD_ONLY',
    checkedAt=datetime.now(timezone.utc).isoformat(),sourceCommit=summary['sourceCommit'],buildFreezeCommit=summary['buildFreezeCommit'],planCommit=summary['planCommit'],
    packetManifestSha256=sha((P/'packet-manifest.json').read_bytes()),summarySha256=sha((P/'summary.json').read_bytes()),independentAuditSha256=summary['independentAuditSha256'],
    payloadFiles=80,originalSourceFiles=74,allOriginalPhysicalAndLogicalBytesIndependentlyVerified=True,
    independent360ColdAuditReviewed=True,settlingAndAdmissionEvidenceAccepted=True,
    allCoreNumbersAndScopeTypesPreserved=True,rawReceiptAliasesReviewed=True,
    refusedBeforeBlockSpawn=True,remainingIdentityZeroDoesNotEraseAdverseLaunch=True,
    backendQualified=False,scientificAcceptance=False,formalHardwareQualification=False,independentHumanReview=False,
    authorApproval=False,currentProductInheritsResearchQualification=False,seedConstructed=False,freshHeldoutCases=0,table7_3='NOT_RUN',
    nextActualAttemptRequiresSeparateProspectiveDecision=True,automaticRetries=0)
with (C/'root-refusal-disposition.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
print(json.dumps(result,indent=2))
