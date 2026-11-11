#!/usr/bin/env python3
"""Keep the authored source snapshot distinct from the SDK's embedded build revision."""
from pathlib import Path
import hashlib
import json
import re

from audit_retrieval_led import load
from audit_retrieval_suffix import require

repo=Path(__file__).resolve().parents[2]
accept=load(repo/'experiments/ch7','live-manifest-qualification-20261112.json')
binding=accept['buildProvenance'];p=repo/binding['path'];data=p.read_bytes();record=json.loads(data)
require(hashlib.sha256(data).hexdigest()==binding['sha256'],'build-provenance record identity')
embedded=re.search(r'AssemblyInformationalVersionAttribute\("([^"]+)"\)',record['generatedAssemblyInfo']).group(1)
require(embedded==record['assemblyInformationalVersion'] and embedded.split('+',1)[1]==record['embeddedBuildGitBase']==binding['embeddedBuildGitBase'],'embedded build revision')
require(hashlib.sha256(record['generatedAssemblyInfo'].encode()).hexdigest()==record['generatedAssemblyInfoSha256'],'generated build metadata bytes')
root=repo/'experiments/ch7/live-manifest-2026-11-12'
a=load(root/'attempts/development-01','input-identities.json');b=load(root/'attempts/development-02','input-identities.json')
require(record['authoredSourceCommit']==binding['authoredSourceCommit']==a['codeCommit'],'authored execution snapshot')
require(a['binaries']==b['binaries'] and a['binaries']['Aijade.Tests.dll']==record['testAssemblySha256'],'frozen actual binary changed')
for relative,expected in record['authoredSourceHashes'].items():
    require(a['liveSources'][relative]==b['liveSources'][relative]==expected==hashlib.sha256((repo/relative).read_bytes()).hexdigest(),'authored source bytes')
require(record['cleanCheckoutBinaryReproductionClaimed'] is binding['cleanCheckoutBinaryReproductionClaimed'] is False,'bitwise/clean-build equivalence invented')
print(json.dumps(dict(status='AUTHORED_SOURCE_AND_EMBEDDED_BUILD_REVISION_DISTINGUISHED',sourceCommit=record['authoredSourceCommit'],embeddedBuildBase=record['embeddedBuildGitBase'],frozenBinaryEqualAcrossRuns=True),indent=2))
