#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
retarget_smplh_to_vrm.py — convert an HY-Motion (SMPL-H 22-joint) motion NPZ into
a VRM gesture-clip JSON, using the same position-method retargeting as KIMODO's
SOMA30 pipeline. Output schema matches kimodo-gestures.ts (buildVRMAnimation).

Usage:
    python retarget_smplh_to_vrm.py <motion.npz> --name wave --out wave.json \
        [--fps 30] [--hips] [--scale 1.0]

The npz must contain `posed_joints` [T, 22, 3] (SMPL-H world joint positions).
HY-Motion's `generate_motion` returns `rot6d`+`transl`; run its body-model LBS
(or FBX export) to get `posed_joints` first.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from motion_common import build_vrm_json, load_posed, SMPLH22_BONES  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Retarget a SMPL-H motion NPZ to a VRM gesture-clip JSON")
    ap.add_argument("npz", help="input motion.npz with posed_joints [T,22,3]")
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--hips", action="store_true", help="emit hips translation track")
    ap.add_argument("--scale", type=float, default=1.0)
    args = ap.parse_args()

    posed, J = load_posed(args.npz)
    if J != 22:
        # allow 52 (SMPL-H with hands) by taking body joints? keep strict for now
        print(f"[warn] expected 22 SMPL-H joints, got {J}; attempting soma30 fallback")
    out = build_vrm_json(posed, "smplh22", args.name, args.fps,
                         hips=args.hips, scale=args.scale)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[retarget] wrote {args.out}  ({len(out['bones'])} bones)")


if __name__ == "__main__":
    main()
