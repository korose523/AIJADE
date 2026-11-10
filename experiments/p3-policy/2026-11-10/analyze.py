#!/usr/bin/env python3
"""Validate complete raw configured-policy captures and compute paired conversation results.

Standard library only. No original evidence is overwritten and no model is called.
The conversation, not its questions or memories, is the resampling unit.
"""
import argparse
from collections import Counter, defaultdict
import datetime as dt
import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics
import struct

SEED = 20261110
B = 10000
HEADER = 'Things you remember about the user (use only when relevant):\n'
MARKER = '\n[Truncated by the product character budget.]'
POLICIES = ['6-newest', '6-server', '60-newest', '60-server']
CELLS = ['on-own', 'on-relevance', 'off-own', 'off-relevance']
STAGES = ['stored', 'pool', 'above', 'response', 'kept', 'planned', 'prompt']
_rng = random.Random(SEED)
SAMPLES = [[_rng.randrange(10) for _ in range(10)] for _ in range(B)]


def load(path):
    with (gzip.open(path, 'rt') if str(path).endswith('.gz') else Path(path).open()) as f:
        return json.load(f)


def lines(path):
    with gzip.open(path, 'rt') as f:
        for line in f:
            yield json.loads(line)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quantile(xs, p):
    pos = (len(xs) - 1) * p
    lower = int(pos)
    upper = min(lower + 1, len(xs) - 1)
    return xs[lower] + (xs[upper] - xs[lower]) * (pos - lower)


def ci(values):
    ordered = sorted(values)
    return [round(quantile(ordered, 0.025), 6), round(quantile(ordered, 0.975), 6)]


def estimate(values):
    assert len(values) == 10 and all(math.isfinite(x) for x in values)
    return {'mean': round(statistics.fmean(values), 6),
            'ci95': ci([statistics.fmean(values[i] for i in sample) for sample in SAMPLES]),
            'conversationValues': values}


def contrast(a, b):
    differences = [x - y for x, y in zip(a, b)]
    result = estimate(differences)
    observed = abs(statistics.fmean(differences))
    extreme = sum(abs(statistics.fmean(sign * value for sign, value in zip(signs, differences))) >= observed - 1e-12
                  for signs in itertools.product([-1, 1], repeat=10))
    result['signFlipP'] = extreme / 1024
    return result


def holm(family):
    ordered = sorted(family, key=lambda r: r.get('signFlipP', 1.0))
    previous = 0
    for rank, result in enumerate(ordered):
        previous = max(previous, min(1, (len(ordered) - rank) * result.get('signFlipP', 1.0)))
        result['holmP'] = previous if 'signFlipP' in result else None


def bounded_contrast(lower, upper, coefficients):
    low = [sum(weight * (lower[cell][i] if weight > 0 else upper[cell][i]) for cell, weight in coefficients.items()) for i in range(10)]
    high = [sum(weight * (upper[cell][i] if weight > 0 else lower[cell][i]) for cell, weight in coefficients.items()) for i in range(10)]
    return {'mean': None, 'pointIdentified': False,
            'identificationBounds': [round(statistics.fmean(low), 6), round(statistics.fmean(high), 6)],
            'lower': estimate(low), 'upper': estimate(high), 'signFlipPStatus': 'not imputed; multiplicity slot retained conservatively'}


def utf16(text):
    return len(text.encode('utf-16-le')) // 2


def observed(system, planned, contents):
    assert system is not None
    count = system.count(HEADER)
    if count == 0:
        return 'absent', []
    assert count == 1 and planned, 'unexplained memory block'
    texts = [contents[key] for key in planned]
    if len(set(texts)) != len(texts) or any(HEADER in text or MARKER in text for text in texts):
        return 'ambiguous-source', None
    expected = HEADER + '\n'.join('- ' + text for text in texts)
    actual = system[system.index(HEADER):]
    if actual.startswith(expected) and (len(actual) == len(expected) or actual[len(expected)] == '\n'):
        return 'complete', planned
    cut = actual.find(MARKER)
    assert 0 <= cut < len(expected) and expected.startswith(actual[:cut]), 'unexplained actual prompt'
    full = []
    end = utf16(HEADER)
    for i, key in enumerate(planned):
        end += (1 if i else 0) + 2 + utf16(contents[key])
        if end <= utf16(actual[:cut]):
            full.append(key)
    assert utf16(actual[:cut] + MARKER) <= 4000
    return 'truncated', full


def rows_by_key(path, expected_cells, cell_key):
    rows = {}
    for row in lines(path):
        cell = cell_key(row)
        assert cell in expected_cells
        key = (row['c'], row['q'], cell)
        assert key not in rows, ('duplicate raw row', key)
        rows[key] = row
    return rows


def evidence_id(c, source):
    return 'ep_locomo-%s-%s' % (c, source.replace(':', '-'))


def product_rows(folder, mode, corpus):
    data = rows_by_key(folder / mode / ('product-%s.jsonl.gz' % mode), POLICIES, lambda r: r['policy'])
    assert len(data) == 7944
    receipt = load(folder / mode / ('product-%s-receipt.json' % mode))
    assert receipt['rows'] == 7944 and receipt['baselines'] == 1986 and receipt['replayMisses'] == 0
    assert receipt['planCommit'] == '132bfda51b95fd4b0ebfc23304142d56bfcb455b'
    assert all(receipt['codeCommit'] in b['informationalVersion'] for b in receipt['binaries'])
    states = Counter()
    for c, conv in enumerate(corpus):
        stored = load(folder / mode / ('store-%s-%s.json.gz' % (mode, c)))
        contents = {r['Id']: r['Content'] for r in stored}
        dates = {r['Id']: r['CreatedAt'] for r in stored}
        assert len(stored) == len(conv['turns'])
        for turn in conv['turns']:
            source_id = evidence_id(c, turn['id'])
            assert contents[source_id] == turn['content']
            when = dt.datetime.fromisoformat(dates[source_id].replace('Z', '+00:00'))
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.timezone.utc)
            assert round(when.timestamp() * 1000) == turn['createdAt']
        for q, question in enumerate(conv['questions']):
            expected_gold = {evidence_id(c, source) for source in question['evidence']}
            for cell in POLICIES:
                row = data[(c, q, cell)]
                assert row['completed'] and row['mode'] == mode
                assert row['searches'][0]['Query'] == question['question']
                assert (c + q + row['position']) % 4 == POLICIES.index(cell)
                assert row['answerable'] == (question['category'] != 5)
                assert set(row['goldIds']) == expected_gold and row['evidence'] == len(expected_gold)
                assert row['located'] == len(expected_gold & contents.keys())
                assert hashlib.sha256(row['rawSystem'].encode()).hexdigest() == row['systemSha256']
                union = []
                for search in row['searches']:
                    assert search['Status'] == 200 and search['Limit'] == int(cell.split('-')[0])
                    items = json.loads(search['RawBody'])['items']
                    assert [r['id'] for r in items] == search['Ids']
                    for item in items:
                        assert item['content'] == contents[item['id']]
                        if item['id'] not in union:
                            union.append(item['id'])
                assert row['responseIds'] == union
                kept = [key for key in union if contents[key].strip().casefold() != question['question'].strip().casefold()]
                assert row['keptIds'] == kept
                planned = (sorted(kept, key=lambda key: dates[key], reverse=True) if cell.endswith('newest') else kept)[:5]
                assert row['plannedIds'] == planned
                state, actual = observed(row['rawSystem'], planned, contents)
                assert state == row['state'] and actual == row['observedIds']
                assert row['prompt'] == (None if actual is None else len(set(actual) & expected_gold))
                sets = [set(contents), set(row['poolIds']), set(row['aboveIds']), set(union), set(kept), set(planned)]
                assert all(b <= a for a, b in zip(sets, sets[1:]))
                for stage, ids in zip(STAGES[:-1], sets):
                    assert row[stage] == len(ids & expected_gold)
                if actual is not None:
                    assert set(actual) <= set(planned)
                states[state] += 1
    return data, receipt, dict(states)


def external_rows(folder, system, corpus):
    base = folder / 'external' / system
    path = base / (system + '.jsonl.gz')
    data = rows_by_key(path, CELLS, lambda r: r['policy'] + '-' + r['scorer'])
    prompts = rows_by_key(base / (system + '-prompts.jsonl.gz'), CELLS, lambda r: r['policy'] + '-' + r['scorer'])
    assert len(data) == len(prompts) == 7944
    receipt = load(base / 'receipt.json')
    capture_receipt = load(base / (system + '-prompts.jsonl.gz.receipt.json'))
    assert sha(path) == receipt['journalSha256'] == capture_receipt['inputSha256']
    assert receipt['rows'] == capture_receipt['rows'] == 7944
    assert receipt['planCommit'] == capture_receipt['planCommit'] == '132bfda51b95fd4b0ebfc23304142d56bfcb455b'
    assert receipt['codeCommit'] == capture_receipt['codeCommit']
    assert receipt['codeCommit'] in capture_receipt['informationalVersion']
    states = Counter()
    lengths = []
    access_rows = 0
    tie_rows = 0
    cutoff_ties = 0
    for c, conv in enumerate(corpus):
        snapshot = load(base / ('store-%s.json.gz' % c))
        contents = {t['id']: t['content'] for t in conv['turns']}
        sources = set(contents)
        lengths.extend(utf16(t['content']) for t in conv['turns'])
        if system == 'langchain':
            state = {}
            for cell in CELLS:
                assert len(snapshot[cell]) == len(sources)
                assert {x['source'] for x in snapshot[cell]} == sources
                assert all(x['content'] == contents[x['source']] for x in snapshot[cell])
                state[cell] = {x['source']: x['lastAccess'] for x in snapshot[cell]}
        else:
            assert len(snapshot['items']) == len(snapshot['writes']) == len(sources)
            assert {x['metadata']['source_turn'] for x in snapshot['items']} == sources
            assert all(x['memory'] == contents[x['metadata']['source_turn']] for x in snapshot['items'])
        for q, question in enumerate(conv['questions']):
            reference_pool = set(data[(c, q, CELLS[0])]['poolIds'])
            assert all(set(data[(c, q, cell)]['poolIds']) == reference_pool for cell in CELLS), 'external cells changed the candidate pool'
            for cell in CELLS:
                row = data[(c, q, cell)]
                capture = prompts[(c, q, cell)]
                gold = set(question['evidence'])
                assert set(row['gold']) == gold and row['answerable'] == (question['category'] != 5)
                assert row['question'] == question['question']
                assert set(row['poolIds']) <= sources and set(row['aboveIds']) <= set(row['poolIds'])
                assert len(row['poolIds']) == len(set(row['poolIds']))
                if system == 'langchain':
                    for candidate in row['candidates']:
                        assert candidate['lastAccess'] == state[cell][candidate['source']]
                        now = dt.datetime.fromisoformat(candidate['time'])
                        expected_time = dt.datetime(2026, 11, 10, 12) + dt.timedelta(minutes=q)
                        assert now == expected_time
                        old = dt.datetime.fromisoformat(candidate['lastAccess'])
                        relevance = candidate['relevance'] if candidate['relevance'] is not None else 0.0
                        expected = 0.99 ** ((now - old).total_seconds() / 3600) + relevance
                        if candidate['nativeOwnType'] == 'float32':
                            f32 = lambda x: struct.unpack('f', struct.pack('f', x))[0]
                            expected = f32(f32(0.99 ** ((now - old).total_seconds() / 3600)) + f32(relevance))
                        assert abs(candidate['own'] - expected) < 1e-12
                        used = relevance if row['scorer'] == 'relevance' else expected
                        assert abs(candidate['used'] - used) < 1e-12
                    full_ranked = sorted(row['candidates'], key=lambda x: -x['used'])
                    ranked = full_ranked[:8]
                    assert [r['source'] for r in ranked] == [r['source'] for r in row['delivered']]
                    for update in row['accessWrites']:
                        assert update['before'] == state[cell][update['source']]
                        assert update['retained'] == (row['policy'] == 'on')
                        if update['retained']:
                            state[cell][update['source']] = update['written']
                    access_rows += bool(row['accessWrites'])
                    tie_rows += row['rankTies'] > 0
                    cutoff_ties += len(full_ranked) > 8 and full_ranked[7]['used'] == full_ranked[8]['used']
                else:
                    threshold = 0.1 if row['policy'] == 'on' else 0.0
                    assert row['threshold'] == threshold
                    passing = [x for x in row['candidates'] if x['semantic'] >= threshold]
                    assert set(row['aboveIds']) == {x['source'] for x in passing}
                    for candidate in passing:
                        candidate['expectedScore'] = min(candidate['semantic'], 1.0) if row['scorer'] == 'relevance' else min(
                            (candidate['semantic'] + candidate['bm25'] + candidate['entity']) / candidate['divisor'], 1.0)
                    full_ranked = sorted(passing, key=lambda x: -x['expectedScore'])
                    ranked = full_ranked[:8]
                    tie_rows += any(a['expectedScore'] == b['expectedScore'] for a, b in zip(full_ranked, full_ranked[1:]))
                    cutoff_ties += len(full_ranked) > 8 and full_ranked[7]['expectedScore'] == full_ranked[8]['expectedScore']
                    assert [x['source'] for x in ranked] == [x['source'] for x in row['delivered']]
                    assert all(abs(a['expectedScore'] - b['score']) < 1e-12 for a, b in zip(ranked, row['delivered']))
                assert len(row['delivered']) <= 8
                assert all(x['content'] == contents[x['source']] for x in row['delivered'])
                planned = [x['source'] for x in row['delivered'][:5]]
                assert capture['plannedIds'] == planned and capture['completed']
                assert hashlib.sha256(capture['rawSystem'].encode()).hexdigest() == capture['systemSha256']
                obs_state, actual = observed(capture['rawSystem'], planned, contents)
                assert capture['state'] == obs_state and capture['observedIds'] == actual
                assert capture['promptGold'] == (None if actual is None else len(set(actual) & gold))
                row['prompt'] = capture['promptGold']
                row['planned'] = len(set(planned) & gold)
                row['evidence'] = len(gold)
                row['located'] = len(gold & sources)
                row['stored'] = row['located']
                row['pool'] = len(set(row['poolIds']) & gold)
                row['above'] = len(set(row['aboveIds']) & gold)
                row['delivered8'] = len({x['source'] for x in row['delivered']} & gold)
                row['hit8'] = int(row['delivered8'] > 0)
                states[obs_state] += 1
    lengths.sort()
    unit = {'items': len(lengths), 'unit': 'source turn', 'sourceTurnsPerItemMedian': 1, 'sourceTurnsPerItemMax': 1,
            'lengthUnit': 'UTF-16 code units', 'median': statistics.median(lengths), 'q1': quantile(lengths, .25),
            'q3': quantile(lengths, .75), 'max': max(lengths)}
    switch = {}
    for name, a_cell, b_cell in [('policyUnderOwn', 'on-own', 'off-own'), ('scorePolicyOn', 'on-own', 'on-relevance')]:
        changed = gold_changed = mask_changed = 0
        for c, conv in enumerate(corpus):
            for q in range(len(conv['questions'])):
                a, b = data[(c, q, a_cell)], data[(c, q, b_cell)]
                changed += [r['source'] for r in a['delivered']] != [r['source'] for r in b['delivered']]
                gold_changed += a['delivered8'] != b['delivered8']
                mask_changed += set(a['aboveIds']) != set(b['aboveIds'])
        switch[name] = {'questions': 1986, 'differentOrderedTop8': changed, 'differentGoldCountsAt8': gold_changed,
                        'differentThresholdMasks': mask_changed}
    return data, receipt, {'states': dict(states), 'itemUnits': unit, 'rowsWithAccessChanges': access_rows,
                           'rowsWithRankTies': tie_rows, 'rowsWithExactCutoffTieAt8': cutoff_ties,
                           'candidatePoolsMatchedAcrossAllCells': True, 'switchDiagnostics': switch}


def select(corpus, population):
    eligible = []
    count = 0
    no_evidence = 0
    unlocated = 0
    for c, conv in enumerate(corpus):
        source = {t['id'] for t in conv['turns']}
        for q, question in enumerate(conv['questions']):
            if population != 'all' and question['category'] == 5:
                continue
            count += 1
            gold = set(question['evidence'])
            no_evidence += not gold
            unlocated += bool(gold - source)
            denominator = len(gold & source) if population == 'located' else len(gold)
            if denominator:
                eligible.append((c, q, denominator))
    return eligible, {'questions': count, 'eligibleQuestions': len(eligible), 'noEvidenceListed': no_evidence, 'unlocatedEvidenceQuestions': unlocated}


def values(data, cell, eligible, field, hit=False, upper=False):
    by_conv = defaultdict(list)
    unknown = 0
    for c, q, denominator in eligible:
        row = data[(c, q, cell)]
        value = row[field]
        if value is None:
            unknown += 1
            value = row['planned'] if upper else 0
        by_conv[c].append(float(value) if hit else value / denominator)
    assert set(by_conv) == set(range(10))
    return [statistics.fmean(by_conv[c]) for c in range(10)], unknown


def summarize(data, cells, eligible, fields):
    result = {}
    for cell in cells:
        estimates = {}
        arrays = {}
        for field in fields:
            array_, unknown = values(data, cell, eligible, field, hit=field == 'hit8')
            arrays[field] = array_
            if unknown:
                upper, _ = values(data, cell, eligible, field, upper=True)
                estimates[field] = {'mean': None, 'pointIdentified': False, 'unknownQuestions': unknown,
                                    'identificationBounds': [round(statistics.fmean(array_), 6), round(statistics.fmean(upper), 6)],
                                    'lower': estimate(array_), 'upper': estimate(upper)}
            else:
                estimates[field] = {**estimate(array_), 'pointIdentified': True, 'unknownQuestions': 0}
        losses = {}
        for a, b in zip(fields, fields[1:]):
            if a == 'hit8' or b == 'hit8':
                continue
            if estimates[a]['pointIdentified'] and estimates[b]['pointIdentified']:
                losses[a + '->' + b] = estimate([x - y for x, y in zip(arrays[a], arrays[b])])
        if estimates['prompt']['pointIdentified']:
            losses['pool->prompt'] = estimate([x - y for x, y in zip(arrays['pool'], arrays['prompt'])])
        result[cell] = {'recall': estimates, 'loss': losses}
    return result


def d_effect(data, eligible):
    cells = {cell: values(data, cell, eligible, 'hit8', hit=True)[0] for cell in CELLS}
    scoring = contrast(cells['on-own'], cells['on-relevance'])
    policy = contrast(cells['on-own'], cells['off-own'])
    ds = scoring['conversationValues']
    dp = policy['conversationValues']
    point = abs(statistics.fmean(ds)) - abs(statistics.fmean(dp))
    interval = ci([abs(statistics.fmean(ds[i] for i in sample)) - abs(statistics.fmean(dp[i] for i in sample)) for sample in SAMPLES])
    reading = 'scoring larger in this configuration' if interval[0] > 0 else 'policy larger in this configuration' if interval[1] < 0 else 'sizes not distinguished on this corpus'
    return {'metric': 'macro conversation hit-any recall@8', 'scoringOwnMinusRelevancePolicyOn': scoring,
            'policyOnMinusOffOwnScorer': policy, 'D': {'mean': round(point, 6), 'ci95': interval, 'reading': reading},
            'scope': 'named configured write/read policy, conditional captured vectors; no population-wide policy verdict'}


def analyze(folder, corpus_path, external_folder=None):
    corpus = load(corpus_path)
    assert len(corpus) == 10 and sum(len(c['questions']) for c in corpus) == 1986
    result = {'schema': 'aijade.p3.policy.summary.v1', 'planCommit': '132bfda51b95fd4b0ebfc23304142d56bfcb455b',
              'recordingAmendmentCommit': '87e2f3189ad3eb7fdabd4e45ae298cf8d84b78e2',
              'corpusSha256': '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4',
              'corpusExportSha256': sha(corpus_path),
              'bootstrapSeed': SEED, 'bootstrapReplicates': B, 'resamplingUnit': 'conversation',
              'percentileMethod': 'linear interpolation of sorted resamples', 'newModelCalls': 0,
              'product': {}, 'external': {}}
    product_family = []
    external_family = []
    product_commits = set()
    external_commits = set()
    for mode in ['text', 'embedding']:
        data, receipt, states = product_rows(folder, mode, corpus)
        product_commits.add(receipt['codeCommit'])
        item = {'validation': {'rows': len(data), 'questionsPerCell': 1986, 'cells': 4, 'states': states, 'baselineIdMatches': receipt['baselines']}, 'populations': {}}
        for population in ['answerable', 'all', 'located']:
            eligible, counts = select(corpus, population)
            population_result = {'population': counts, 'policies': summarize(data, POLICIES, eligible, STAGES)}
            contrasts = {}
            arrays = {cell: values(data, cell, eligible, 'prompt') for cell in POLICIES}
            lower = {cell: pair[0] for cell, pair in arrays.items()}
            upper = {cell: values(data, cell, eligible, 'prompt', upper=True)[0] for cell in POLICIES}
            specifications = {'serverOrderAt6': {'6-server': 1, '6-newest': -1},
                              'widenAtServerOrder': {'60-server': 1, '6-server': -1},
                              'interaction': {'60-server': 1, '60-newest': -1, '6-server': -1, '6-newest': 1}}
            for name, coefficients in specifications.items():
                if any(arrays[cell][1] for cell in coefficients):
                    contrasts[name] = bounded_contrast(lower, upper, coefficients)
                else:
                    plus = [sum(weight * lower[cell][i] for cell, weight in coefficients.items() if weight > 0) for i in range(10)]
                    minus = [sum(-weight * lower[cell][i] for cell, weight in coefficients.items() if weight < 0) for i in range(10)]
                    contrasts[name] = {**contrast(plus, minus), 'pointIdentified': True}
            if not any(unknown for _, unknown in arrays.values()):
                baseline_loss = population_result['policies']['6-newest']['loss']['pool->prompt']['mean']
                population_result['baselineLossRecoveryShare'] = {cell: ((population_result['policies'][cell]['recall']['prompt']['mean'] -
                    population_result['policies']['6-newest']['recall']['prompt']['mean']) / baseline_loss if baseline_loss > 0 else None) for cell in POLICIES}
            if population == 'answerable':
                product_family.extend(contrasts.values())
            population_result['contrasts'] = contrasts
            item['populations'][population] = population_result
        result['product'][mode] = item
    for system in ['langchain', 'mem0']:
        data, receipt, validation = external_rows(external_folder or folder, system, corpus)
        external_commits.add(receipt['codeCommit'])
        item = {'validation': {'rows': len(data), 'questionsPerCell': 1986, 'cells': 4, **validation}, 'populations': {}}
        for population in ['answerable', 'all', 'located']:
            eligible, counts = select(corpus, population)
            item['populations'][population] = {'population': counts, 'policies': summarize(data, CELLS, eligible,
                ['stored', 'pool', 'above', 'delivered8', 'planned', 'prompt', 'hit8']), 'effects': d_effect(data, eligible)}
            if population == 'answerable':
                effects = item['populations'][population]['effects']
                external_family.extend([effects['scoringOwnMinusRelevancePolicyOn'], effects['policyOnMinusOffOwnScorer']])
        result['external'][system] = item
    assert len(product_commits) == len(external_commits) == 1, 'mixed execution commits within a study'
    result['executionCodeCommits'] = {'product': product_commits.pop(), 'external': external_commits.pop()}
    holm(product_family)
    holm(external_family)
    result['multiplicity'] = {'productPrimaryFamily': len(product_family), 'externalSignedPrimaryFamily': len(external_family),
                              'method': 'Holm on exact paired-conversation sign-flip p; D intervals descriptive'}
    result['scope'] = 'All cells/questions of named configurations, actual prompt captures, conditional replay of existing vectors; no default LLM fact extraction, whole LangChain agent, full Web/QQ or answer accuracy.'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--external-folder', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    output = analyze(args.folder, args.corpus, args.external_folder)
    with args.out.open('x') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
    print(json.dumps({'status': 'VALIDATED_AND_SUMMARIZED', 'codeCommits': output['executionCodeCommits'],
                      'productConditions': 8, 'externalConditions': 8, 'newModelCalls': 0}))
