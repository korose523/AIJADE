#!/usr/bin/env python3
"""Complete raw-byte, stopped-attempt, admission and live-dataflow reconstruction."""
from pathlib import Path
import gzip
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parent
REPO=next(p for p in ROOT.parents if (p/'src/Aijade.Research').is_dir())
sys.path.insert(0,str(REPO/'experiments/ch7'))
from audit_retrieval_led import load,raw,lines,timestamp,sha
from audit_retrieval_suffix import require
from audit_live_manifest import verify
from build_known_live_manifest import construct,encoded
from score_live_manifest import score_directory
from test_live_manifest_scoring import run as scoring_controls
from test_live_manifest_rejections import run as rejections


def audit():
    acceptance=json.loads((REPO/'experiments/ch7/live-manifest-qualification-20261112.json').read_text())
    require(sha((ROOT/'manifest.json').read_bytes())==acceptance['manifestSha256'],'archive manifest identity')
    manifest=load(ROOT,'manifest.json');seen=set()
    for row in manifest['files']:
        rel=row['path'];p=ROOT/rel
        require(rel not in seen and not Path(rel).is_absolute() and '..' not in Path(rel).parts and p.is_file() and not p.is_symlink(),'unsafe/missing archive file')
        data=p.read_bytes();require(len(data)==row['bytes'] and sha(data)==row['sha256'],'archive bytes: '+rel);seen.add(rel)
    require(seen=={str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and p!=ROOT/'manifest.json'},'unlisted archive file')
    for row in load(ROOT,'logical-files.json'):
        data=gzip.decompress((ROOT/row['path']).read_bytes())
        require(len(data)==row['uncompressedBytes'] and sha(data)==row['uncompressedSha256'],'logical-byte hash')
    for rel,expected in manifest['instrumentSourceHashes'].items(): require(sha((REPO/rel).read_bytes())==expected,'instrument source changed: '+rel)
    runtime,origin=construct(REPO)
    require((REPO/'experiments/ch7/live-manifest-known-input-v1.json').read_bytes()==encoded(runtime),'runtime fixture derivation')
    first=ROOT/'attempts/development-01';repeat=ROOT/'attempts/development-02';admission=ROOT/'admission-01'
    a=load(first,'receipt.json');b=load(repeat,'receipt.json');gate=load(admission,'receipt.json')
    require(a['status']=='STOPPED' and a['reason']=='RuntimeError: swap_sustained_resource_stop' and a['completedCases']==0,'first resource stop missing')
    require(a['codeCommit']=='7a162ecbbcd78f42889a229ddd63836920d21aa4' and b['codeCommit']==gate['codeCommit']=='e2184e72f6746810c7be0ef181437364bbc8dd98','source chronology')
    require(not (first/'cases.json').exists() and load(ROOT,'stopped-score-refusal.json')['primaryErrorCounts'] is None,'stopped prefix relabelled as zero errors')
    try: score_directory(first)
    except ValueError: pass
    else: raise ValueError('Incomplete first run was scored')
    require(len(load(first,'prepared.json'))==20 and len(lines(first,'registry.jsonl'))-1==a['registeredIntentCount']==10,'first prefix/registration population')
    telemetry=lines(first,'telemetry.jsonl');timers={};stop_observed=False
    for t in telemetry:
        if t['swapIncreaseBytes']>1024**3:
            timers.setdefault('swap',t['elapsedSeconds'])
            if t['elapsedSeconds']-timers['swap']>=30:stop_observed=True
        else:timers.pop('swap',None)
    require(stop_observed and max(t['swapIncreaseBytes'] for t in telemetry)==a['peak']['swapIncreaseBytes'],'actual sustained swap stop')
    require(all(p['exitCode'] is None for p in a['phases'].values()),'unknown stopped child exit code invented')
    last=raw(first,'client/aijade-render-state.jsonl').splitlines()[-1]
    try: complete=json.loads(last).get('complete') is True
    except ValueError: complete=False
    require(not complete,'first incomplete renderer relabelled complete')
    require(len(load(first,'database-cleanup.json'))==20 and all(r['remaining']==0 for r in load(first,'database-cleanup.json')),'first owned leases remain')
    samples=lines(admission,'telemetry.jsonl')
    require(gate['status']=='ADMITTED' and gate['repeatStarted'] is True and gate['repeatExitCode']==0 and gate['firstAttemptBytesUnchanged'] is True,'admission/repeat incomplete')
    require(len(samples)==gate['samples'] and samples[-1]['elapsedSeconds']==gate['elapsedSeconds']>=120,'fixed admission interval')
    require(all(y['elapsedSeconds']>x['elapsedSeconds'] and timestamp(y['utc'])>=timestamp(x['utc']) for x,y in zip(samples,samples[1:])),'admission time reversal')
    require(all(not s['researchProcesses'] for s in samples) and min(s['availableBytes'] for s in samples)==gate['minimumAvailableBytes']>=4*1024**3,'unloaded available-memory admission')
    require(max(s['swapUsedBytes'] for s in samples)-min(s['swapUsedBytes'] for s in samples)==gate['swapRangeBytes']<=64*1024**2,'whole-window swap admission')
    require(timestamp(a['finishedAt'])<timestamp(samples[0]['utc']) and timestamp(samples[-1]['utc'])<=timestamp(b['phases']['flow']['startedAt']),'attempt/admission chronology')
    ia=load(first,'input-identities.json');ib=load(repeat,'input-identities.json');frozen=load(ROOT,'engineering/frozen-build.json')
    require(ia['binaries']==ib['binaries']==frozen['binaries'] and ia['liveSources']==ib['liveSources'],'rebuild/changed live algorithm on repeat')
    require(raw(first,'runtime-manifest.json')==raw(repeat,'runtime-manifest.json') and raw(first,'window-template.json')==raw(repeat,'window-template.json'),'changed repeated inputs/windows')
    preservation=load(admission,'first-attempt-preservation.json')
    for rel,expected in preservation.items():
        if (first/rel).is_file() or (first/(rel+'.gz')).is_file():require(sha(raw(first,rel))==expected,'archived first primary bytes changed')
    first_databases={p['databaseBefore']['database'] for p in load(first,'prepared.json')}
    later_databases={p['databaseBefore']['database'] for p in load(repeat,'prepared.json')}
    require(len(first_databases)==len(later_databases)==20 and first_databases.isdisjoint(later_databases),'prefix/database reused between attempts')
    ledger=load(ROOT,'case-disposition-ledger.json');require(len(ledger)==40,'attempt disposition denominator')
    require(all(r['promotionObserved'] is None and r['sandboxReuseObserved'] is None and r['suffixObservationStatus']=='NOT_REACHED' for r in ledger if r['attempt']=='development-01'),'first unknown outcome converted to zero')
    require(all(r['suffixObservationStatus']=='COMPLETE' for r in ledger if r['attempt']=='development-02'),'complete suffix missing')
    result=verify(repeat,REPO)
    require(result==load(ROOT,'full-raw-audit.json'),'full independent raw reconstruction')
    old=load(REPO/'experiments/ch7/manifest-preparation-2026-11-12','scores.json')
    require((score_directory(repeat)['arms']==old['arms'])==load(ROOT,'known-scenario-compatibility.json')['agrees'],'separate compatibility comparison')
    tests=scoring_controls();require(tests['status']=='PASS' and tests['tests']==5,'adverse-result scoring controls')
    negative=rejections(repeat,REPO);require(negative['rejectedCorruptions']==7 and negative['primaryUnchanged'],'raw rejection controls')
    require('CA1068' in raw(ROOT,'engineering/parser-tests-first.log').decode() and 'CA1861' in raw(ROOT,'engineering/parser-tests-first.log').decode(),'first compile failure hidden')
    require('通过:   660' in raw(ROOT,'engineering/full-tests.log').decode() and '失败:     0' in raw(ROOT,'engineering/full-tests.log').decode(),'default regression evidence')
    return dict(status='CONDITIONAL_LIVE_MANIFEST_PACKET_PASS',packetFiles=len(seen)+1,knownScenarioPairs=10,measuredConditionRows=20,
                retainedResourceStops=1,admissionWindows=1,admissionSamples=len(samples),retainedOriginalDatabases=20,allOwnedDatabaseLeasesCleaned=40,
                parserTests=5,scoringControls=5,rejectedCorruptions=7,heldOutCases=0,modelRequests=0,formalHardwareQualification=False,
                qualification='Conditional on one fixed unloaded admission; known-scenario live dataflow only.')


if __name__=='__main__':print(json.dumps(audit(),indent=2))
