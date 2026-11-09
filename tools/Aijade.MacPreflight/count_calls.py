#!/usr/bin/env python3
"""Count actual archived API call classes, including the determinism-prefix budget."""
import argparse
import hashlib
import json
from pathlib import Path


RUNS = [('family-gpu/rq-c-s42-ollama-t30-r5', 'llama3.1:8b', 'A'),
        ('template-gpu/A/rq-c-s42-ollama-t30-r5', 'qwen2.5-coder:7b-instruct', 'A'),
        ('template-gpu/B/rq-c-s42-ollama-t30-r5', 'qwen2.5-coder:7b-instruct', 'B')]


def counts(rows):
    new = [r for r in rows if not r['reused']]
    initial = sum(r['attempt'] == 0 for r in new)
    retry = [r for r in new if r['attempt'] > 0]
    return {'steps': len(rows), 'initialGenerationCalls': initial,
            'retryGenerationCalls': len(retry), 'reusedSteps': len(rows) - len(new),
            'verifierCalls': sum(r['selfVerdict'] is not None for r in new),
            'retriesWithoutEnvironmentOrCritique': sum(not r['hadEnvFeedback'] and not r['hadSelfCritique'] for r in retry)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError('Refusing to overwrite counts')
    runs = []
    for path, model, template in RUNS:
        source = args.repo / 'experiments/rq-c' / path / 'trials.jsonl'
        rows = [json.loads(line) for line in source.read_text().splitlines()]
        prefix = [r for r in rows if r['trial'] < 5]
        assert len(rows) == 7200 and len(prefix) == 1200
        for selected in (rows, prefix):
            c = counts(selected)
            assert c['steps'] == c['initialGenerationCalls'] + c['retryGenerationCalls'] + c['reusedSteps']
        runs.append({'run': path, 'model': model, 'verifierTemplate': template,
                     'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                     'fullRun': counts(rows), 'firstFiveTrials': counts(prefix),
                     'determinismPasses': 5, 'warmupCallsPerPass': 1})
    args.out.write_text(json.dumps({'kind': 'archived call-count scenarios; new trajectories may differ', 'runs': runs}, indent=2) + '\n')
    print(json.dumps(runs))


if __name__ == '__main__':
    main()
