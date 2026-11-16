"""Explicit build identity and bounded owned cleanup for the finite controller.

These helpers never decide a C1/C2 scientific outcome. Unknown cleanup is adverse.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


BUILD_FREEZE_PATH='experiments/ch7/relocated-runtime-2026-11-16/frozen-build.json'


def validate_build(assembly, manifest, commit, repo=None, freeze_commit=None):
    assembly=Path(assembly).resolve();manifest=Path(manifest).resolve()
    require(assembly.name=='Aijade.Tests.dll' and assembly.is_file(), 'explicit test assembly missing')
    build=json.loads(manifest.read_text())
    require(build['status']=='CLEAN_COMMITTED_BUILD_FROZEN_BEFORE_QUALIFICATION' and build['commit']==commit, 'wrong committed build')
    require(build['assemblyInformationalVersion']=='0.1.0+'+commit, 'declared assembly revision')
    require(build['assemblyInformationalVersion'].encode() in assembly.read_bytes(), 'assembly revision bytes absent')
    files={p.name:p for p in assembly.parent.iterdir() if p.is_file()}
    require(assembly.with_suffix('.deps.json').name in files and assembly.with_suffix('.runtimeconfig.json').name in files, 'assembly runtime/dependency file missing')
    require(set(files)==set(build['files']), 'build file population changed')
    require(all(sha(p)==build['files'][name] for name,p in files.items()), 'build binary/dependency bytes changed')
    if repo is not None:
        require(re.fullmatch(r'[0-9a-f]{40}',freeze_commit or '') is not None, 'public build-freeze commit required')
        frozen=subprocess.check_output(['git','show',freeze_commit+':'+BUILD_FREEZE_PATH],cwd=repo)
        require(frozen==manifest.read_bytes(), 'pre-qualification public build freeze differs')
    return build


def cleanup_owned_databases(leases, docker, container, run=subprocess.run, budget_seconds=30):
    """Validate every lease before any destructive operation; never infer absence on an error."""
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',container) is not None, 'invalid explicit database container')
    try:
        values=[json.loads(line) for line in Path(leases).read_text().splitlines()] if Path(leases).is_file() else []
        names=[row['database'] for row in values]
        require(all(type(n) is str and re.fullmatch(r'aijade_test_[0-9a-f]{32}',n) for n in names), 'invalid owned lease; nothing dropped')
    except (OSError,ValueError,KeyError,TypeError) as error:
        return [dict(database=None,presentAfterProcessExit=None,remaining=None,error=type(error).__name__+': '+str(error))]
    command=[str(docker),'exec',container,'psql','-X','-U','aijade','-d','aijade','-v','ON_ERROR_STOP=1','-tAc']
    deadline=time.monotonic()+budget_seconds;records=[]
    def query(sql):
        remaining=deadline-time.monotonic()
        require(remaining>0, 'owned cleanup budget exhausted')
        result=run(command+[sql],capture_output=True,text=True,timeout=min(5,remaining),check=False)
        require(result.returncode==0, 'database cleanup command failed: '+result.stderr.strip()[:1000])
        return result.stdout.strip()
    for name in dict.fromkeys(names):
        row=dict(database=name,presentAfterProcessExit=None,remaining=None,error=None)
        try:
            count=query("SELECT count(*) FROM pg_database WHERE datname='"+name+"'")
            require(count in ['0','1'], 'unknown database presence response')
            row['presentAfterProcessExit']=int(count)
            if count=='1':
                query('DROP DATABASE '+name+' WITH (FORCE)')
            count=query("SELECT count(*) FROM pg_database WHERE datname='"+name+"'")
            require(count in ['0','1'], 'unknown final database presence response')
            row['remaining']=int(count)
        except (OSError,ValueError,subprocess.SubprocessError) as error:
            row['error']=type(error).__name__+': '+str(error)
        records.append(row)
    return records


def stop_owned_processes(roots, grace_seconds=5):
    records=[]
    for root in roots:
        row=dict(pid=root.pid,exitCode=root.poll(),errors=[])
        if row['exitCode'] is None:
            try:os.killpg(root.pid,signal.SIGTERM)
            except OSError as error:row['errors'].append(type(error).__name__+': '+str(error))
        records.append(row)
    deadline=time.monotonic()+grace_seconds
    while any(p.poll() is None for p in roots) and time.monotonic()<deadline:
        time.sleep(.05)
    for root,row in zip(roots,records):
        if root.poll() is None:
            try:os.killpg(root.pid,signal.SIGKILL)
            except OSError as error:row['errors'].append(type(error).__name__+': '+str(error))
        try:root.wait(timeout=1)
        except subprocess.SubprocessError as error:row['errors'].append(type(error).__name__+': '+str(error))
        row['exitCode']=root.poll()
    return records


def dispositions(root, planned, flow_started=False):
    """Partial/missing capture cannot be silently promoted to an unattempted or zero-error record."""
    root=Path(root);completed=[];started=set();errors=[]
    try:
        rows=json.loads((root/'cases.json').read_text()) if (root/'cases.json').is_file() else []
        completed=[r['caseId']+'/'+r['condition'] for r in rows]
        require(len(completed)==len(set(completed)) and set(completed)<=set(planned), 'invalid completed population')
    except (OSError,ValueError,KeyError,TypeError) as error:
        errors.append(type(error).__name__+': '+str(error));completed=[]
    try:
        for line in (root/'journal.jsonl').read_text().splitlines() if (root/'journal.jsonl').is_file() else []:
            key=json.loads(line)['caseId']
            if '/' in key:
                require(key in planned, 'unexpected journal identity');started.add(key)
    except (OSError,ValueError,KeyError,TypeError) as error:
        errors.append(type(error).__name__+': '+str(error))
    unknown=[p for p in planned if p not in completed and p not in started] if flow_started and (errors or not (root/'journal.jsonl').is_file()) else []
    return dict(completedCaseIds=completed,inFlightCaseIds=[p for p in planned if p in started and p not in completed],unknownCaseIds=unknown,
                unattemptedCaseIds=[p for p in planned if p not in started and p not in completed and p not in unknown],dispositionErrors=errors)


def read_block_receipt(path):
    try:
        value=json.loads(Path(path).read_text())
        require(type(value) is dict and value.get('status')=='COMPLETE_FINITE_BLOCK_OBSERVATIONS', 'missing/noncomplete block receipt')
        return value
    except (OSError,ValueError,TypeError) as error:
        raise ValueError('block did not produce a complete terminal receipt: '+str(error)) from error
