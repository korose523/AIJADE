#!/usr/bin/env python3
"""Validate observed-prompt v2 captures and summarize a fixed full-corpus P3-E run.

No old v1 files are read or overwritten. Usage: summarize.py RUN_ROOT --corpus FILE --out FILE
The actual-request observer is cross-checked here from retained text/store/transport records.
"""
import argparse
import gzip
import hashlib
import json
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

SHA = '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
HEADER = 'Things you remember about the user (use only when relevant):\n'
MARKER = '\n[Truncated by the product character budget.]'
STAGES = ['stored', 'pool', 'above', 'response', 'kept', 'plannedPrompt', 'prompt']
SEED = 20261110


def check(ok, message):
    if not ok:
        raise ValueError(message)


def resolved(path):
    return path if path.exists() else path.with_name(path.name + '.gz')


def load(path):
    path = resolved(path)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        return json.load(stream)


def raw_digest(path):
    path = resolved(path)
    opener = gzip.open if path.suffix == '.gz' else open
    h = hashlib.sha256()
    with opener(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def visible(system, planned):
    if system is None:
        return None, 'not-captured'
    if HEADER not in system:
        return [], 'absent'
    if system.count(HEADER) != 1 or not planned:
        return None, 'unexplained-block'
    contents = [p['Content'] for p in planned]
    if len(set(contents)) != len(contents) or len({p['Id'] for p in planned}) != len(planned) or any(HEADER in s or MARKER in s for s in contents):
        return None, 'ambiguous-source'
    block = HEADER + '\n'.join('- ' + s for s in contents)
    actual = system[system.index(HEADER):]
    if actual.startswith(block) and (len(actual) == len(block) or actual[len(block)] == '\n'):
        return [p['Id'] for p in planned], 'complete'
    cut = actual.find(MARKER)
    if not 0 <= cut < len(block) or not block.startswith(actual[:cut]):
        return None, 'unexplained-block'
    prefix = HEADER
    full = []
    for i, item in enumerate(planned):
        prefix += ('\n' if i else '') + '- ' + item['Content']
        if len(prefix) <= cut:
            full.append(item['Id'])
    return full, 'truncated'


def validate(folder, data, corpus):
    check(data['schema'] == 'aijade.product-path.observed-prompt.v2', 'wrong schema')
    check(data['entry'] == 'shared-memory-only' and data['corpusSha256'] == SHA, 'wrong entry/corpus')
    check(data['planCommit'] == 'd1527e01d19c7e5524a0afa3f003d741a9d131a6', 'wrong pre-execution plan')
    rows = data['rows']
    expected = {(c, q) for c, conv in enumerate(corpus) for q in range(len(conv['qa']))}
    keys = [(r['c'], r['q']) for r in rows]
    check(len(keys) == len(set(keys)) == len(expected) == 1986 and set(keys) == expected, 'incomplete or duplicate question coverage')
    check(sum(r['answerable'] for r in rows) == 1540, 'wrong primary question set')
    condition = data['condition']
    journal = resolved(folder / ('rows-shared-memory-only-' + condition + '.jsonl'))
    opener = gzip.open if journal.suffix == '.gz' else open
    with opener(journal, 'rt', encoding='utf-8') as stream:
        check([json.loads(line) for line in stream] == rows, 'durable journal/report differ')
    stores = {c: {p['Id']: p for p in load(folder / ('store-shared-memory-only-%s-%s.json.gz' % (condition, c)))} for c in range(10)}
    states = Counter()
    for r in rows:
        c, q = r['c'], r['q']
        question = corpus[c]['qa'][q]
        check(r['answerable'] == (question['category'] != 5), 'answerable classification changed')
        gold = {'ep_locomo-%s-%s' % (c, e.replace(':', '-')) for e in question.get('evidence', [])}
        check(r['evidence'] == len(gold), 'gold denominator changed')
        store = stores[c]
        check(r['stored'] == len(gold.intersection(store)), 'stored gold count differs')
        received = []
        check(len(r['searchTrace']) == r['searches'], 'missing server trace')
        for trace in r['searchTrace']:
            check(trace['status'] == 200, 'unsuccessful memory request')
            for item in json.loads(trace['rawBody'])['items']:
                check(item['id'] in store and item['content'] == store[item['id']]['Content'], 'server/store content differs')
                if item['id'] not in received:
                    received.append(item['id'])
        kept = [i for i in received if store[i]['Content'].strip().casefold() != question['question'].strip().casefold()]
        planned_ids = sorted(kept, key=lambda i: store[i]['CreatedAt'], reverse=True)[:5]
        check(r['plannedPromptIds'] == planned_ids, 'provider ordering differs')
        planned = [store[i] for i in planned_ids]
        observed, state = visible(r['rawSystem'], planned)
        check(state == r['promptState'], 'captured block classification differs')
        check(observed == r['observedFullItemIds'], 'full visible item IDs differ')
        check(r['prompt'] == (len(gold.intersection(observed)) if observed is not None else None), 'actual gold recall count differs')
        check(r['plannedPrompt'] == len(gold.intersection(planned_ids)), 'planned gold count differs')
        check(hashlib.sha256(r['rawSystem'].encode()).hexdigest() == r['systemSha256'], 'system capture hash differs')
        check(r['completed'] and not r['mismatch'], 'failed turn or response recomputation')
        check(all(0 <= r[s] <= r['evidence'] for s in STAGES if r[s] is not None), 'invalid stage count')
        known = [r[s] for s in STAGES if r[s] is not None]
        check(known == sorted(known, reverse=True), 'non-monotone delivery stages')
        states[state] += 1
    check(all(data[k] == 0 for k in ['turnsNotStored', 'failedTurns', 'responseMismatches', 'promptMismatches', 'embeddingObservationMisses']), 'run quality failure')
    return {'questions': len(rows), 'answerableQuestions': sum(r['answerable'] for r in rows), 'conversations': len(stores), 'states': dict(states), 'captureAndSourceChecks': 'PASS'}


def describe(rows, value):
    groups = defaultdict(list)
    for r in rows:
        v = value(r)
        if v is not None:
            groups[r['c']].append(v)
    means = [statistics.fmean(groups[c]) for c in sorted(groups)]
    if not means:
        return {'mean': None, 'ci95': None, 'questions': 0, 'conversations': 0}
    rng = random.Random(SEED)
    draws = sorted(statistics.fmean(rng.choices(means, k=len(means))) for _ in range(10000))
    return {'mean': round(statistics.fmean(means), 6), 'ci95': [round(draws[250], 6), round(draws[9750], 6)],
            'questions': sum(map(len, groups.values())), 'conversations': len(means)}


def share(stage, base='evidence'):
    return lambda r: r[stage] / r[base] if r[base] and r[stage] is not None else None


def difference(a, b):
    return lambda r: (r[a] - r[b]) / r['evidence'] if r['evidence'] and r[a] is not None and r[b] is not None else None


def part(rows, denominator='evidence'):
    eligible = [r for r in rows if r[denominator]]
    unknown = sum(r['prompt'] is None for r in eligible)
    out = {'questions': len(rows), 'eligibleQuestions': len(eligible), 'conversations': len({r['c'] for r in rows}),
           'noEvidenceListed': sum(not r['evidence'] for r in rows), 'evidenceNotLocated': sum(r['located'] < r['evidence'] for r in rows),
           'unknownEligiblePrompts': unknown, 'denominator': denominator,
           'recall': {s: describe(rows, share(s, denominator)) for s in STAGES},
           'primaryPointIdentified': unknown == 0,
           'counts': {'states': dict(Counter(r['promptState'] for r in rows)), 'termSearches': sum(r['termSearch'] for r in rows),
                      'firstSearchEmpty': sum(r['firstEmpty'] for r in rows), 'fewerThanFive': sum(r['fewerThanFive'] for r in rows),
                      'providerNotConsulted': sum(not r['providerConsulted'] for r in rows), 'echoDropped': sum(r['echoDropped'] for r in rows),
                      'plannedVersusObservedDifferent': sum(r['observedFullItemIds'] != r['plannedPromptIds'] for r in rows)}}
    if denominator == 'evidence':
        out['loss'] = {a + '->' + b: describe(rows, difference(a, b)) for a, b in zip(STAGES, STAGES[1:])}
        out['loss']['pool->prompt'] = describe(rows, difference('pool', 'prompt'))
        out['upstreamPreBudgetArm'] = {'serverTop5': describe(rows, share('serverTop5')), 'plannedNewest5': describe(rows, share('plannedPrompt')),
                                     'warning': 'These are pre-budget candidates, not an actually delivered equal-budget alternative.'}
    if unknown:
        out['secondaryCompleteCasePrompt'] = out['recall'].pop('prompt')
        out['primaryPromptBounds'] = {
            name: describe(rows, lambda r, fill=fill: (r['prompt'] / r[denominator] if r['prompt'] is not None else fill) if r[denominator] else None)
            for name, fill in [('lower', 0), ('upper', 1)]}
        if denominator == 'evidence':
            out['secondaryCompleteCaseLoss'] = out['loss'].pop('pool->prompt')
            out['primaryLossBounds'] = {name: describe(rows, lambda r, fill=fill: r['pool'] / r['evidence'] - (r['prompt'] / r['evidence'] if r['prompt'] is not None else fill) if r['evidence'] else None)
                                        for name, fill in [('lower', 1), ('upper', 0)]}
    return out


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('run_root', type=Path)
    parser.add_argument('--corpus', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    check(hashlib.sha256(args.corpus.read_bytes()).hexdigest() == SHA, 'corpus fingerprint differs')
    corpus = load(args.corpus)
    report = {'schema': 'aijade.p3e.current-summary.v1', 'plan': 'experiments/plans/2026-11-10-p3-e-shared-runtime.md',
              'planCommit': 'd1527e01d19c7e5524a0afa3f003d741a9d131a6', 'corpusSha256': SHA, 'bootstrapSeed': SEED,
              'bootstrapReplicates': 10000, 'resamplingUnit': 'conversation', 'conditions': {}}
    for condition in ['text', 'embedding']:
        folder = args.run_root / condition
        path = folder / ('product-path-v2-shared-memory-only-' + condition + '.json')
        data = load(path)
        valid = validate(folder, data, corpus)
        rows = data['rows']
        report['conditions'][condition] = {
            'declaredCodeCommit': data['declaredCodeCommit'], 'entry': data['entry'], 'scope': data['scope'], 'promptBudget': data['promptBudget'],
            'rawReportSha256': raw_digest(path), 'validation': valid,
            'answerable': part([r for r in rows if r['answerable']]), 'all': part(rows),
            'locatedEvidence': part([r for r in rows if r['answerable']], 'located')}
        old_path = Path(__file__).resolve().parents[3] / 'experiments/memory/product-path' / ('product-path-' + condition + '.json')
        old_data = load(old_path)
        old_rows = {(r['c'], r['q']): r for r in old_data['rows']}
        check(set(old_rows) == {(r['c'], r['q']) for r in rows}, 'historical comparison question keys differ')
        differences = defaultdict(list)
        changed = 0
        unknown = 0
        for r in rows:
            old = old_rows[r['c'], r['q']]
            check(old['evidence'] == r['evidence'] and old['answerable'] == r['answerable'], 'historical comparison denominator differs')
            if r['prompt'] is None:
                unknown += 1
                continue
            changed += r['prompt'] != old['prompt']
            if r['answerable'] and r['evidence']:
                differences[r['c']].append((r['prompt'] - old['prompt']) / r['evidence'])
        report['conditions'][condition]['historicalComparison'] = {
            'historicalRawReportSha256': hashlib.sha256(old_path.read_bytes()).hexdigest(), 'historicalCodeCommit': old_data['codeCommit'],
            'matchedQuestionKeys': len(rows), 'unknownCurrentPrompts': unknown, 'questionsWithDifferentGoldPromptCounts': changed,
            'macroPrimaryRecallDelta': statistics.fmean(statistics.fmean(v) for v in differences.values()) if not unknown else None,
            'scope': 'Descriptive paired point comparison on the same question keys; no causal version effect or general prompt equivalence is established.'}
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({c: {'validation': d['validation'], 'prompt': d['answerable'].get('recall', {}).get('prompt'), 'poolToPrompt': d['answerable'].get('loss', {}).get('pool->prompt')} for c, d in report['conditions'].items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
