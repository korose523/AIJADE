import os,json
from pathlib import Path
p=Path("/Volumes/Untitled/AIJADE/.runtime/tmp/sandbox-write-proof");p.write_text("project-local");p.unlink()
try:
 fd=os.open("/dev/null", os.O_WRONLY);os.close(fd)
except OSError as e:print(json.dumps(dict(insideWrite=True,outsideErrno=e.errno,outsideDenied=e.errno==1)))
else:print(json.dumps(dict(insideWrite=True,outsideDenied=False)))
