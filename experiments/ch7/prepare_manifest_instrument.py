#!/usr/bin/env python3
"""Derive an explicitly non-new fixture from the previously measured development packet."""
import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import random
import subprocess

from audit_retrieval_led import load, raw
from comparison_manifest import CONDITIONS, REGISTRY_SHA256, SCHEMA, require, score
from score_paired_development import score as frozen_score

BASE = '8de976772e7635af7719fba8b76716f8cdb7a482'
PACKET = 'experiments/ch7/paired-development-2026-11-12'
PACKET_SHA256 = 'ea0285d60ade24313ee201eb2223fd63f0fb71461e9c9a7a2633deb33da62fb2'
PIN_PATHS = ['src', 'tests/Aijade.Tests/ResearchLoopAdapter.cs',
             'tests/Aijade.Tests/ResearchLoopQualificationTests.cs',
             'tests/Aijade.Tests/ResearchRetrievalLedTests.cs',
             'tests/Aijade.Tests/ResearchPairedDevelopmentTests.cs',
             'experiments/ch7/2026-11-12/selection.json',
             'experiments/ch7/paired-development-scoring-v1.json',
             'experiments/ch7/paired-development-layout-v1.json',
             'experiments/ch7/score_paired_development.py',
             'Directory.Build.props', 'Directory.Packages.props', 'global.json']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def text_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def source_freeze(repo):
    tree = subprocess.check_output(['git', 'ls-tree', '-r', '-z', BASE, '--', *PIN_PATHS], cwd=repo)
    rows = []
    for entry in tree.split(b'\0'):
        if not entry:
            continue
        header, path_raw = entry.split(b'\t', 1)
        mode, kind, blob = header.decode().split()
        relative = path_raw.decode('utf-8')
        path = repo / relative
        require(mode in ('100644', '100755') and kind == 'blob' and not path.is_symlink(), 'unsupported source entry')
        data = path.read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        require(actual == blob, 'source differs from pinned public code: ' + relative)
        rows.append(dict(path=relative, bytes=len(data), sha256=sha(data), gitBlobSha1=blob))
    require(len(rows) > 100, 'source freeze unexpectedly narrow')
    return dict(schema='aijade.ch7.comparison-source-freeze.v1', basePublicCode=BASE,
                selection='All tracked src files plus the actual adapter, legacy drivers, frozen scoring/layout, selected programs and dependency configuration.',
                files=rows, researchApproval=False, newHeldoutCases=0)


def derive(repo):
    source = repo / PACKET
    require(sha((source / 'manifest.json').read_bytes()) == PACKET_SHA256, 'source packet identity')
    original_bytes = raw(source / 'attempts/development-01', 'cases.json')
    original = json.loads(original_bytes)
    rules = load(source, 'scoring-contract.json')
    require(sha(raw(source, 'scoring-contract.json')) == REGISTRY_SHA256, 'original window registry identity')
    aliases = {r['caseId']: 'u_' + sha((PACKET_SHA256 + ':' + r['caseId']).encode())[:16] for r in rules['cases']}
    require(len(set(aliases.values())) == len(aliases), 'alias collision')
    rows = copy.deepcopy(original)
    for row in rows:
        row['caseId'] = aliases[row['caseId']]
        row['batch'] = 'derived_development_reencoding_not_new_measurement'
    new_rules = copy.deepcopy(rules['cases'])
    for rule in new_rules:
        rule['caseId'] = aliases[rule['caseId']]
    rng = random.Random(20261112)
    rng.shuffle(new_rules)
    rng.shuffle(rows)
    manifest = dict(schema=SCHEMA, purpose='development_reencoding_only', conditions=copy.deepcopy(CONDITIONS),
                    casePairs=len(new_rules), conditionRows=len(rows), cases=new_rules,
                    scheduledInvalidPromotionOpportunitiesPerCondition=rules['scheduledInvalidPromotionOpportunitiesPerCondition'],
                    scheduledInvalidReuseOpportunitiesPerCondition=rules['scheduledInvalidReuseOpportunitiesPerCondition'],
                    windowRegistrySha256=REGISTRY_SHA256, sourcePacketManifestSha256=PACKET_SHA256,
                    sourceRowsSha256=sha(original_bytes), round2SemanticActCorrectness='NOT_MEASURED')
    return rows, manifest, aliases, original, rules


def check_original_parity(result, original, rules, aliases):
    frozen = frozen_score(original, rules)
    reverse = {v: k for k, v in aliases.items()}
    for condition in ('C1', 'C2'):
        actual = copy.deepcopy(result['arms'][condition])
        actual.pop('normalOutcomeCounts')
        for row in actual['byCase']:
            row['caseId'] = reverse[row['caseId']]
        actual['byCase'].sort(key=lambda r: r['caseId'])
        expected = copy.deepcopy(frozen['arms'][condition])
        expected['byCase'].sort(key=lambda r: r['caseId'])
        require(actual == expected, 'frozen per-case/arm scoring changed: ' + condition)
    require(result['differencesC2MinusC1'] == frozen['differencesC2MinusC1'], 'frozen contrast changed')
    return dict(status='PASS', completePerCaseRecords=20, completeConditionSummaries=2,
                primaryDefinitionsUnchanged=True, newEmpiricalObservations=0, heldOutCases=0)


def main(repo, output):
    require(not output.exists(), 'output already exists')
    rows, manifest, aliases, original, rules = derive(repo)
    result = score(rows, manifest)
    parity = check_original_parity(result, original, rules, aliases)
    freeze = source_freeze(repo)
    output.mkdir(parents=True)
    for name, value in [('comparison-manifest.json', manifest), ('source-to-alias-map.json', aliases),
                        ('scores.json', result), ('original-score-parity.json', parity), ('source-freeze.json', freeze)]:
        (output / name).write_bytes(text_bytes(value))
    (output / 'derived-existing-rows.json.gz').write_bytes(gzip.compress(text_bytes(rows), mtime=0))
    print(json.dumps(dict(status='DERIVED_EXISTING_OBSERVATIONS_ONLY', sourceFilesFrozen=len(freeze['files']),
                          oldCasesReencoded=10, newEmpiricalObservations=0, parity=parity), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    main(args.repo.resolve(), args.output.resolve())
