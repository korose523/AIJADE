#!/usr/bin/env python3
"""Construct only the existing ten development inputs; no fresh held-out cases or seed."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from audit_retrieval_led import raw, load
from comparison_manifest import require

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / 'experiments/ch7/live-manifest-known-input-v1.json'
ORIGIN = ROOT / 'experiments/ch7/live-manifest-known-origin-v1.json'
PACKET_SHA = 'ea0285d60ade24313ee201eb2223fd63f0fb71461e9c9a7a2633deb33da62fb2'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def construct(repo):
    paired = repo / 'experiments/ch7/paired-development-2026-11-12'
    prepared = repo / 'experiments/ch7/manifest-preparation-2026-11-12'
    require(sha((paired / 'manifest.json').read_bytes()) == PACKET_SHA, 'original measured packet changed')
    aliases = load(prepared, 'source-to-alias-map.json')
    layout = load(paired, 'layout.json')
    scoring = load(paired, 'scoring-contract.json')
    selection = load(paired, 'selection.json')
    rules = {r['caseId']: r for r in scoring['cases']}
    semantic = next(r['caseId'] for r in scoring['cases'] if r['class'] == 'semantic_control')
    cases = []
    for row in layout['cases']:
        source_id = row['caseId']
        window = rules[source_id]['window']
        candidate = selection['unusable' if window == 'execution_failed' else 'usable']
        cid = aliases[source_id]
        operations = dict(execution='omit' if window == 'execution_unknown' else 'run',
                          mapperActOverride='celebrate' if window == 'wrong_allowed_act_in_round1' else None,
                          receiptCaseId=aliases[semantic] if window == 'execution_receipt_intent' else cid,
                          assetVersionOverride='different-asset' if window == 'asset_admission' else None,
                          claimedStage='pixels_observed' if window == 'claimed_receipt_stage' else 'behavior_overlay_pre_solve',
                          repeatOutcome=window == 'duplicate_invocation_2',
                          revokeBeforeReuse=window == 'revocation_before_round2',
                          failStateWrite=window == 'post_promotion_authority_write')
        cases.append(dict(caseId=cid, conditions=copy.deepcopy(row['conditions']), taskId=candidate['taskId'],
                          codeSha256=candidate['codeSha256'], requestedAct='comfort', operations=operations))
    runtime = dict(schema='aijade.ch7.live-case-manifest.v1', purpose='known_development_qualification_only',
                   originPacketManifestSha256=PACKET_SHA,
                   selectionSha256=sha(raw(paired, 'selection.json')),
                   sourceAliasMapSha256=sha(raw(prepared, 'source-to-alias-map.json')), cases=cases)
    sources = {str(p.relative_to(repo)): sha(p.read_bytes()) for p in [paired / 'manifest.json',
               prepared / 'source-to-alias-map.json', repo / 'experiments/ch7/paired-development-layout-v1.json',
               repo / 'experiments/ch7/paired-development-scoring-v1.json', repo / 'experiments/ch7/2026-11-12/selection.json']}
    origin = dict(schema='aijade.ch7.live-known-input-origin.v1', plan='1ffb94b', sourceCode='2be60d27593c68d1ab4b0cc35f893533397dd5c5',
                  purpose='Exact input construction from known scenarios, not held-out generation.',
                  sources=sources, casePairs=len(cases), conditionRows=sum(len(c['conditions']) for c in cases),
                  freshHeldoutCases=0, caseGenerationSeed=None,
                  runtimeContainsExpectedOutcome=False, adapterReceivesCaseClass=False,
                  derivation='Operations derive from the frozen window definitions and the existing balanced order. Runtime IDs are the prior alias map; the mapper override and other interventions are explicit data.')
    return runtime, origin


def encoded(value):
    return (json.dumps(value, indent=2) + '\n').encode('utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    runtime, origin = construct(ROOT)
    for p, obj in [(INPUT, runtime), (ORIGIN, origin)]:
        if args.write:
            require(not p.exists(), 'preserve existing input construction')
            p.write_bytes(encoded(obj))
        else:
            require(p.read_bytes() == encoded(obj), 'known input derivation changed: ' + str(p.name))
    print(json.dumps(dict(status='KNOWN_INPUT_CONSTRUCTION_PASS', pairs=10, freshHeldoutCases=0, runtimeSha256=sha(encoded(runtime)))))
