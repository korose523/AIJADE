#!/usr/bin/env python3
"""Read-only provenance/consistency audit for the 3 November 2026 review.

This does not generate model outputs, modify archived results, or qualify Ch7.
--require-current-version refuses to transfer P3-E numbers to changed sources.
--current-ref reads Git objects instead of the working tree, for a positive
version-control check. A matching source version is not scientific acceptance.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_PATHS = [
    'src/Aijade.Client/Chat/MemoryContext.cs',
    'src/Aijade.Server/Memory/MemoryLibrary.cs',
    'src/Aijade.Client/Chat/Orchestrator.cs',
    'src/Aijade.UI/Pages/Chat.razor',
    'src/Aijade.UI/Services/AppState.cs',
    'src/Aijade.Integrations/CompanionBridge.cs',
]


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def source(ref, path):
    return git('show', ref + ':' + path) if ref else (ROOT / path).read_bytes()


def first_commit(path):
    commits = git('log', '--diff-filter=A', '--format=%H', '--', path).decode().splitlines()
    return commits[-1] if commits else None


def import_score():
    spec = importlib.util.spec_from_file_location('p1b_archive_summary', ROOT / 'experiments/p1/stryker_summary.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.score


def qualitative_provenance(path):
    """Check a correction against its immutable inputs; this does not validate the qualitative labels."""
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest['schema'] != 'aijade.qualitative-provenance.v1':
        raise ValueError('Unknown qualitative provenance schema')
    items = []
    identities = set()
    for item in manifest['items']:
        if item['id'] in identities or item['codingMethod'] != 'AI_ASSISTED_EXPLORATORY':
            raise ValueError('Duplicate identity or unsupported qualitative coding method')
        identities.add(item['id'])
        source_path = (ROOT / item['path']).resolve()
        if not source_path.is_relative_to(ROOT.resolve()):
            raise ValueError('Qualitative input is outside the repository')
        actual = sha(source_path.read_bytes())
        data = json.loads(source_path.read_text(encoding='utf-8'))
        archived_reader = data
        for field in item['readerField']:
            archived_reader = archived_reader[field]
        items.append({**item, 'actualSha256': actual, 'matches': actual == item['sha256'],
                      'archivedAttribution': archived_reader})
    if not items:
        raise ValueError('A qualitative correction must identify its inputs')
    return {'status': 'INPUT_HASHES_CHECKED', 'manifestSha256': sha(path.read_bytes()),
            'authorClarification': manifest['authorClarification'],
            'independentHumanValidation': manifest['independentHumanValidation'],
            'items': items, 'allArtifactsMatch': all(item['matches'] for item in items),
            'interpretation': 'Checks input identity and declared AI assistance, not category accuracy or scientific acceptance.'}


def current_product_receipt(path, current_ref=None):
    """Check a new fixed-scope run separately from the historical v1 comparison; not independent attestation."""
    receipt = json.loads(path.read_text(encoding='utf-8'))
    if receipt['schema'] != 'aijade.p3e.current-run.v1':
        raise ValueError('Unknown current P3-E receipt schema')
    folder = (ROOT / receipt['artifactRoot']).resolve()
    if not folder.is_relative_to(ROOT.resolve()):
        raise ValueError('Current P3-E artifacts are outside the repository')
    artifacts = []
    for name, expected in receipt['artifactSha256'].items():
        target = (folder / name).resolve()
        if not target.is_relative_to(folder):
            raise ValueError('Current P3-E artifact escapes its package')
        artifacts.append({'path': name, 'matches': target.is_file() and sha(target.read_bytes()) == expected})
    summary = json.loads((folder / 'summary.json').read_text(encoding='utf-8'))
    manifest = json.loads((folder / 'protected-inputs.json').read_text(encoding='utf-8'))
    entries = []
    for name, expected in manifest['sha256'].items():
        if not name.startswith('src/'):
            continue
        try:
            actual = sha(source(current_ref, name))
        except (FileNotFoundError, subprocess.CalledProcessError):
            actual = None
        entries.append({'path': name, 'matches': actual == expected})
    coverage = []
    for condition in ['text', 'embedding']:
        raw_path = (folder / receipt['reports'][condition]).resolve()
        if not raw_path.is_relative_to(folder):
            raise ValueError('Current P3-E report escapes its package')
        with gzip.open(raw_path, 'rt', encoding='utf-8') as stream:
            raw = json.load(stream)
        rows = raw['rows']
        keys = {(r['c'], r['q']) for r in rows}
        saved = summary['conditions'][condition]['validation']
        coverage.append({'condition': condition, 'rows': len(rows), 'uniqueQuestions': len(keys),
                         'conversations': len({r['c'] for r in rows}),
                         'matches': len(rows) == len(keys) == 1986 and len({r['c'] for r in rows}) == 10 and
                         sum(r['answerable'] for r in rows) == 1540 and all(r['completed'] for r in rows) and
                         raw['entry'] == 'shared-memory-only' and raw['condition'] == condition and
                         raw['corpusSha256'] == summary['corpusSha256'] and raw['planCommit'] == receipt['planCommit'] and
                         raw['declaredCodeCommit'] == receipt['instrumentationCommit'] and
                         saved['captureAndSourceChecks'] == 'PASS' and
                         all(raw[k] == 0 for k in ['failedTurns', 'turnsNotStored', 'responseMismatches', 'promptMismatches', 'embeddingObservationMisses'])})
    ancestry = subprocess.run(['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', receipt['planCommit'], receipt['instrumentationCommit']], capture_output=True).returncode == 0
    source_paths = {e['path'] for e in entries}
    required = {'src/Aijade.Client/Chat/MemoryContext.cs', 'src/Aijade.Client/Chat/CompanionRuntime.cs',
                'src/Aijade.Client/Chat/PromptBudget.cs', 'src/Aijade.Client/Chat/Orchestrator.cs',
                'src/Aijade.Server/Memory/MemoryLibrary.cs', 'src/Aijade.Server/Product/ModelServices.cs'}
    required_artifacts = {'summary.json', 'protected-inputs.json', *receipt['reports'].values()}
    valid = (required_artifacts <= set(receipt['artifactSha256']) and all(e['matches'] for e in artifacts) and all(e['matches'] for e in entries) and required <= source_paths and
             all(e['matches'] for e in coverage) and ancestry and receipt['planCommit'] == summary['planCommit'])
    return {'valid': valid, 'artifacts': artifacts, 'productSourceFiles': entries, 'coverage': coverage,
            'planPrecedesInstrumentation': ancestry, 'scope': 'shared-memory-only; single-turn empty history; text and one embedding model',
            'note': 'Artifact/source/coverage consistency only. The separate capture validator checks rows against the corpus. Binary hashes are recorded, not independently attested. No all-feature Web/QQ, causal version effect or answer accuracy is inferred.'}


def policy_comparison_receipt(path, current_ref=None):
    """Check the named policy package without transferring its results to other/default configurations."""
    receipt = json.loads(path.read_text(encoding='utf-8'))
    if receipt['schema'] != 'aijade.p3.policy.run.v1':
        raise ValueError('Unknown configured P3 policy receipt schema')
    folder = (ROOT / receipt['artifactRoot']).resolve()
    if not folder.is_relative_to(ROOT.resolve()):
        raise ValueError('P3 policy package is outside the repository')
    artifacts = []
    for name, expected in receipt['artifactSha256'].items():
        target = (folder / name).resolve()
        if not target.is_relative_to(folder):
            raise ValueError('P3 policy artifact escapes its package')
        artifacts.append({'path': name, 'matches': target.is_file() and sha(target.read_bytes()) == expected})
    summary_path = (folder / receipt['summary']).resolve()
    if not summary_path.is_relative_to(folder):
        raise ValueError('P3 policy summary escapes its package')
    summary = json.loads(summary_path.read_text(encoding='utf-8'))
    source_manifest = json.loads((folder / 'protected-inputs.json').read_text(encoding='utf-8'))
    sources = []
    codes = receipt['executionCodeCommits']
    for name, expected in source_manifest['sha256'].items():
        if not name.startswith('src/'):
            continue
        try:
            actual = sha(source(current_ref, name))
        except (FileNotFoundError, subprocess.CalledProcessError):
            actual = None
        executed = {}
        for study, code in codes.items():
            try:
                executed[study] = sha(source(code, name)) == expected
            except (FileNotFoundError, subprocess.CalledProcessError):
                executed[study] = False
        sources.append({'path': name, 'matches': actual == expected, 'executionMatches': executed})
    coverage = []
    for group, names in [('product', ['text', 'embedding']), ('external', ['langchain', 'mem0'])]:
        for name in names:
            item = summary[group][name]
            checked = item['validation']
            primary = item['populations']['answerable']['population']
            coverage.append({'group': group, 'configuration': name, 'rows': checked['rows'],
                             'matches': checked['rows'] == 7944 and checked['questionsPerCell'] == 1986 and checked['cells'] == 4
                             and sum(checked['states'].values()) == 7944 and primary['questions'] == 1540
                             and primary['eligibleQuestions'] == 1536})
    ancestry = all(subprocess.run(['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', receipt['planCommit'], code], capture_output=True).returncode == 0 for code in codes.values())
    amendment_order = subprocess.run(['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', receipt['recordingAmendmentCommit'], codes['external']], capture_output=True).returncode == 0
    measured = []
    for record in receipt['measuringSources']:
        name, expected, code = record['path'], record['sha256'], codes[record['study']]
        try:
            actual = sha(source(code, name))
        except (FileNotFoundError, subprocess.CalledProcessError):
            actual = None
        measured.append({'path': name, 'matchesExecutionCommit': actual == expected})
    binary_bound = set(receipt['actualBinaryIdentitiesByStudy']) == set(codes) == {'product', 'external'} and all(set(binaries) == {'Aijade.Tests', 'Aijade.Client', 'Aijade.Server'} and
                       all(codes[study] in item['informationalVersion'] and len(item['sha256']) == 64 for item in binaries.values())
                       for study, binaries in receipt['actualBinaryIdentitiesByStudy'].items())
    required = {'summary.json', 'protected-inputs.json', 'search-crosscheck.json', 'execution.json'}
    valid = (required <= set(receipt['artifactSha256']) and all(item['matches'] for item in artifacts)
             and sources and all(item['matches'] and all(item['executionMatches'].values()) for item in sources) and measured
             and {r['study'] for r in receipt['measuringSources']} == set(codes)
             and all(item['matchesExecutionCommit'] for item in measured) and all(item['matches'] for item in coverage)
             and ancestry and amendment_order and binary_bound and summary['executionCodeCommits'] == codes
             and summary['planCommit'] == receipt['planCommit'] and receipt['capturedTurns'] == 31776
             and receipt['newModelCalls'] == summary['newModelCalls'] == summary['embeddingPreparation']['newEmbeddingHttpRequests']
             and receipt['newChatModelCalls'] == summary['newChatModelCalls'] == summary['policyExecutionNewModelCalls'] == 0)
    return {'valid': bool(valid), 'coverage': coverage, 'artifacts': artifacts, 'productSourceFiles': sources,
            'measuringSources': measured, 'planPrecedesCode': ancestry, 'recordingAmendmentPrecedesExternalCode': amendment_order, 'recordedBinaryIdentityBound': binary_bound,
            'scope': summary['scope'], 'note': 'Hash, source and complete-cell consistency; the raw capture/summary and numerical validators remain separate. Recorded identities are not independent execution attestation or scientific approval.'}


def audit(current_ref=None, qualitative_manifest=None, current_receipt=None, policy_receipt=None):
    frozen = load('configs/project-scope.json')['frozen']
    frozen_checks = [{'path': f['path'], 'expectedSha256': f['sha256'],
                      'actualSha256': sha(source(current_ref, f['path']))} for f in frozen]
    for check in frozen_checks:
        check['matches'] = check['actualSha256'] == check['expectedSha256']
    product = load('experiments/memory/product-path.json')
    plan = product['plan']
    plan_commit = first_commit(plan)
    comparisons = {}
    for condition, data in product['conditions'].items():
        declared = data['codeCommit']
        git('cat-file', '-e', declared + '^{commit}')
        entries = []
        for path in PRODUCT_PATHS:
            archived = sha(source(declared, path))
            now = sha(source(current_ref, path))
            entries.append({'path': path, 'atDeclaredRunCommitSha256': archived,
                            'comparisonSha256': now, 'matches': archived == now})
        comparisons[condition] = {
            'declaredRunCommit': declared, 'resolvedPlanCommit': plan_commit,
            'planCommitIsAncestor': subprocess.run(
                ['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', plan_commit, declared],
                capture_output=True).returncode == 0,
            'sourceFiles': entries, 'allComparedSourcesMatch': all(x['matches'] for x in entries),
            'runtimeExecutableHash': 'NOT_RECORDED_IN_ARCHIVE',
            'note': 'Git objects verify sources at the declared commit; they do not independently bind the executed binary.'}
    mutants = load('experiments/p1/independent-fault-set.json')
    decoded = [dict(zip(mutants['mutantColumns'], row)) for row in mutants['mutants']]
    score = import_score()
    by_matrix = {}
    for matrix, expected in mutants['byMatrix'].items():
        rows = [{'final': r['hand'] or r['tool']} for r in decoded if r['key'].startswith(matrix + '-')]
        actual = score(rows)
        by_matrix[matrix] = {'recomputed': actual, 'matchesArchive': actual == expected}
    p1c = load('experiments/p1/external-renderer.json')
    checks = {
        'frozenSourcesMatch': all(x['matches'] for x in frozen_checks),
        'p1bScoresRecompute': all(x['matchesArchive'] for x in by_matrix.values()),
        'p3eSourcesMatchComparison': all(x['allComparedSourcesMatch'] for x in comparisons.values()),
        'p3ePlansPrecedeRecordedCode': all(x['planCommitIsAncestor'] for x in comparisons.values()),
        'p1cThreeRecordedRounds': len(p1c['tally']) == 3,
    }
    qualitative = qualitative_provenance(qualitative_manifest) if qualitative_manifest else {'status': 'NOT_REQUESTED'}
    if qualitative_manifest:
        checks['qualitativeProvenanceHashesMatch'] = qualitative['allArtifactsMatch']
    current = current_product_receipt(current_receipt, current_ref) if current_receipt else {'status': 'NOT_REQUESTED'}
    if current_receipt:
        checks['currentP3eArtifactsValid'] = current['valid']
    artifacts = [
        ('P1-A', 'experiments/p1/alternative-designs.json', 'INPUT_AND_DATA_CASES_RECORDED'),
        ('P1-A-code', 'experiments/p1/alternative-designs-code-faults.json', 'CODE_FAULT_CASES_RECORDED_WITH_DEVIATIONS'),
        ('P1-B', 'experiments/p1/independent-fault-set.json', 'MUTANT_ROWS_RECORDED'),
        ('P1-B-reading', 'experiments/p1/survivor-reading.json', 'AI_ASSISTED_QUALITATIVE_CODING'),
        ('P1-C', 'experiments/p1/external-renderer.json', 'THREE_ROUNDS_RECORDED_NOT_INDEPENDENT_TEAM'),
        ('P2-A', 'experiments/p2-a/multiple-check.json', 'STATIC_STAGE_ONLY_NO_GENERATION'),
        ('P2-oracle-reading', 'experiments/rq-c/oracle-audit.json', 'AI_ASSISTED_EXPLORATORY_RESCORE'),
        ('P2-verifier-reasons', 'experiments/rq-c/verifier-reasons.json', 'AI_ASSISTED_QUALITATIVE_CODING'),
        ('P3-tables', 'experiments/memory/answerable-tables.json', 'RECOMPUTED_TABLES_RECORDED'),
        ('P3-C-LangChain', 'experiments/p3-c/langchain.json', 'COMPONENT_PRECHECK_NO_POLICY_COMPARISON'),
        ('P3-C-LlamaIndex', 'experiments/p3-c/llamaindex.json', 'COMPONENT_PRECHECK_NO_POLICY_COMPARISON'),
        ('P3-C-Mem0', 'experiments/p3-c/mem0.json', 'TURN_STORAGE_INFER_FALSE'),
        ('P3-D', 'experiments/memory/embedding-check.json', 'ONE_EMBEDDING_MODEL_RECORDED'),
        ('P3-E', 'experiments/memory/product-path.json', 'HISTORICAL_PRODUCT_SNAPSHOT_ONLY'),
        ('P3-scorer-survey', 'experiments/memory/scorer-survey.json', 'AI_ASSISTED_SOURCE_CODING_NOT_PERFORMANCE'),
    ]
    inventory = [{'item': item, 'path': path, 'sha256': sha((ROOT/path).read_bytes()), 'scope': scope}
                 for item, path, scope in artifacts]
    policies = policy_comparison_receipt(policy_receipt, current_ref) if policy_receipt else {'status': 'NOT_SELECTED'}
    if policy_receipt:
        checks['currentP3PolicyArtifactsValid'] = policies['valid']
    return {
        'audit': '2026-11-03 supervisor review against local AIJADE evidence',
        'comparisonBasis': current_ref or 'working-tree',
        'localHead': git('rev-parse', 'HEAD').decode().strip(),
        'worktreeModified': bool(git('status', '--porcelain')),
        'newScientificRun': False, 'modelCalls': 0,
        'checks': checks, 'frozenSources': frozen_checks,
        'productVersionComparison': comparisons, 'p1bRecomputation': by_matrix,
        'qualitativeProvenance': qualitative,
        'currentP3e': current,
        'currentP3Policies': policies,
        'artifacts': inventory,
        'interpretation': {
            'archiveStatistics': 'Existing records can be recomputed; unchanged archives are not new observations.',
            'currentProduct': 'VERSION_MATCH_ONLY' if checks['p3eSourcesMatchComparison'] else 'DO_NOT_TRANSFER_ARCHIVED_P3E_METRICS',
            'recallChangeAfterSourceChanges': 'CURRENT_FIXED_CONFIGURATION_RECORDED_NOT_A_CAUSAL_VERSION_EFFECT' if current.get('valid') else 'NOT_MEASURED_BY_THIS_AUDIT',
            'ch7': 'NOT_RUN; backend, frozen checks/adapter and held-out batch remain separate prerequisites.',
            'host2': 'AUTHOR_REPORT: CPU replacement unavailable before January 2027; no hardware qualification inferred.',
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--current-ref')
    parser.add_argument('--require-current-version', action='store_true')
    parser.add_argument('--qualitative-provenance', type=Path,
                        help='Correction manifest for AI-assisted interpretations; verifies original artifact hashes without rewriting them')
    parser.add_argument('--current-product-receipt', type=Path,
                        help='Validate a new full-corpus shared-runtime receipt separately from historical v1 figures')
    parser.add_argument('--policy-receipt', type=Path,
                        help='Validate configured full policy comparisons separately from historical component pre-checks')
    args = parser.parse_args()
    result = audit(args.current_ref, args.qualitative_provenance, args.current_product_receipt, args.policy_receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not result['checks']['frozenSourcesMatch'] or not result['checks']['p1bScoresRecompute']:
        return 2
    if not result['checks'].get('qualitativeProvenanceHashesMatch', True):
        return 4
    if not result['checks'].get('currentP3eArtifactsValid', True):
        return 5
    if not result['checks'].get('currentP3PolicyArtifactsValid', True):
        return 6
    if args.require_current_version and not (result['checks']['p3eSourcesMatchComparison'] or result['checks'].get('currentP3eArtifactsValid') or result['checks'].get('currentP3PolicyArtifactsValid')):
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
