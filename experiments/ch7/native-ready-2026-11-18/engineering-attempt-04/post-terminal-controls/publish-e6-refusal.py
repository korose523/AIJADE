"""Publish only the closed E6 negative packet and its exact validation sources.

Import is inert. The explicit main boundary never starts an experiment or edits
the Q worktree; a separate index creates one additive, publicly verified commit.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import urllib.parse
import urllib.request

B = Path('/Volumes/Untitled/AIJADE')
C = Path(__file__).resolve().parent
W = B / '.runtime/posix/nested-20261117/worktree'
Q = '4599cfe9885e529e99ba22f7ffdbfb2ce290d583'
F = 'a6af0034c92fca138d7a7250d4f2895713a2b21d'
BRANCH = 'research/ch7-native-ready-refusal-20261118'
ROOT = 'experiments/ch7/native-ready-2026-11-18/'
PREFIX = ROOT + 'engineering-attempt-04/packet/'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def git(*args, input=None, env=None):
    return subprocess.run(['git', '--no-replace-objects', '-C', str(W), *args],
        input=input, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout


def exact(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(exact(left[k], right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(exact(a, b) for a, b in zip(left, right))
    return left == right


def local(path):
    path = Path(path)
    assert path.is_absolute() and path == path.resolve() and path.is_relative_to(C)
    assert path.is_file() and not any(p.is_symlink() for p in (path, *path.parents))
    return path


def relative(name):
    value = PurePosixPath(name)
    assert type(name) is str and name and not value.is_absolute() and '..' not in value.parts
    assert '\\' not in name and value.as_posix() == name and not any(ord(c) < 32 for c in name)
    return name


def main(args):
    packet = Path(args.packet)
    assert packet.is_relative_to(C) and packet.is_dir()
    # Normal sibling modules are present on disk and imported as normal modules.
    tools = packet / 'archive-tools'
    sys.path.insert(0, str(tools))
    from packet_common import verify_packet
    verified = verify_packet(packet)
    summary = read(packet / 'summary.json')
    audit = read(C / 'audit/e6-independent-negative-audit-01.json')
    assert summary['sourceCommit'] == Q and exact(summary['numbers'], audit['numbers'])
    assert summary['engineeringEnvelopeAccepted'] is False and summary['enclosingParentExitCode'] == 1
    assert summary['numbers']['nestedBlocksStarted'] == summary['numbers']['nestedBlocksCompleted'] == 0
    for key in ('backendQualified', 'scientificAcceptance', 'formalHardwareQualification',
                'independentHumanReview', 'authorApproval', 'seedConstructed',
                'heldoutComparisonComplete', 'currentProductInheritsResearchQualification'):
        assert summary['scope'][key] is False, key
    review_path, companion_path = local(args.root_review), local(args.companions)
    review, companions = read(review_path), read(companion_path)
    assert review['packetManifestSha256'] == verified['manifestSha256']
    assert review['engineeringAccepted'] is False and review['postTerminalAdverseControls']['failed'] == 0
    assert 10 <= review['postTerminalAdverseControls']['passed'] <= 17
    assert git('rev-parse', 'HEAD').decode().strip() == Q and not git('status', '--porcelain')
    assert git('rev-parse', F + '^{commit}').decode().strip() == F
    assert git('ls-remote', '--heads', 'origin', 'refs/heads/' + BRANCH) == b''
    payload = {}
    for path in sorted(packet.rglob('*')):
        if path.is_file():
            local(path)
            payload[PREFIX + relative(path.relative_to(packet).as_posix())] = path.read_bytes()
    for row in companions['files']:
        assert set(row) == {'name', 'sha256', 'bytes'}
        source = local(companion_path.parent / relative(row['name']))
        raw = source.read_bytes()
        assert sha(raw) == row['sha256'] and type(row['bytes']) is int and len(raw) == row['bytes']
        target = ROOT + 'engineering-attempt-04/post-terminal-controls/' + relative(row['name'])
        assert target not in payload
        payload[target] = raw
    companion_target = ROOT + 'engineering-attempt-04/post-terminal-controls/publication-companions.json'
    assert companion_target not in payload
    payload[companion_target] = companion_path.read_bytes()
    payload[ROOT + 'engineering-attempt-04/post-terminal-controls/root-packet-review.json'] = review_path.read_bytes()
    payload[ROOT + 'engineering-attempt-04/post-terminal-controls/root-recorded17-binding-python312.log'] = local(C / 'audit/root-recorded17-binding-python312-01.log').read_bytes()
    payload[ROOT + 'engineering-attempt-04/post-terminal-controls/publish-e6-refusal.py'] = Path(__file__).read_bytes()
    followup = local(C / 'followup/producer-cost-attribution.md')
    payload['experiments/plans/2026-11-18-ch7-producer-cost-attribution-followup.md'] = followup.read_bytes()
    original_readme = git('show', Q + ':' + ROOT + 'README.md')
    outcome = '''
## Actual E6 outcome: refused before nested load

The single frozen window ended with controller exit 1 and an actual enclosing
parent wait, without watchdog expiry or signals. All 168 raw observations were
retained: 167 PASS and one UNKNOWN/REFUSED. There were 167 complete accepted
services, 3,202 finite actual waits returning 0, and 9,609 canonical events.
The final complete service was 2.2452560660021845 seconds, above 2 seconds;
the complete after-listener call was 0.581139005 seconds, above 0.5 seconds.
Its 59-byte stdout still described the expected listener; stderr was empty,
return code was 0 and exception was null. Full transcript timing identifies
deadline rejection; it does not establish a missing port or a unique kernel or
filesystem cause. The two lock-held segments remained below 1.25 seconds.

The independent audit cold-reproduced every one of the 168 raw decisions and
all 336 Native transcripts. Its complete negative inventory is distinct from
the original frozen complete auditor, which actually refused the incomplete
candidate. Inner guard evaluations were 168; outer evaluations were 167, with
no fictitious final outer call. Unknown RSS and four null endpoints remain.
There were 132 unattempted settling slots and 60 unattempted admission slots;
no nested child, model, renderer, qualification, seed or held-out case was run.

See the [complete E6 packet](engineering-attempt-04/packet/) and
[post-terminal portable controls](engineering-attempt-04/post-terminal-controls/).
The [inactive follow-up](../../plans/2026-11-18-ch7-producer-cost-attribution-followup.md)
requires measured producer-cost attribution and another actual source freeze;
it authorizes no window or qualification. The producer did not copy its whole
historical state per lookup. User-space read-byte counters include OS cache and
do not measure device traffic. Its original reaped clock includes a lease read
after Popen.wait, so that interval is not pure lsof/kernel time.

'''
    marker = b'## Preserved' if b'## Preserved' in original_readme else b'```mermaid'
    assert original_readme.count(marker) == 1
    payload[ROOT + 'README.md'] = original_readme.replace(marker, outcome.encode() + marker, 1)
    workflow = git('show', Q + ':.github/workflows/ci.yml')
    needle = b'      - name: Verify native READY, full listener transcripts and current independent native audit controls\n'
    assert workflow.count(needle) == 1
    addition = ("      - name: Verify complete retained E6 Native refusal without live services\n"
                "        run: |\n"
                "          .runtime/finite-control-env/bin/python -B " + PREFIX +
                "archive-tools/verify_e6_packet.py --packet " + PREFIX.rstrip('/') + "\n"
                "          .runtime/finite-control-env/bin/python -B " + ROOT +
                "engineering-attempt-04/post-terminal-controls/verify_e6_recorded_controls.py --packet " +
                PREFIX.rstrip('/') + "\n").encode()
    payload['.github/workflows/ci.yml'] = workflow.replace(needle, addition + needle, 1)
    assert payload['.github/workflows/ci.yml'].replace(addition, b'', 1) == workflow
    assert payload and all(len(raw) <= 32 * 1024 ** 2 for raw in payload.values())
    index = C / 'e6-refusal-publication.index'
    assert not index.exists() and not (C / 'e6-refusal-local.json').exists()
    env = dict(os.environ, GIT_INDEX_FILE=str(index))
    git('read-tree', F, env=env)
    rows = []
    for name, raw in sorted(payload.items()):
        oid = git('hash-object', '-w', '--stdin', input=raw).decode().strip()
        rows.append(('100644 ' + oid + '\t' + name + '\0').encode())
    git('update-index', '-z', '--index-info', input=b''.join(rows), env=env)
    tree = git('write-tree', env=env).decode().strip()
    commit = git('commit-tree', tree, '-p', F,
        input=b'Retain full E6 Native deadline refusal, independent cold evidence and inactive attribution plan\n').decode().strip()
    git('update-ref', 'refs/heads/' + BRANCH, commit, '0' * 40)
    result = dict(status='LOCAL_E6_NEGATIVE_COMMIT_NOT_REMOTE_VERIFIED', commit=commit,
                  parent=F, measurementSource=Q, branch=BRANCH,
                  packetManifestSha256=verified['manifestSha256'], files=len(payload))
    with (C / 'e6-refusal-local.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    git('push', 'origin', commit + ':refs/heads/' + BRANCH)
    assert git('ls-remote', '--heads', 'origin', 'refs/heads/' + BRANCH).decode().split() == [commit, 'refs/heads/' + BRANCH]

    def check(item):
        name, expected = item
        url = 'https://raw.githubusercontent.com/korose523/AIJADE/' + commit + '/' + urllib.parse.quote(name, safe='/')
        with urllib.request.urlopen(url, timeout=60) as response:
            raw = response.read(32 * 1024 ** 2 + 1)
        assert raw == expected == git('show', commit + ':' + name), name
        return dict(path=name, url=url, sha256=sha(raw), bytes=len(raw))

    with ThreadPoolExecutor(max_workers=4) as pool:
        verified_rows = list(pool.map(check, sorted(payload.items())))
    result = dict(status='REMOTE_E6_ADVERSE_PACKET_AND_ALL_FIXED_GIT_BLOBS_VERIFIED_NOT_QUALIFIED',
        commit=commit, parent=F, measurementSource=Q, branch=BRANCH, packetPrefix=PREFIX,
        packetManifestSha256=verified['manifestSha256'], summarySha256=sha((packet / 'summary.json').read_bytes()),
        files=verified_rows, remoteHead=commit, remoteHeadVerified=True,
        engineeringEnvelopeAccepted=False, backendQualified=False, seedConstructed=False,
        heldoutComparisonComplete=False, newWindowStartedByPublication=False)
    with (C / 'e6-refusal-publication.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    assert git('rev-parse', 'HEAD').decode().strip() == Q and not git('status', '--porcelain')
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('packet', 'companions', 'root-review'):
        parser.add_argument('--' + name, type=Path, required=True)
    main(parser.parse_args())
