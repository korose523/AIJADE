#!/usr/bin/env python3
"""Ready identity, await one release byte, then exec exact argv with same PID."""
import json
import os
import sys
import time


def main(argv):
    if len(argv)<4 or argv[2]!='--':raise ValueError('identity-ready exec arguments')
    ready,gate=int(argv[0]),int(argv[1]);command=argv[3:]
    # The child stays blocked until the direct parent obtains and rereads its
    # kernel creation identity. Importing psutil in every short child is not
    # necessary and would consume the collector's unchanged 0.5-second budget.
    value=dict(pid=os.getpid(),parentPid=os.getppid(),readyMonotonic=time.monotonic())
    os.write(ready,(json.dumps(value,separators=(',',':'))+'\n').encode());os.close(ready)
    if os.read(gate,1)!=b'1':raise ValueError('identity-ready release missing')
    os.close(gate)
    if not os.path.isabs(command[0]):raise ValueError('exec target must be absolute')
    os.execve(command[0],command,dict(os.environ))


if __name__=='__main__':main(sys.argv[1:])
