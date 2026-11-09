#!/usr/bin/env python3
"""Audit saved requests and calculate explicitly conditional device-time scenarios.

No model calls, correctness-based selection, or writes to the historical archives.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import statistics


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def analyze(repo, directory, fixture, first_swap):
    result = load(directory / 'result.json')
    expected = {item['id']: item for item in fixture['items']}
    checks, models = [], []
    for model in result['models']:
        alias = 'qwen7b' if model['model'].startswith('qwen') else 'llama8b'
        cases = []
        for request in model['requests']:
            case = directory / alias / request['id']
            body = load(case / 'request.json')
            item = expected[request['id']]
            assert sha(case / 'request.json') == request['requestSha256']
            assert body['options'] == fixture['sampling']
            assert body['model'] == model['model']
            assert body['stream'] is False
            assert body['messages'] == [{'role': 'user', 'content': item['prompt']}]
            assert hashlib.sha256(item['prompt'].encode()).hexdigest() == item['promptSha256']
            if 'responseSha256' in request:
                assert sha(case / 'response.json') == request['responseSha256']
            metrics = request.get('metrics', {})
            if request['status'] == 'COMPLETED':
                response = load(case / 'response.json')
                assert response['done'] is True and response['done_reason'] != 'length'
                assert response['model'] == model['model']
                loaded = request['loadedModelState']['models']
                assert len(loaded) == 1
                assert loaded[0]['digest'] == model['identity']['digest']
                assert loaded[0]['context_length'] == 4096
                checks.append(f'{alias}/{request["id"]}: body, reply and loaded identity verified')
            else:
                checks.append(f'{alias}/{request["id"]}: body verified; {request["status"]} retained')
            samples = [json.loads(line) for line in (case / 'telemetry.jsonl').read_text().splitlines()]
            assert samples and all(s['availableBytes'] >= 0 for s in samples)
            cases.append({'id': request['id'], 'kind': request['kind'], 'status': request['status'],
                          'observedWallSeconds': request['observedWallSeconds'], **metrics,
                          'telemetrySamples': len(samples),
                          'loadedSizeVramBytes': next(iter(request.get('loadedModelState', {}).get('models', [])), {}).get('size_vram')})
        complete = [c for c in cases if c['status'] == 'COMPLETED']
        warm = [c for c in complete if c['kind'] != 'startup']
        verdict = [c for c in complete if c['kind'] in ('verifier-A', 'verifier-B', 'format-A')]
        synthetic = [c for c in verdict if c['kind'] == 'format-A']
        speed = [c['generationTokensPerSecond'] for c in warm if c.get('generationTokensPerSecond')]
        models.append({'model': model['model'], 'digest': model['identity']['digest'],
                       'quantization': model['identity']['details']['quantization_level'],
                       'archiveDigestMatches': model['archiveDigestMatches'], 'status': model['status'],
                       'plannedRequests': len(expected), 'attemptedRequests': len(cases), 'completedRequests': len(complete),
                       'notAttemptedRequests': len(expected) - len(cases),
                       'coldWallSeconds': next((c.get('wallSeconds') for c in complete if c['kind'] == 'startup'), None),
                       'coldLoadSeconds': next((c['load_duration'] / 1e9 for c in complete if c['kind'] == 'startup'), None),
                       'warmGenerationTokensPerSecondRange': [min(speed), max(speed)] if speed else None,
                       'warmGenerationTokensPerSecondMedian': statistics.median(speed) if speed else None,
                       'syntheticFormatConforming': sum(c.get('verdictPrefixConforming', False) for c in synthetic),
                       'syntheticFormatMeasured': len(synthetic),
                       'verifierFormatConforming': sum(c.get('verdictPrefixConforming', False) for c in verdict),
                       'verifierFormatMeasured': len(verdict),
                       'baselineAvailableGiB': model['baseline']['availableBytes'] / 2**30,
                       'minimumAvailableGiB': model['minAvailableBytes'] / 2**30,
                       'baselineSwapGiB': model['baseline']['swapUsedBytes'] / 2**30,
                       'peakSwapGiB': model['maxSwapUsedBytes'] / 2**30,
                       'swapIncreaseGiB': model['swapIncreaseFromModelBaselineBytes'] / 2**30,
                       'swapPeakChangeFromFirstBaselineGiB': (model['maxSwapUsedBytes'] - first_swap) / 2**30,
                       'peakOwnedProcessRssGiB': model['peakOwnedProcessRssBytes'] / 2**30,
                       'modelElapsedSeconds': model['seconds'], 'cases': cases})
    classifier = load(directory / 'parser-classification.json')
    expected_rows = sum(m['verifierFormatMeasured'] for m in models)
    assert classifier['allMatch'] and len(classifier['rows']) == expected_rows
    assert all(m['archiveDigestMatches'] for m in models)
    assert result['serverVersionUnchanged']
    assert all(not m['stateAfterUnload']['models'] for m in result['models'])
    return {'directory': str(directory.relative_to(repo)), 'resultSha256': sha(directory / 'result.json'),
            'startedAt': result['startedAt'], 'endedAt': result['endedAt'], 'models': models,
            'checks': checks, 'existingParserAgrees': True, 'parserComparisons': expected_rows,
            'primaryExperiment': False, 'sourceHead': result['sourceHead'], 'sourceTreeDirty': result['sourceTreeDirty']}


def budget(phase, runs):
    models = {m['model']: m for m in phase['models']}
    rows = []
    for run in runs:
        model = models[run['model']]
        cases = {c['id']: c for c in model['cases'] if c['status'] == 'COMPLETED'}
        ids = ['cold-ready', 'warm-initial-longest', 'warm-retry-longest-code', 'warm-verifier-longest-' + run['verifierTemplate']]
        missing = [item for item in ids if item not in cases]
        row = {'run': run['run'], 'model': run['model'], 'template': run['verifierTemplate'],
               'counts': run['counts'], 'warmupCalls': run['warmupCalls'], 'available': not missing}
        if missing:
            row['reason'] = 'No uncensored measurement for: ' + ', '.join(missing)
        else:
            counts = run['counts']
            times = [cases[item]['wallSeconds'] for item in ids]
            seconds = times[0] + counts['initialGenerationCalls'] * times[1] + counts['retryGenerationCalls'] * times[2] + counts['verifierCalls'] * times[3]
            row.update({'observedClassWallSeconds': dict(zip(ids, times)), 'conditionalApiHours': seconds / 3600,
                        'conditionalApiHoursWith30PercentAllowance': seconds * 1.3 / 3600})
        rows.append(row)
    return {'phase': phase['directory'], 'rows': rows,
            'interpretation': 'Conditional API-time scenario only: archived call counts and one observed longest-by-character representative per class; not an upper bound, confidence interval, full-run prediction or commitment. New generations may change reply lengths, retries and verifier counts. Excludes sandbox/persistence, model switching, determinism passes, device qualification and public-benchmark/larger-model runs. The 30% allowance is an explicit planning assumption.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--phase', action='append', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError('Refusing to overwrite an analysis receipt')
    fixture = load(args.root / 'fixtures.json')
    for path, value in fixture['sourcesSha256'].items():
        assert sha(args.repo / path) == value, path
    counts = load(args.root / 'archived-call-counts.json')
    for run in counts['runs']:
        assert sha(args.repo / 'experiments/rq-c' / run['run'] / 'trials.jsonl') == run['sourceSha256']
        c = run['counts']
        assert c['steps'] == c['initialGenerationCalls'] + c['retryGenerationCalls'] + c['reusedSteps']
    first_swap = load(args.phase[0] / 'result.json')['models'][0]['baseline']['swapUsedBytes']
    phases = [analyze(args.repo, phase, fixture, first_swap) for phase in args.phase]
    deterministic_counts = load(args.root / 'determinism-call-counts.json')
    deterministic_runs = []
    for run, primary in zip(deterministic_counts['runs'], counts['runs'], strict=True):
        assert run['run'] == primary['run'] and run['sourceSha256'] == primary['sourceSha256']
        assert all(run['fullRun'][key] == value for key, value in primary['counts'].items())
        assert run['fullRun']['retriesWithoutEnvironmentOrCritique'] == 0
        assert run['firstFiveTrials']['retriesWithoutEnvironmentOrCritique'] == 0
        deterministic_runs.append({**run, 'counts': run['firstFiveTrials'], 'warmupCalls': 1})
    deterministic = []
    for phase in phases:
        scenario = budget(phase, deterministic_runs)
        for row, counted in zip(scenario['rows'], deterministic_counts['runs'], strict=True):
            row['passes'] = counted['determinismPasses']
            if row['available']:
                row['fivePassConditionalApiHours'] = row['conditionalApiHours'] * row['passes']
                row['fivePassConditionalApiHoursWith30PercentAllowance'] = row['conditionalApiHoursWith30PercentAllowance'] * row['passes']
        deterministic.append(scenario)
    text_comparisons = []
    if len(args.phase) == 2:
        initial_models = {m['model']: m for m in phases[0]['models']}
        for repeated in phases[1]['models']:
            alias = 'qwen7b' if repeated['model'].startswith('qwen') else 'llama8b'
            initial_complete = {c['id']: c for c in initial_models[repeated['model']]['cases'] if c['status'] == 'COMPLETED'}
            for case in repeated['cases']:
                if case['status'] != 'COMPLETED' or case['id'] not in initial_complete:
                    continue
                texts = [load(phase / alias / case['id'] / 'response.json')['message']['content'] for phase in args.phase]
                text_comparisons.append({'model': repeated['model'], 'case': case['id'], 'kind': case['kind'],
                                         'sameText': texts[0] == texts[1],
                                         'contentSha256': [hashlib.sha256(t.encode()).hexdigest() for t in texts]})
    output = {'recordedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'kind': 'audited development preflight, all attempts retained',
              'primaryExperiment': False, 'fixturesSha256': sha(args.root / 'fixtures.json'),
              'host': load(args.phase[0] / 'result.json')['host'],
              'sourcesStillMatchFrozenFixtures': True, 'phases': phases,
              'budgetScenarios': [budget(p, counts['runs']) for p in phases],
              'determinismBudgetScenarios': deterministic,
              'exploratoryRepeatedTextCheck': {'scope': 'Post-hoc exact-content comparison of the two development passes where both completed; not the planned five-pass runner determinism series, and no accuracy/model selection.',
                                              'rows': text_comparisons}}
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'phases': len(phases), 'requestAuditCount': sum(len(p['checks']) for p in phases),
                      'parserComparisons': sum(p['parserComparisons'] for p in phases), 'out': str(args.out)}))


if __name__ == '__main__':
    main()
