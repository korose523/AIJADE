#!/usr/bin/env python3
"""Observe the fixed preflight-repeat admission window; no stress or model call."""
import argparse
import datetime as dt
import json
from pathlib import Path
import time
import urllib.request

import psutil


def state(base):
    with urllib.request.urlopen(base + '/api/ps', timeout=10) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:11509')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError('Refusing to overwrite an admission trace')
    before = state(args.base)
    start = time.monotonic()
    samples = []
    while True:
        elapsed = time.monotonic() - start
        samples.append({'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'elapsedSeconds': elapsed,
                        'availableBytes': psutil.virtual_memory().available, 'swapUsedBytes': psutil.swap_memory().used})
        if elapsed >= 60:
            break
        time.sleep(1)
    after = state(args.base)
    reasons = []
    if before['models'] or after['models']:
        reasons.append('A model was loaded at admission boundary')
    if min(s['availableBytes'] for s in samples) < 7 * 2**30:
        reasons.append('Available RAM fell below 7 GiB')
    if max(s['swapUsedBytes'] for s in samples) - samples[0]['swapUsedBytes'] > 256 * 2**20:
        reasons.append('Swap increased by more than 256 MiB')
    args.out.write_text(json.dumps({'kind': 'fixed development repeat admission, not hardware qualification',
                                    'admitted': not reasons, 'reasons': reasons,
                                    'stateBefore': before, 'stateAfter': after, 'samples': samples}, indent=2) + '\n')
    print(json.dumps({'admitted': not reasons, 'reasons': reasons, 'samples': len(samples),
                      'minAvailableGiB': min(s['availableBytes'] for s in samples) / 2**30}))
    return 0 if not reasons else 1


if __name__ == '__main__':
    raise SystemExit(main())
