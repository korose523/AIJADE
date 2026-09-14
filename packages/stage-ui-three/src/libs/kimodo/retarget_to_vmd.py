#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
retarget_to_vmd.py — convert a KIMODO (SOMA30) or HY-Motion (SMPL-H22) motion
NPZ into a MikuMikuDance .vmd file. This is the "MMD action" output: AIJADE's AI
free-form motion double-emitted as a VRM clip (for AIJADE) AND a .vmd (for MMD).

Usage:
    python retarget_to_vmd.py <motion.npz> --name dance --out dance.vmd \
        [--skeleton auto|soma30|smplh22] [--fps 30] [--scale 1.0] [--handedness mmd]

The npz must contain `posed_joints` [T, J, 3] (world joint positions). For
HY-Motion, run its pipeline to produce a `posed_joints` npz first (the SMPL-H
body-model LBS); the retargeter itself only needs positions.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from motion_common import build_vmd, load_posed  # noqa: E402


def detect_skeleton(joint_count: int) -> str:
    if joint_count == 30:
        return "soma30"
    if joint_count == 22:
        return "smplh22"
    if joint_count == 77:
        return "soma30"  # SOMA77 humanoid subset still maps via soma30 layout
    raise ValueError(f"unsupported joint count {joint_count}; expected 22 or 30")


def main():
    ap = argparse.ArgumentParser(description="Retarget a motion NPZ to a MMD .vmd file")
    ap.add_argument("npz", help="input motion.npz with posed_joints [T,J,3]")
    ap.add_argument("--name", required=True, help="clip name (used for nothing in VMD, kept for parity)")
    ap.add_argument("--out", required=True, help="output .vmd path")
    ap.add_argument("--skeleton", default="auto", choices=["auto", "soma30", "smplh22"])
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--scale", type=float, default=1.0, help="translation scale (meters)")
    ap.add_argument("--handedness", default="mmd", choices=["mmd", "source"],
                    help="mmd: negate Z translation + Y euler (MMD faces -Z); source: keep as-is")
    args = ap.parse_args()

    posed, J = load_posed(args.npz)
    skeleton = args.skeleton if args.skeleton != "auto" else detect_skeleton(J)

    motion = build_vmd(posed, skeleton, args.name, args.fps,
                       scale=args.scale, handedness=args.handedness)

    from pypmxvmd import save_vmd
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    save_vmd(motion, args.out)
    print(f"[vmd] wrote {args.out}  ({len(motion.bone_frames)} bone frames, "
          f"skeleton={skeleton}, handedness={args.handedness})")


if __name__ == "__main__":
    main()
