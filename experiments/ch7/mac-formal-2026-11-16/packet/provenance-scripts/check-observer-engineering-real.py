"""One authorized real read-only instrument check; not an admission window."""
import json
import argparse
from pathlib import Path
import sys
from datetime import datetime, timezone

BASE = Path('/Volumes/Untitled/AIJADE')
C = BASE / '.research/runs/ch7-mac-formal-20261116'
sys.path.insert(0, str(C / 'worktree/experiments/ch7'))
import mac_process_guard as guard

parser = argparse.ArgumentParser()
parser.add_argument('--output', default=str(C / 'observer-engineering-real.json'))
arguments = parser.parse_args()
destination = Path(arguments.output)
if destination.parent.resolve() != C.resolve() or destination.suffix != '.json' or destination.exists():
    raise SystemExit('Refuse overwrite or output outside the fixed engineering evidence directory')

out = {'scope': 'ONE_ENGINEERING_INSTRUMENT_SNAPSHOT_NOT_ADMISSION',
       'observedAt': datetime.now(timezone.utc).isoformat(), 'modelCalls': 0,
       'rendererStarts': 0, 'admissionStarts': 0, 'servicesStopped': 0}
try:
    out['policy'] = guard.build_policy(669, 701)
    out['observation'] = guard.observe(out['policy'])
    out['recomputed'] = guard.validate_observation(out['policy'], out['observation'])
except Exception as error:
    out.update({'status': 'ENGINEERING_CHECK_FAILED', 'errorClass': type(error).__name__,
                'message': str(error) if isinstance(error, ValueError) else 'read-only capture failed'})
with destination.open('x', encoding='utf-8') as stream:
    stream.write(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
observation = out.get('observation', {})
print(json.dumps({'status': observation.get('status', out.get('status')),
                  'durationSeconds': observation.get('finishedMonotonic', 0) - observation.get('startedMonotonic', 0),
                  'blockers': observation.get('blockers'),
                  'api': observation.get('idleDaemon', {}).get('api'),
                  'errorClass': out.get('errorClass'), 'message': out.get('message')}, ensure_ascii=False, indent=2))
