#!/usr/bin/env python3
"""Ready identity, await one release byte, then exec exact argv with same PID."""
import json
import os
from pathlib import Path
import sys
import time


def main(argv):
    if len(argv)<4 or argv[2]!='--':raise ValueError('identity-ready exec arguments')
    ready,gate=int(argv[0]),int(argv[1]);command=argv[3:]
    import psutil
    current=psutil.Process()
    value=dict(identity=dict(pid=os.getpid(),createTimeMicros=round(current.create_time()*1000000),
                            parentPid=os.getppid()),readyMonotonic=time.monotonic())
    os.write(ready,(json.dumps(value,separators=(',',':'))+'\n').encode());os.close(ready)
    if os.read(gate,1)!=b'1':raise ValueError('identity-ready release missing')
    os.close(gate)
    if not Path(command[0]).is_absolute():raise ValueError('exec target must be absolute')
    os.execve(command[0],command,dict(os.environ))


if __name__=='__main__':main(sys.argv[1:])
