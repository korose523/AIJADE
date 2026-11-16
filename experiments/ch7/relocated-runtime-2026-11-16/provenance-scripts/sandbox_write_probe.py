from pathlib import Path
import json,os
p=Path("/Volumes/Untitled/AIJADE/.runtime/tmp/sandbox-write-proof");p.write_text("project-local");p.unlink()
try:
 open("/Users/mac/WorkBuddy/AIJADE/aijade-sandbox-probe", "w")
except OSError as e:
 print(json.dumps(dict(insideWrite=True, outsideErrno=e.errno, outsideDenied=e.errno==1)))
else:raise AssertionError("outside write unexpectedly allowed")
