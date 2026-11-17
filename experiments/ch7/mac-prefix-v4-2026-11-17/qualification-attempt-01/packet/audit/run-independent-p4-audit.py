"""Capture exactly one offline audit execution; no automatic retry."""
from datetime import datetime,timezone
import hashlib,json
from pathlib import Path
import subprocess,sys

HERE=Path(__file__).resolve().parent
source=HERE/'independent_p4_terminal_audit.py'
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
before=sha(source)
with (HERE/'independent-p4-terminal-audit-01.log').open('xb') as stream:
    result=subprocess.run([sys.executable,'-B',str(source)],stdout=stream,stderr=subprocess.STDOUT)
record={'status':'OFFLINE_AUDIT_EXECUTION_COMPLETED' if result.returncode==0 else 'OFFLINE_AUDIT_EXECUTION_REFUSED',
        'exitCode':result.returncode,'sourceSha256':before,'sourceUnchanged':sha(source)==before,
        'logSha256':sha(HERE/'independent-p4-terminal-audit-01.log'),'actualObserverOrModelInvoked':False,
        'at':datetime.now(timezone.utc).isoformat()}
with (HERE/'independent-p4-terminal-audit-01.receipt.json').open('x') as stream:json.dump(record,stream,indent=2);stream.write('\n')
print(json.dumps(record,indent=2));raise SystemExit(result.returncode)
