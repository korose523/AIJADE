from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import subprocess
import uuid

C = Path(__file__).resolve().parent
env = dict(os.environ, DOCKER_HOST='unix:///Volumes/Untitled/AIJADE/.runtime/posix/colima/default/docker.sock')
docker = '/Users/mac/.local/bin/docker'
name = 'aijade_test_' + uuid.uuid4().hex
assert re.fullmatch(r'aijade_test_[0-9a-f]{32}', name)
record = {'status': 'RUNNING', 'startedAt': datetime.now(timezone.utc).isoformat(), 'database': name, 'created': False, 'dropped': False, 'remaining': None, 'steps': [], 'modelRequests': 0, 'rendererStarts': 0}
(C / 'preflight-database-lease.jsonl').write_text(json.dumps({'database': name, 'purpose': 'single_owned_preflight_control', 'recordedBeforeCreation': True}) + '\n')

def sql(label, text):
    p = subprocess.run([docker, 'exec', 'aijade-next-db', 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'aijade', '-d', 'aijade', '-Atc', text], env=env, capture_output=True, text=True, timeout=20)
    record['steps'].append({'label': label, 'returnCode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
    if p.returncode:
        raise RuntimeError(label + ' failed')
    return p.stdout.strip()

try:
    record['postgres'] = sql('version_and_extensions', "SELECT version(); SELECT extname || ':' || extversion FROM pg_extension ORDER BY extname;")
    image = subprocess.run([docker, 'inspect', '--format', '{{.Image}}', 'aijade-next-db'], env=env, capture_output=True, text=True, timeout=10)
    assert image.returncode == 0
    record['databaseImageId'] = image.stdout.strip()
    assert sql('preexisting_absence', "SELECT count(*) FROM pg_database WHERE datname='" + name + "'") == '0'
    sql('create_exact_owned_database', 'CREATE DATABASE ' + name)
    record['created'] = True
    assert sql('verify_created', "SELECT count(*) FROM pg_database WHERE datname='" + name + "'") == '1'
    record['status'] = 'CONTROL_CREATED_AND_OBSERVED'
except BaseException as error:
    record.update(status='STOPPED_PRECONDITION', error=type(error).__name__ + ': ' + str(error))
finally:
    if record['created']:
        try:
            sql('drop_exact_recorded_owned_database', 'DROP DATABASE ' + name)
            record['dropped'] = True
            record['remaining'] = int(sql('independent_absence_after_drop', "SELECT count(*) FROM pg_database WHERE datname='" + name + "'"))
            if record['remaining'] == 0 and 'error' not in record:
                record['status'] = 'REAL_OWNED_DATABASE_LIFECYCLE_VERIFIED'
        except BaseException as error:
            record.update(status='STOPPED_CLEANUP_UNKNOWN', cleanupError=type(error).__name__ + ': ' + str(error))
    record['finishedAt'] = datetime.now(timezone.utc).isoformat()
    (C / 'real-owned-database-control.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'status': record['status'], 'created': record['created'], 'dropped': record['dropped'], 'remaining': record['remaining']}))
raise SystemExit(0 if record['status'] == 'REAL_OWNED_DATABASE_LIFECYCLE_VERIFIED' else 1)
