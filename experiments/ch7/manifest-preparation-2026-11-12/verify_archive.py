#!/usr/bin/env python3
"""Verify the complete, explicitly non-new manifest instrument preparation."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
REPO = next(p for p in ROOT.parents if (p / 'src/Aijade.Research').is_dir())
sys.path.insert(0, str(REPO / 'experiments/ch7'))
from comparison_manifest import require, score
from prepare_manifest_instrument import BASE, PACKET, PACKET_SHA256, check_original_parity, derive
from test_comparison_manifest import run


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def verify():
    acceptance = json.loads((REPO / 'experiments/ch7/manifest-preparation-acceptance-20261112.json').read_text())
    require(hashlib.sha256((ROOT / 'manifest.json').read_bytes()).hexdigest() == acceptance['manifestSha256'], 'preparation manifest identity')
    listing = read('manifest.json')
    seen = set()
    for row in listing['files']:
        relative = row['path']
        require(relative not in seen and not Path(relative).is_absolute() and '..' not in Path(relative).parts, 'unsafe manifest path')
        path = ROOT / relative
        require(path.is_file() and not path.is_symlink(), 'missing packet file')
        data = path.read_bytes()
        require(len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256'], 'packet bytes: ' + relative)
        seen.add(relative)
    require(seen == {str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and p != ROOT / 'manifest.json'}, 'unlisted packet file')
    for relative, expected in listing['instrumentSourceHashes'].items():
        require(hashlib.sha256((REPO / relative).read_bytes()).hexdigest() == expected, 'instrument source changed: ' + relative)
    require(hashlib.sha256((REPO / PACKET / 'manifest.json').read_bytes()).hexdigest() == PACKET_SHA256, 'old measured archive identity')
    freeze = read('source-freeze.json')
    require(freeze['basePublicCode'] == BASE and len(freeze['files']) == 331, 'frozen source identity/coverage')
    listed_src = {r['path'] for r in freeze['files'] if r['path'].startswith('src/')}
    actual_src = set(subprocess.check_output(['git', 'ls-files', '-z', '--', 'src'], cwd=REPO).decode().rstrip('\0').split('\0'))
    require(listed_src == actual_src, 'tracked source set changed')
    for row in freeze['files']:
        path = REPO / row['path']
        require(path.is_file() and not path.is_symlink(), 'frozen source missing')
        data = path.read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        require(len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256'] and blob == row['gitBlobSha1'], 'source hash: ' + row['path'])
    rows = json.loads(gzip.decompress((ROOT / 'derived-existing-rows.json.gz').read_bytes()))
    manifest = read('comparison-manifest.json')
    expected_rows, expected_manifest, aliases, original, rules = derive(REPO)
    require(rows == expected_rows and manifest == expected_manifest and read('source-to-alias-map.json') == aliases, 'not the exact declared existing-record derivation')
    result = score(rows, manifest)
    require(result == read('scores.json'), 'archived derived score changed')
    require(check_original_parity(result, original, rules, aliases) == read('original-score-parity.json'), 'original full-score parity')
    tests = run()
    require(tests['status'] == 'PASS' and tests['tests'] == 18 and tests['failures'] == tests['errors'] == 0, 'instrument controls failed')
    require(read('instrument-tests-final.json')['status'] == 'PASS' and read('instrument-tests-first.json')['tests'] == 16, 'instrument implementation chronology')
    require(read('original-archive-verification.json')['status'] == 'PASS', 'original full archive verification record')
    proposal = json.loads((REPO / 'experiments/ch7/heldout-protocol-proposal-v1.json').read_text())
    require(proposal['status'] == 'PROPOSED_NOT_APPROVED_NOT_RUN' and proposal['newHeldoutCases'] == proposal['newModelJudgments'] == 0, 'proposal promoted to result')
    require(proposal['caseGenerationSeed'] is proposal['authorProtocolApproval'] is proposal['supervisorProtocolApproval'] is None, 'approval/seed invented')
    require(proposal['proposedPairs'] == proposal['normalPairs'] + proposal['semanticLimitPairs'] + proposal['integrityFamilies'] * proposal['pairsPerIntegrityFamily'] == 40, 'proposal count arithmetic')
    return dict(status='MANIFEST_INSTRUMENT_PREPARATION_PASS', packetFiles=len(seen) + 1,
                sourceFilesFrozen=331, completeOriginalPerCaseScores=20, originalConditionSummaries=2,
                instrumentTests=tests['tests'], newEmpiricalObservations=0, newHeldOutCases=0,
                newModelJudgments=0, manifestLiveDriverImplemented=False, formalProtocolApproved=False,
                originalPrimaryMeasurementRerun=False, proposedPairsNotResults=40)


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
