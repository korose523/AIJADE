"""Explicitly publish E5 prelaunch metadata without moving clean Qe4.

Import is inert. main uses a separate Git index and additive commit/ref, then
verifies every published raw byte. It starts no engineering/scientific window.
No invocation, actual passport, Git mutation or network action is preparation.
"""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request

B = Path('/Volumes/Untitled/AIJADE')
C = Path(__file__).resolve().parent
W = B / '.runtime/posix/nested-20261117/worktree'
BRANCH = 'research/ch7-owned-state-freeze-20261118'
PREFIX = 'experiments/ch7/owned-state-2026-11-18/prelaunch-03/'


def main():
    spec = importlib.util.spec_from_file_location('owned_e4_passport_preparation', C / 'prepare-engineering-passport.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)  # Its main guard is deliberately not invoked.
    need, sha, read, owned, relative = helper.need, helper.sha, helper.read, helper.owned, helper.relative

    def git(*args, input=None, env=None):
        return subprocess.run(['git', '--no-replace-objects', '-C', str(W), *args], input=input,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, env=env).stdout

    q = read(C / 'source-freeze-qe4.json')['commit']
    need(type(q) is str and re.fullmatch('[0-9a-f]{40}', q), 'actual full Qe4 commit required')
    need(git('rev-parse', 'HEAD').decode().strip() == q and not git('status', '--porcelain'), 'clean exact Qe4 required')
    passport_path = owned(C / 'engineering-03-passport.json')
    passport = read(passport_path)
    need(passport['sourceCommit'] == q and passport['repo'] == str(W) and
         passport['output'] == str(helper.OUTPUT) and not helper.OUTPUT.exists(), 'actual unused E5 passport/output required')
    need(passport['purpose'] == 'ENGINEERING_ONLY_NOT_QUALIFICATION' and
         passport['onlineReplayMode'] == helper.MODE and passport['onlineReplayInitializationMode'] == helper.INIT_MODE and
         passport['onlineReplaySourceSha256'] == passport['sourceFiles'][helper.CLONE], 'new exact clone/init passport fields')
    ci = read(C / 'source-qe4-ci.json')
    pub = read(C / 'source-qe4-publication.json')
    need(ci['headSha'] == q and ci['status'] == 'completed' and ci['conclusion'] == 'success', 'actual successful source Qe4 CI required')
    run = re.fullmatch(r'https://github\.com/korose523/AIJADE/actions/runs/([0-9]+)', ci['url'])
    need(run is not None, 'actual source CI run URL required')
    need(pub['sourceCommit'] == q and pub['status'] == 'REMOTE_QE_REF_AND_ALL_CHANGED_GIT_BLOBS_VERIFIED', 'source raw-byte publication verified')
    need(helper.file_sha(C / 'source-qe4-ci.json') == passport['sourceCiReceiptSha256'] and
         helper.file_sha(C / 'source-qe4-publication.json') == passport['sourcePublicationReceiptSha256'], 'actual CI/publication passport pins')
    controls = helper.control_map()
    need(controls == passport['controlEvidenceSha256'] and
         helper.file_sha(C / 'control-evidence-map.json') == passport['controlEvidenceMapSha256'], 'actual complete control evidence matches passport')
    need(len(passport['observerSources']) == 18 and set(passport['observerSources']) <= set(passport['sourceFiles']), 'full eighteen-file observer closure')
    for name, expected in passport['sourceFiles'].items():
        raw = owned(W / relative(name)).read_bytes()
        need(sha(raw) == expected and raw == git('show', q + ':' + name), 'actual Qe4 frozen source differs: ' + name)
    for name, expected in passport['observerSources'].items():
        need(passport['sourceFiles'][name] == expected, 'observer source pin differs')
    need(git('ls-remote', '--heads', 'origin', 'refs/heads/' + BRANCH) == b'', 'single unused freeze branch required; never repeat an uncertain push')
    selection = read(C / 'prelaunch-artifacts.json')
    rows = selection['files']
    need(type(rows) is list and rows, 'explicit complete prelaunch artifact selection')
    payload, by_source = {}, {}
    for row in rows:
        need(type(row) is dict and set(row) == {'path', 'name'}, 'prelaunch row exact path/name schema')
        source = owned(row['path'])
        name = relative(row['name'])
        target = PREFIX + name
        need(target not in payload and str(source) not in by_source and name != 'publication-manifest.json',
             'duplicate prelaunch name/source or reserved manifest')
        raw = source.read_bytes()
        need(len(raw) <= 256 * 1024 ** 2, 'prelaunch artifact exceeds declared per-file cap')
        payload[target] = raw
        by_source[str(source)] = target
    required = ('engineering-03-passport.json', 'source-qe4-ci.json', 'source-qe4-publication.json',
        'source-freeze-qe4.json', 'control-evidence-map.json', 'prelaunch-artifacts.json',
        'prepare-engineering-passport.py', 'publish-engineering-freeze.py')
    need(all(str(C / name) in by_source for name in required), 'passport, source receipts and exact preparation/selection sources must all be published')
    for row in read(C / 'control-evidence-map.json')['files']:
        need(by_source.get(str(owned(row['path']))) == PREFIX + row['name'] and
             sha(payload[PREFIX + row['name']]) == row['sha256'], 'all control/probe/history rows must be published under their bound names')
    manifest = dict(schema='aijade.ch7.nested-engineering-prelaunch-publication.v1',
        status='FIXED_BEFORE_ONE_ENGINEERING_WINDOW_NOT_QUALIFICATION', sourceCommit=q,
        planPath=passport['planPath'], planSha256=passport['planSha256'],
        protocolPath=passport['protocolPath'], protocolSha256=passport['protocolSha256'],
        policyPath=passport['policyPath'], policySha256=passport['policySha256'],
        passportPath=by_source[str(passport_path)], passportSha256=sha(passport_path.read_bytes()),
        onlineReplayMode=helper.MODE, onlineReplayInitializationMode=helper.INIT_MODE,
        onlineReplaySourceSha256=passport['onlineReplaySourceSha256'],
        sourceCiRun=int(run.group(1)), sourceCiConclusion='success',
        controlEvidenceMapSha256=passport['controlEvidenceMapSha256'],
        artifactSelectionSha256=helper.file_sha(C / 'prelaunch-artifacts.json'),
        controlEvidenceCategories=read(C / 'control-evidence-map.json')['categories'],
        files=[dict(path=name, sha256=sha(raw), bytes=len(raw)) for name, raw in payload.items()],
        engineeringStarted=False, backendQualified=False, scientificAcceptance=False,
        formalHardwareQualification=False, independentHumanReview=False, authorApproval=False,
        seedConstructed=False, heldoutComparisonComplete=False, table7_3='NOT_RUN',
        retainedE3PacketManifestSha256=passport['retainedE3PacketManifestSha256'],
        retainedE4PacketManifestSha256=passport['retainedE4PacketManifestSha256'])
    payload[PREFIX + 'publication-manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    index = C / 'engineering-metadata.index'
    need(not index.exists() and not (C / 'engineering-freeze-local.json').exists() and
         not (C / 'engineering-freeze-publication.json').exists(), 'exclusive freeze index/receipts; preserve uncertain earlier attempts')
    env = dict(os.environ, GIT_INDEX_FILE=str(index))
    git('read-tree', q, env=env)
    for name, raw in payload.items():
        oid = git('hash-object', '-w', '--stdin', input=raw).decode().strip()
        git('update-index', '--add', '--cacheinfo', '100644,' + oid + ',' + name, env=env)
    tree = git('write-tree', env=env).decode().strip()
    commit = git('commit-tree', tree, '-p', q,
        input=b'Freeze actual nested owned-state engineering passport and complete retained preparation evidence before one attempt\n').decode().strip()
    need(git('rev-parse', 'HEAD').decode().strip() == q and not git('status', '--porcelain'), 'working Qe4 changed before freeze publication')
    git('update-ref', 'refs/heads/' + BRANCH, commit, '0' * 40)
    local = dict(status='LOCAL_ADDITIVE_ENGINEERING_METADATA_COMMIT_NOT_REMOTE_VERIFIED',
        commit=commit, parent=q, branch=BRANCH, tree=tree, files=list(payload), passportSha256=manifest['passportSha256'])
    with (C / 'engineering-freeze-local.json').open('x') as stream:
        json.dump(local, stream, indent=2)
        stream.write('\n')
    git('push', 'origin', commit + ':refs/heads/' + BRANCH)
    need(git('ls-remote', '--heads', 'origin', 'refs/heads/' + BRANCH).decode().split() ==
         [commit, 'refs/heads/' + BRANCH], 'remote actual freeze ref differs')

    def verify(item):
        name, expected = item
        url = 'https://raw.githubusercontent.com/korose523/AIJADE/' + commit + '/' + urllib.parse.quote(name, safe='/')
        with urllib.request.urlopen(url, timeout=45) as response:
            raw = response.read(len(expected) + 1)
        need(raw == expected and raw == git('show', commit + ':' + name), 'all actual remote/local Git bytes must match: ' + name)
        return dict(path=name, url=url, sha256=sha(raw), bytes=len(raw))

    with ThreadPoolExecutor(max_workers=4) as pool:
        verified = list(pool.map(verify, payload.items()))
    need(git('rev-parse', 'HEAD').decode().strip() == q and not git('status', '--porcelain'), 'freeze publication must leave W5 at clean Qe4')
    result = dict(status='REMOTE_ENGINEERING_FREEZE_AND_PASSPORT_VERIFIED_NOT_RUN', commit=commit,
        sourceCommit=q, branch=BRANCH, passportPath=manifest['passportPath'], passportSha256=manifest['passportSha256'],
        files=verified, engineeringWindowStarted=False, backendQualified=False, scientificAcceptance=False,
        seedConstructed=False, heldoutComparisonComplete=False)
    with (C / 'engineering-freeze-publication.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, indent=2))


if __name__ == '__main__':
    main()
