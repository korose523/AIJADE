#!/usr/bin/env python3
"""Run the committed configured-policy study with durable logs and exact binary identities.

Build the Release test project at a clean commit first. No installation or live model is performed.
All outputs must be placed in a new directory outside the checkout.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
PLAN = '132bfda51b95fd4b0ebfc23304142d56bfcb455b'


def run(args):
    args.out.mkdir(parents=True, exist_ok=False)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip(), 'build/run the clean committed instrumentation'
    binaries = {}
    for name in ['Aijade.Tests', 'Aijade.Client', 'Aijade.Server']:
        path = args.artifacts / 'bin' / name / 'release' / (name + '.dll')
        strings = subprocess.check_output(['strings', str(path)])
        identity = re.search(rb'0\.1\.0\+[0-9a-f]{40}', strings)
        assert identity and identity.group().decode().endswith(commit), (name, 'binary is not from this exact commit')
        binaries[name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'informationalVersion': identity.group().decode()}
    ledger = {'schema': 'aijade.p3.policy.execution.v1', 'planCommit': PLAN, 'codeCommit': commit,
              'binaryIdentities': binaries, 'startedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'phases': []}
    if args.external_only:
        ledger['recordingAmendmentCommit'] = '87e2f3189ad3eb7fdabd4e45ae298cf8d84b78e2'
        assert args.completed_product is not None
        saved = {}
        for mode in ['text', 'embedding']:
            path = args.completed_product / mode / ('product-%s-receipt.json' % mode)
            old = json.loads(path.read_text())
            assert old['rows'] == 7944 and old['baselines'] == 1986 and old['replayMisses'] == 0
            saved[mode] = {'receiptSha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'codeCommit': old['codeCommit']}
        ledger['completedProductReference'] = saved
        ledger['externalOnlyRestart'] = True
    identity_path = args.out / 'execution.json'

    def save():
        identity_path.write_text(json.dumps(ledger, indent=2) + '\n')

    env = os.environ.copy()
    env.update({'AIJADE_ARTIFACTS': str(args.artifacts), 'AIJADE_GIT_COMMIT': commit, 'AIJADE_P3_POLICY_PLAN': PLAN,
                'AIJADE_P3E_CORPUS': str(args.raw_corpus), 'AIJADE_P3_POLICY_PRIOR': str(args.source / 'attempt-02'),
                'AIJADE_TEST_DATABASE_URL': 'postgres://aijade:aijade@127.0.0.1:55432/aijade', 'TZ': 'UTC',
                'DOTNET_ROOT': str(args.dotnet.parent), 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
                'MEM0_TELEMETRY': 'False', 'ANONYMIZED_TELEMETRY': 'False'})
    env['PATH'] = str(args.dotnet.parent) + os.pathsep + env['PATH']

    def execute(name, command, extra=None):
        record = {'name': name, 'command': command, 'startedAt': dt.datetime.now(dt.timezone.utc).isoformat()}
        ledger['phases'].append(record)
        save()
        print('START', name, flush=True)
        phase_env = dict(env)
        phase_env.update(extra or {})
        with (args.out / (name + '.log')).open('x') as log:
            process = subprocess.Popen(command, cwd=ROOT, env=phase_env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            started = time.monotonic()
            while process.poll() is None:
                time.sleep(2)
                if time.monotonic() - started > 7200:
                    record['stopReason'] = 'two-hour infrastructure/setup/phase limit; retain partial attempt'
                    os.killpg(process.pid, signal.SIGTERM)
                    break
            record['exitCode'] = process.wait()
        record['endedAt'] = dt.datetime.now(dt.timezone.utc).isoformat()
        save()
        if record['exitCode'] or 'stopReason' in record:
            raise SystemExit('Failed phase retained: ' + name)
        print('COMPLETE', name, flush=True)

    source_args = ['--source', str(args.source), '--corpus', str(args.corpus), '--raw-corpus', str(args.raw_corpus)]
    script = str(Path(__file__).with_name('external_policies.py'))
    execute('external-qualification', [str(args.external_python), script, '--qualify', '--out', str(args.out / 'external-qualification')])
    test = [str(args.dotnet), 'test', 'tests/Aijade.Tests/Aijade.Tests.csproj', '-c', 'Release', '--no-build']
    for mode in ([] if args.external_only else ['text', 'embedding']):
        target = args.out / mode
        target.mkdir()
        command = test + ['--filter', 'FullyQualifiedName~ProductPolicyExperimentTests', '--logger', 'trx;LogFileName=full-corpus.trx', '--results-directory', str(target / 'test-results')]
        execute('product-' + mode, command, {'AIJADE_P3_POLICY_OUT': str(target), 'AIJADE_P3_POLICY_MODE': mode})
        result = json.loads((target / ('product-%s-receipt.json' % mode)).read_text())
        assert result['rows'] == 7944 and result['baselines'] == 1986
    (args.out / 'external').mkdir()
    for system in ['langchain', 'mem0']:
        target = args.out / 'external' / system
        execute('external-' + system, [str(args.external_python), script, '--system', system, '--out', str(target), *source_args])
        output = target / (system + '-prompts.jsonl.gz')
        command = test + ['--filter', 'FullyQualifiedName~ExternalPolicyPromptTests', '--logger', 'trx;LogFileName=external-prompts.trx', '--results-directory', str(target / 'test-results')]
        execute('external-prompts-' + system, command,
                {'AIJADE_P3_EXTERNAL_INPUT': str(target / (system + '.jsonl.gz')), 'AIJADE_P3_EXTERNAL_OUTPUT': str(output)})
    ledger['status'] = 'ALL_EXECUTION_PHASES_COMPLETE_VALIDATE_RAW_DATA_BEFORE_CLAIMS'
    ledger['endedAt'] = dt.datetime.now(dt.timezone.utc).isoformat()
    save()
    print(ledger['status'], flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--external-only', action='store_true')
    p.add_argument('--completed-product', type=Path)
    p.add_argument('--dotnet', type=Path, default=Path('/Users/mac/.dotnet/dotnet'))
    p.add_argument('--external-python', type=Path, default=Path('/Users/mac/p3c-env/venv/bin/python'))
    p.add_argument('--artifacts', type=Path, default=Path('/Users/mac/.cache/aijade-next-artifacts'))
    p.add_argument('--source', type=Path, default=ROOT / 'experiments/p3-e/2026-11-10-shared-runtime')
    p.add_argument('--corpus', type=Path, default=Path('/Users/mac/.local/share/aijade-data/locomo-export.json'))
    p.add_argument('--raw-corpus', type=Path, default=Path('/Users/mac/.local/share/aijade-data/locomo10.json'))
    run(p.parse_args())
