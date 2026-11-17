"""Fixed synthetic-file comparison probe, never an observer/daemon/model read."""
from pathlib import Path
import cProfile
import gc
import hashlib
import importlib.util
import io
import json
import os
import pstats
import statistics
import sys
import tempfile
import time

HERE=Path(__file__).resolve().parent
BASE=Path('/Volumes/Untitled/AIJADE')
SIZE=138097040
PART=SIZE//2
REPEATS=3
OUT=HERE/'binary-comparison-probe-01'
OUT.mkdir()


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


old=load('binary_e5_baseline',HERE/'binary-baseline/binary_authentication.py')
new=load('binary_e5_candidate',HERE/'binary-candidate/experiments/ch7/binary_authentication.py')
BLOCK=bytes(range(256))*4096


def file_sha(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1024**2):result.update(block)
    return result.hexdigest()


def delta(before,after):return {key:after[key]-before[key] for key in before}


def write_original(path):
    with path.open('wb') as stream:
        left=PART
        while left:
            block=BLOCK[:min(left,len(BLOCK))];stream.write(block);left-=len(block)
        stream.flush();os.fsync(stream.fileno())


def measure(auth,paths,expected, *, profile=None):
    before=auth.statistics();cpu=time.process_time();wall=time.perf_counter()
    if profile:profile.enable()
    actual=[auth.sha256(path) for path in paths]
    if profile:profile.disable()
    elapsed=time.perf_counter()-wall;cpu=time.process_time()-cpu
    assert actual==expected,(actual,expected)
    report=dict(wallSeconds=elapsed,cpuSeconds=cpu,statisticsDelta=delta(before,auth.statistics()),actualDigests=actual)
    assert report['statisticsDelta']['openedFiles']==2
    assert report['statisticsDelta']['fullFileReads']==2
    assert report['statisticsDelta']['physicalReadBytes']==SIZE
    return report


results=[]
scratch=BASE/'.runtime/posix/tmp';scratch.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(dir=scratch,prefix='e5-binary-comparison-') as directory:
    paths=[Path(directory)/name for name in ('synthetic-gui-payload','synthetic-cli-payload')]
    for path in paths:write_original(path)
    expected=[file_sha(path) for path in paths]
    original_last=BLOCK[(PART-1)%len(BLOCK)]
    for repeat in range(REPEATS):
        order=('legacy','candidate') if repeat%2==0 else ('candidate','legacy')
        for method in order:
            for path in paths:write_original(path)
            module=old if method=='legacy' else new
            auth=module.BinaryAuthenticator({str(path):sha for path,sha in zip(paths,expected)})
            cold=measure(auth,paths,expected)
            equal=measure(auth,paths,expected)
            with paths[1].open('r+b') as stream:
                stream.seek(PART-1);stream.write(bytes([original_last^1]));stream.flush();os.fsync(stream.fileno())
            changed=[expected[0],file_sha(paths[1])]
            mismatch=measure(auth,paths,changed)
            assert cold['statisticsDelta']['sha256Bytes']==SIZE
            assert equal['statisticsDelta']['sha256Bytes']==0
            assert equal['statisticsDelta']['equalBytesAuthenticated']==SIZE
            assert mismatch['statisticsDelta']['sha256Bytes']==PART
            assert auth.statistics()['approvedFiles']==2 and auth.statistics()['approvedBytes']==SIZE
            results.append(dict(repeat=repeat,order=list(order),method=method,cold=cold,equal=equal,mismatch=mismatch))
            del auth;gc.collect()
    # Separate labelled diagnostic pass: not one of the three primary timings.
    profiles={}
    for method,module in [('legacy',old),('candidate',new)]:
        for path in paths:write_original(path)
        auth=module.BinaryAuthenticator({str(path):sha for path,sha in zip(paths,expected)})
        measure(auth,paths,expected)
        profiler=cProfile.Profile();measured=measure(auth,paths,expected,profile=profiler)
        report=io.StringIO();stats=pstats.Stats(profiler,stream=report).sort_stats('cumulative');stats.print_stats()
        profile_path=OUT/(method+'-equal-profile.txt');profile_path.write_text(report.getvalue())
        exact=[]
        for (filename,line,name),(primitive,calls,own,cumulative,callers) in stats.stats.items():
            if name=='_compare':exact.append(dict(source=filename,line=line,primitiveCalls=primitive,calls=calls,ownSeconds=own,cumulativeSeconds=cumulative))
        profiles[method]=dict(measurement=measured,compare=exact,profilePath=str(profile_path))
        del auth;gc.collect()

for repeat in range(REPEATS):
    pair={row['method']:row for row in results if row['repeat']==repeat}
    for phase in ('cold','equal','mismatch'):
        assert pair['legacy'][phase]['statisticsDelta']==pair['candidate'][phase]['statisticsDelta'],(repeat,phase)

summary={}
for method in ('legacy','candidate'):
    rows=[row for row in results if row['method']==method]
    summary[method]={phase:dict(medianSeconds=statistics.median(row[phase]['wallSeconds'] for row in rows),maximumSeconds=max(row[phase]['wallSeconds'] for row in rows)) for phase in ('cold','equal','mismatch')}
report=dict(schema='aijade.e5.binary-comparison-offline-probe.v1',
    status='OFFLINE_SYNTHETIC_COMPARISON_NOT_SERVICE_QUALIFICATION',
    fixture=dict(totalActualFileBytes=SIZE,fileCount=2,bytesPerFile=PART,sha256=expected,
        defaultPerFileCacheBytes=128*1024**2,defaultTotalCacheBytes=192*1024**2,
        defaultProductionCapsUnchanged=True,primaryRepeats=REPEATS,allPrimaryPhysicalReadsPerPhase=SIZE,
        mismatch='last byte of second file',profilingPassesSeparateFromPrimaryTimings=True),
    sourceFiles={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in [('baseline',Path(old.__file__)),('candidate',Path(new.__file__))]},
    summary=summary,results=results,profiles=profiles,
    scope=dict(syntheticProjectFilesOnly=True,actualDaemonSdkApiNativeModelReads=0,newObservedWindows=0,
        completeActualReadsToEOF=True,sourceCompareProfileNotWholeService=True,backendQualified=False,scientificAcceptance=False))
path=OUT/'result.json';path.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),summary=summary,compareProfiles={key:value['compare'] for key,value in profiles.items()}),indent=2))
