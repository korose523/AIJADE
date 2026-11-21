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
    # The engine log goes to the run's own log directory, one file per call; the scene creates MOSAIC_SCENE_OUT itself
    # and refuses an existing directory (third recorded deviation of the 21 November 2026 Mac qualification).
    logs=Path(os.environ['AIJADE_GODOT_LOG_DIR']).resolve()
    scene=os.environ.get('MOSAIC_SCENE_OUT')
    scene=Path(scene).resolve() if scene else None
    if (not sdk.is_file() or not profile.is_file() or workspace not in profile.parents or workspace not in logs.parents
            or (scene is not None and workspace not in scene.parents)):
        raise ValueError('explicit Godot/profile/log paths are invalid or outside the workspace')
    logs.mkdir(parents=True,exist_ok=True)
    return subprocess.run(['/usr/bin/sandbox-exec','-f',str(profile),str(sdk),
                           '--log-file',str(logs/f'godot-engine-{os.getpid()}.log'),*arguments],check=False).returncode


if __name__=='__main__':
    raise SystemExit(main(sys.argv[1:]))
