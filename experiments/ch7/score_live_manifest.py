#!/usr/bin/env python3
"""Score actual known-scenario live records with explicit fresh-run provenance.

The frozen v1 scorer is an internal numerical window calculator only. Its old
re-encoding origin/interpretation are never propagated as live-run provenance.
"""
import argparse
import json
from pathlib import Path

from audit_retrieval_led import load, raw, sha
from comparison_manifest import require, score as window_calculator


def score_rows(rows, runtime, template):
    require(runtime['schema'] == 'aijade.ch7.live-case-manifest.v1' and runtime['purpose'] == 'known_development_qualification_only', 'live scope')
    require({c['caseId'] for c in runtime['cases']} == {c['caseId'] for c in template['cases']}, 'window template not bound to operational cases')
    result = window_calculator(rows, template)
    # Numerical fields only: never reuse the v1 data-origin label or explanation.
    return dict(arms=result['arms'], differencesC2MinusC1=result['differencesC2MinusC1'],
                rowIntegrityDiagnostics=result['rowIntegrityDiagnostics'],
                normalAcceptanceDefinition=result['normalAcceptanceDefinition'], round2SemanticActCorrectness='NOT_MEASURED')


def score_directory(root):
    receipt = load(root, 'receipt.json'); identity = load(root, 'input-identities.json')
    require(receipt['status'] == 'COMPLETE_LIVE_MANIFEST_KNOWN_OBSERVATIONS', 'incomplete live observation batch')
    runtime = load(root, 'runtime-manifest.json'); rows = load(root, 'cases.json'); template = load(root, 'window-template.json')
    require(sha(raw(root, 'runtime-manifest.json')) == identity['runtimeManifestSha256'], 'runtime manifest identity')
    require(sha(raw(root, 'window-template.json')) == identity['windowTemplateSha256'], 'window template identity')
    require(receipt['completedCases'] == len(rows) == 2 * len(runtime['cases']), 'complete observation population')
    return dict(schema='aijade.ch7.live-manifest-score.v1', status='COMPLETE_KNOWN_LIVE_RECORDS_SCORED',
                dataOrigin='Actual fresh execution of previously known scenarios, not renamed prior observations.',
                codeCommit=receipt['codeCommit'], receiptSha256=sha(raw(root, 'receipt.json')),
                actualRowsSha256=sha(raw(root, 'cases.json')), runtimeManifestSha256=identity['runtimeManifestSha256'],
                windowTemplateSha256=identity['windowTemplateSha256'], windowTemplateOrigin='Previous frozen integrity-window definitions; template source rows are not the actual data source.',
                knownDevelopmentPairs=len(runtime['cases']), measuredConditionRows=len(rows), heldOutCases=0, modelRequests=0,
                **score_rows(rows, runtime, template),
                interpretation='Known-scenario live-driver/dataflow qualification. No new held-out cases, fault-population inference, investigator blinding, independent human review or formal hardware qualification.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = json.dumps(score_directory(args.root), indent=2) + '\n'
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end='')
