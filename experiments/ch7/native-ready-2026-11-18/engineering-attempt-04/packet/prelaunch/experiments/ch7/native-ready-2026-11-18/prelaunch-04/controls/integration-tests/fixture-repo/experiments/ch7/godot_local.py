#!/usr/bin/env python3
"""Run the explicit installed Godot with project-local logs and a Mac write boundary."""
import os
from pathlib import Path
import subprocess
import sys


def main(arguments):
    workspace=Path(os.environ['AIJADE_WORKSPACE_ROOT']).resolve()
    sdk=Path(os.environ['AIJADE_REAL_GODOT']).resolve()
    profile=Path(os.environ['AIJADE_GODOT_SANDBOX_PROFILE']).resolve()
    output=Path(os.environ.get('MOSAIC_SCENE_OUT',os.environ['AIJADE_GODOT_LOG_DIR'])).resolve()
    if not sdk.is_file() or not profile.is_file() or workspace not in profile.parents or workspace not in output.parents:
        raise ValueError('explicit Godot/profile/log paths are invalid or outside the workspace')
    output.mkdir(parents=True,exist_ok=True)
    return subprocess.run(['/usr/bin/sandbox-exec','-f',str(profile),str(sdk),
                           '--log-file',str(output/'godot-engine.log'),*arguments],check=False).returncode


if __name__=='__main__':
    raise SystemExit(main(sys.argv[1:]))
