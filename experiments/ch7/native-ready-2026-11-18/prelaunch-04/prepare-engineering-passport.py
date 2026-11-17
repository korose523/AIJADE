"""Prepare the actual E6 passport only after clean Qe6 and successful source CI.

Import is inert. No placeholder commit, passport or scientific decision exists.
The caller must explicitly invoke main after filling the actual receipt maps.
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import re
import shutil
import subprocess
import sys

B = Path('/Volumes/Untitled/AIJADE')
C = Path(__file__).resolve().parent
W = B / '.runtime/posix/nested-20261117/worktree'
BASELINE = 'ffbac56a171ccc5491c6e8186531ed8111da76cf'
PY = B / '.runtime/python-envs/p2-tokenizer/bin/python'
WRAPPER = B / '.runtime/run-local.sh'
PLAN = 'experiments/plans/2026-11-18-ch7-native-ready-engineering.md'
PROTOCOL = 'experiments/plans/2026-11-18-ch7-native-ready-protocol.json'
POLICY = 'configs/research/ch7-mac-native-ready-engineering-process-policy.json'
RUNNER = 'experiments/ch7/run_nested_load.py'
AUDIT = 'experiments/ch7/audit_nested_load.py'
CLONE = 'experiments/ch7/newowned_guard_cursor.py'
LAUNCH = 'experiments/ch7/native-ready-2026-11-18/freeze/launch_nested_load.py'
LAUNCH_SHA = '0e0222e961bd5d5be6e78567c2afbd6a535f317f8e21fb34098cccb7b40e2f43'
MODE = 'owned-guard-state-exact-prefix-v1'
INIT_MODE = 'paired-source-verified-owned-state-v1'
OUTPUT = B / '.runtime/posix/runs/ch7-native-ready-20261118/engineering-04'


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def unique(pairs):
    out = {}
    for key, value in pairs:
        need(key not in out, 'duplicate JSON key')
        out[key] = value
    return out


def read(path):
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def relative(value):
    need(type(value) is str and value and '\\' not in value and not any(ord(c) < 32 for c in value), 'safe relative path')
    p = PurePosixPath(value)
    need(not p.is_absolute() and '..' not in p.parts and p.as_posix() == value, 'canonical relative path')
    return value


def owned(value):
    p = Path(value)
    need(p.is_absolute() and p == p.resolve() and p.is_relative_to(B), 'absolute canonical path below AIJADE')
    need(not any(q.is_symlink() for q in (p, *p.parents)) and p.is_file(), 'regular unlinked evidence file required')
    return p


def git(*args):
    return subprocess.check_output(['git', '--no-replace-objects', '-C', str(W), *args])


def control_map():
    data = read(C / 'control-evidence-map.json')
    rows = data['files']
    need(type(rows) is list and rows, 'nonempty actual control-evidence map')
    result, paths = {}, {}
    for row in rows:
        need(type(row) is dict and set(row) == {'path', 'name', 'sha256'}, 'control row path/name/sha256 schema')
        name = relative(row['name'])
        path = owned(row['path'])
        need(name not in result and str(path) not in paths, 'duplicate control evidence name/path')
        need(re.fullmatch('[0-9a-f]{64}', row['sha256']) is not None and file_sha(path) == row['sha256'],
             'actual control evidence hash differs: ' + name)
        result[name], paths[str(path)] = row['sha256'], name
    categories = data['categories']
    need(type(categories) is dict and set(categories) == {
        'cursorControls', 'pairedBootstrapProbe', 'launcherControls', 'retainedHistory'}, 'complete control evidence categories')
    for category, names in categories.items():
        need(type(names) is list and names and len(names) == len(set(names)) and set(names) <= set(result),
             'missing actual evidence for category: ' + category)
    folder=C/'launcher-preparation'
    for filename in ('launcher-controls-final.json','test_nested_launcher.py','test_owned_launcher_adverse.py',
                     'test_native_launcher_adverse.py','testdata/nested-engineering-protocol.fixture.json','launcher-controls-native-final.log'):
        need(str(folder/filename) in paths,'complete native launcher controls/source/fixture/log mapping')
    controls=read(folder/'launcher-controls-final.json')
    need(controls['status']=='MOCKED_PARENT_LAUNCHER_NATIVE_CONTROLS_PASS_NOT_LIVE_VALIDATION'
         and type(controls['passed']) is int and controls['passed']==81 and controls['failed']==0
         and controls['launcherSha256']==LAUNCH_SHA,'actual distinct81native controls required')
    need(controls['newRealChildren']==controls['newObserverRequests']==controls['artifactExecutions']==0,'mock tests cannot be actual load')
    need(controls['testSha256']==file_sha(folder/'test_nested_launcher.py')
         and controls['fixtureSha256']==file_sha(folder/'testdata/nested-engineering-protocol.fixture.json')
         and controls['logSha256']==file_sha(folder/'launcher-controls-native-final.log'),'native test/log/fixture pins')
    need(set(controls['additionalTestSha256'])=={'test_owned_launcher_adverse.py','test_native_launcher_adverse.py'},
         'complete two additional native launcher test sources')
    for name,expected in controls['additionalTestSha256'].items():
        need(file_sha(folder/name)==expected,'additional native launcher actual test source differs')
    component=read(C/'component-handoff-01.json')
    need(component['status']=='NATIVE_READY_COMPONENT_NOT_ALL_PASS_NO_ENGINEERING_ACCEPTANCE',
         'retain the actual component refusal, never promote it')
    return result


def main():
    freeze = read(C / 'source-freeze-qe6.json')
    q = freeze['commit']
    need(type(q) is str and re.fullmatch('[0-9a-f]{40}', q), 'actual Qe6 full commit required')
    need(git('rev-parse', 'HEAD').decode().strip() == q and not git('status', '--porcelain'), 'clean exact Qe6 worktree required')
    need(git('merge-base', '--is-ancestor', BASELINE, q) == b'', 'Qe6 must retain the published E3 history')
    ci = read(C / 'source-qe6-ci.json')
    need(ci['headSha'] == q and ci['status'] == 'completed' and ci['conclusion'] == 'success', 'actual successful Qe6 CI required')
    pub = read(C / 'source-qe6-publication.json')
    need(pub['status'] == 'REMOTE_QE_REF_AND_ALL_CHANGED_GIT_BLOBS_VERIFIED' and
         pub['sourceCommit'] == q and pub['baselineCommit'] == BASELINE, 'actual complete Qe6 publication receipt required')
    protocol, policy = read(W / PROTOCOL), read(W / POLICY)
    old = read(B / '.research/runs/ch7-nested-20261117/engineering-01-passport.json')
    observers = [*old['observerSources'], 'experiments/ch7/full_state_clone_cursor.py', CLONE,
        'experiments/ch7/native_exec_registry.py','experiments/ch7/lifecycle_exec_native.c','experiments/ch7/listener_evidence.py']
    need(len(observers) == len(set(observers)) == 21, 'complete explicit21observer native closure')
    proof_paths = ['.github/workflows/ci.yml', 'Aijade.slnx', 'experiments/ch7/native_exec_registry.py', 'experiments/ch7/lifecycle_exec_native.c',
        CLONE, POLICY, 'experiments/ch7/binary_authentication.py', 'experiments/ch7/finite_audit.py',
        'experiments/ch7/finite_runtime.py', 'experiments/ch7/finite_sequence_audit.py', 'experiments/ch7/godot_local.py',
        'experiments/ch7/lifecycle_audit.py', 'experiments/ch7/lifecycle_exec.py', 'experiments/ch7/mac_bulk_census.c',
        'experiments/ch7/mac_process_guard.py', 'experiments/ch7/mac_process_guard_v2.py', 'experiments/ch7/mac_process_guard_v3.py',
        'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json', 'experiments/ch7/phase_continuity.py',
        'experiments/ch7/process_lifecycle.py', RUNNER, 'experiments/ch7/measured_mac_monitor.py',
        'experiments/ch7/nested_event_index.py', AUDIT, PLAN, PROTOCOL, 'experiments/ch7/listener_evidence.py', 'tools/dev-services.sh']
    need(len(proof_paths) == len(set(proof_paths)) == 28, 'exact twenty-eight source-proof file commands')
    replacements = {old['planPath']: PLAN, old['protocolPath']: PROTOCOL, old['policyPath']: POLICY,
        'experiments/ch7/nested-load-2026-11-17/freeze/launch_nested_load.py': LAUNCH}
    old_closure = {replacements.get(name, name) for name in old['sourceFiles']}
    need(len(old['sourceFiles']) == 40 and len(old_closure) == 40, 'original forty-file closure and four replacements')
    changed = git('diff', '--name-only', '--no-renames', '--diff-filter=AM', BASELINE, q).decode().splitlines()
    need(not git('diff', '--name-only', '--no-renames', '--diff-filter=D', BASELINE, q), 'Qe6 must not delete historical source or evidence')
    sources = {}
    for name in sorted(old_closure | set(observers) | set(proof_paths) | set(changed)):
        relative(name)
        body = owned(W / name).read_bytes()
        need(body == git('show', q + ':' + name), 'working source differs from actual Qe6 Git blob: ' + name)
        mode = git('ls-tree', q, '--', name).decode().split()[0]
        need(mode in ('100644', '100755'), 'regular Git source blob required')
        sources[name] = sha(body)
    need(set(row['path'] for row in pub['files']) == set(changed) and pub['changedFiles'] == len(changed),
         'source publication complete changed population differs')
    need(all(row['sha256'] == sources[row['path']] for row in pub['files']), 'source publication actual blob SHA differs')
    need((W / LAUNCH).read_bytes() == (C / 'launcher-preparation/launch_nested_load.py').read_bytes() and sources[LAUNCH] == LAUNCH_SHA,
         'new exact C8/frozen launcher bytes required')
    need(protocol['schema'] == 'aijade.ch7.real-nested-engineering-protocol.v1' and
         protocol['planPath'] == PLAN and protocol['policyPath'] == POLICY and
         protocol['purpose'] == 'ENGINEERING_ONLY_NOT_BACKEND_QUALIFICATION', 'new exact engineering protocol identity')
    need(policy['purpose'] == 'engineering_real_nested_only' and 'executionDecision' not in policy,
         'engineering policy cannot be a scientific decision')
    for data in (policy, protocol):
        need(data['coordinationMode'] == 'segmented-census-mutation-v1' and
             data['coordinationSchema'] == 'aijade.mac.segmented-census-mutation.v1' and
             data['onlineReplayMode'] == MODE and data['onlineReplayInitializationMode'] == INIT_MODE and
             data['onlineReplaySourceSha256'] == sources[CLONE], 'explicit source-bound C-clone and paired initialization required')
    need(policy['binaryAuthenticationMode'] == 'full-read-exact-bytes-v1' and
         policy['binaryAuthenticationSourceSha256'] == sources['experiments/ch7/binary_authentication.py'], 'full binary authentication retained')
    need(protocol['sourceProofCommandsPerController'] == 30 and protocol['runtime']['blocks'] == 4 and
         protocol['runtime']['parentMaximumSeconds'] == 600 and protocol['automaticRetries'] == 0,
         'fixed workload and thirty-command proof envelope')
    need(policy.get('lifecycleExecMode')==protocol.get('lifecycleExecMode')=='native-ready-release-v1',
         'new explicit Native execution policy/protocol required')
    need(policy['nativeExec']==protocol['nativeExec'] and policy['listenerEvidence']==protocol['listenerEvidence'],
         'complete exact native/listener leaf policy/protocol equality')
    need(policy['nativeExec']['adapterSourceSha256']==sources['experiments/ch7/native_exec_registry.py']
         and policy['nativeExec']['sourceSha256']==sources['experiments/ch7/lifecycle_exec_native.c']
         and policy['nativeExec']['sourcePath']==str(W/'experiments/ch7/lifecycle_exec_native.c')
         and policy['listenerEvidence']['moduleSha256']==sources['experiments/ch7/listener_evidence.py'],
         'actual Native/caller/parser source bindings')
    controls = control_map()
    commands = [dict(arguments=['status', '--porcelain'], stdoutSha256=sha(git('status', '--porcelain'))),
                dict(arguments=['rev-parse', 'HEAD'], stdoutSha256=sha(git('rev-parse', 'HEAD')))]
    commands += [dict(arguments=['show', '{SOURCE}:' + name], stdoutSha256=sources[name]) for name in proof_paths]
    need(len(commands) == 30, 'exact thirty proof commands')
    need(Path(sys.executable).absolute() == PY, 'fixed project Python required')
    out = dict(schema='aijade.ch7.nested-load-passport.v1', purpose='ENGINEERING_ONLY_NOT_QUALIFICATION',
        sourceCommit=q, repo=str(W), output=str(OUTPUT), sourceFiles=sources,
        observerSources={name: sources[name] for name in observers}, runnerSha256=sources[RUNNER],
        auditScriptSha256=sources[AUDIT], launcherSha256=LAUNCH_SHA,
        policyPath=POLICY, policySha256=sources[POLICY], planPath=PLAN, planSha256=sources[PLAN],
        protocolPath=PROTOCOL, protocolSha256=sources[PROTOCOL], pythonPath=str(PY), pythonSha256=file_sha(PY),
        runtimeWrapperSha256=file_sha(WRAPPER), preflightCommands=commands,
        runtime=protocol['runtime'], prefixPaddingTaskCount=protocol['prefixPaddingTaskCount'],
        prefixPreparationMaximumSeconds=protocol['prefixPreparationMaximumSeconds'],
        journalAcceptanceMaximumBytes=protocol['journalAcceptanceMaximumBytes'],
        minimumDemonstratedPrefixBytes=protocol['minimumDemonstratedPrefixBytes'], numericContextLimits=protocol['numericContextLimits'],
        onlineReplayMode=MODE, onlineReplayInitializationMode=INIT_MODE, onlineReplaySourceSha256=sources[CLONE],
        toolExecutableSha256=dict(git=file_sha(Path(shutil.which('git')).resolve()), lsof=file_sha(Path('/usr/sbin/lsof').resolve())),
        sourceCiReceiptSha256=file_sha(C / 'source-qe6-ci.json'),
        sourcePublicationReceiptSha256=file_sha(C / 'source-qe6-publication.json'),
        controlEvidenceMapSha256=file_sha(C / 'control-evidence-map.json'), controlEvidenceSha256=controls,
        apfsFreeBytesAtFreeze=shutil.disk_usage(B / '.runtime/posix').free,
        automaticRetries=0, qualificationStarted=False, backendQualified=False, formalHardwareQualification=False,
        independentHumanReview=False, authorApproval=False, scientificAcceptance=False,
        seedConstructed=False, heldoutComparisonComplete=False,
        retainedE3PacketManifestSha256='75f8d31201824cf437a7142e160a9aab43d49f0c7e9a507cd47fb89df5d3a56b',
        retainedE4PacketManifestSha256='819cde4e8f7b8197f74181ec2ac6ec5d2ef82aeda6a6d56e1c949617de917e59',
        lifecycleExecMode=policy['lifecycleExecMode'],nativeExec=policy['nativeExec'],listenerEvidence=policy['listenerEvidence'],
        retainedE5PacketManifestSha256='0c0338bfa3b2b8862cf4e5aff4aae3baa28b1ede8a9ad0c5ab8e9a238a51b83e',
        scope='One separately frozen actual native READY engineering load; componentNOT_ALL_PASS retained. Not science/model/renderer/hardware qualification.')
    need(out['apfsFreeBytesAtFreeze'] >= 1024 ** 3, 'at least one GiB actual APFS free space required')
    target = C / 'engineering-04-passport.json'
    need(not target.exists() and not OUTPUT.exists(), 'single unused E6 passport/output required')
    need(git('rev-parse', 'HEAD').decode().strip() == q and not git('status', '--porcelain'), 'Qe6 changed during passport preparation')
    with target.open('x') as stream:
        json.dump(out, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(status='ACTUAL_QE6_AND_SUCCESSFUL_CI_PASSPORT_FROZEN_NOT_EXECUTED',
        sourceCommit=q, path=str(target), sha256=file_sha(target), sourceFiles=len(sources), observerSources=len(observers)), indent=2))


if __name__ == '__main__':
    main()
