#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
retarget_soma_to_vrm.py — convert a KIMODO motion NPZ into a VRM gesture-clip JSON.

KIMODO emits motions on the SOMA (30/77 joint) or SMPL-X (22 joint) skeleton.
This script retargets the humanoid core onto VRM human bones using the
**position method** (validated: produces clean unit quaternions, axis/scale
robust) and derives an optional hips translation track so dance / walk actually
displace the avatar.

The output JSON matches the schema consumed by
``packages/stage-ui-three/src/libs/kimodo-gestures.ts`` (buildVRMAnimation).

Usage:
    python retarget_soma_to_vrm.py <motion.npz> --name wave --out wave.json \
        [--fps 30] [--hips] [--scale 1.0] [--skeleton auto]

If --skeleton auto (default), the joint count picks the right skeleton layout.
"""
from __future__ import annotations

import argparse
import json
import math
import os

import numpy as np

# ── SOMA 30-joint humanoid core (subset of SOMASkeleton30). ──────────────────
# (name, parent) — parents resolve to indices within the same skeleton layout.
SOMA30_BONES = [
    ("Hips", None),
    ("Spine1", "Hips"),
    ("Spine2", "Spine1"),
    ("Chest", "Spine2"),
    ("Neck1", "Chest"),
    ("Neck2", "Neck1"),
    ("Head", "Neck2"),
    ("Jaw", "Head"),
    ("LeftEye", "Head"),
    ("RightEye", "Head"),
    ("LeftShoulder", "Chest"),
    ("LeftArm", "LeftShoulder"),
    ("LeftForeArm", "LeftArm"),
    ("LeftHand", "LeftForeArm"),
    ("LeftHandThumbEnd", "LeftHand"),
    ("LeftHandMiddleEnd", "LeftHand"),
    ("RightShoulder", "Chest"),
    ("RightArm", "RightShoulder"),
    ("RightForeArm", "RightArm"),
    ("RightHand", "RightForeArm"),
    ("RightHandThumbEnd", "RightHand"),
    ("RightHandMiddleEnd", "RightHand"),
    ("LeftLeg", "Hips"),
    ("LeftShin", "LeftLeg"),
    ("LeftFoot", "LeftShin"),
    ("LeftToeBase", "LeftFoot"),
    ("RightLeg", "Hips"),
    ("RightShin", "RightLeg"),
    ("RightFoot", "RightShin"),
    ("RightToeBase", "RightFoot"),
]

# Humanoid SOMA joint name → VRM human bone. Names absent from this map are
# skipped (finger/extra joints have no VRM equivalent).
VRM_MAP = {
    "Hips": "hips",
    "Spine1": "spine",
    "Spine2": "chest",
    "Chest": "upperChest",
    "Neck1": "neck",
    "Neck2": None,
    "Head": "head",
    "Jaw": "jaw",
    "LeftEye": "leftEye",
    "RightEye": "rightEye",
    "LeftShoulder": "leftShoulder",
    "LeftArm": "leftUpperArm",
    "LeftForeArm": "leftLowerArm",
    "LeftHand": "leftHand",
    "RightShoulder": "rightShoulder",
    "RightArm": "rightUpperArm",
    "RightForeArm": "rightLowerArm",
    "RightHand": "rightHand",
    "LeftLeg": "leftUpperLeg",
    "LeftShin": "leftLowerLeg",
    "LeftFoot": "leftFoot",
    "LeftToeBase": "leftToes",
    "RightLeg": "rightUpperLeg",
    "RightShin": "rightLowerLeg",
    "RightFoot": "rightFoot",
    "RightToeBase": "rightToes",
}


def quat_from_to(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Return a unit quaternion [x,y,z,w] rotating unit vector a onto unit vector b."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na < 1e-12 or nb < 1e-12:
        return np.array([0.0, 0.0, 0.0, 1.0])
    a = a / na
    b = b / nb
    dot = float(np.dot(a, b))
    if dot > 1.0 - 1e-8:
        return np.array([0.0, 0.0, 0.0, 1.0])
    if dot < -1.0 + 1e-8:
        # 180°: pick any orthogonal axis
        axis = np.cross(np.array([1.0, 0.0, 0.0]), a)
        if np.linalg.norm(axis) < 1e-8:
            axis = np.cross(np.array([0.0, 1.0, 0.0]), a)
        axis = axis / np.linalg.norm(axis)
        return np.array([axis[0], axis[1], axis[2], 0.0])
    axis = np.cross(a, b)
    axis = axis / np.linalg.norm(axis)
    ang = math.acos(max(-1.0, min(1.0, dot)))
    s = math.sin(ang / 2.0)
    return np.array([axis[0] * s, axis[1] * s, axis[2] * s, math.cos(ang / 2.0)])


def get_bone_order(skeleton: str):
    """Resolve (name, parent) layout. Prefer KIMODO's own skeleton defs when present."""
    if skeleton in ("soma30", "auto"):
        try:
            from kimodo.skeleton import SOMASkeleton30
            return [(n, p) for (n, p) in SOMASkeleton30().bone_order_names_with_parents]
        except Exception:
            return SOMA30_BONES
    if skeleton == "soma77":
        try:
            from kimodo.skeleton import SOMASkeleton77
            return [(n, p) for (n, p) in SOMASkeleton77().bone_order_names_with_parents]
        except Exception:
            raise RuntimeError("soma77 layout requires the kimodo package")
    if skeleton == "smplx22":
        try:
            from kimodo.skeleton import SMPLXSkeleton22
            return [(n, p) for (n, p) in SMPLXSkeleton22().bone_order_names_with_parents]
        except Exception:
            raise RuntimeError("smplx22 layout requires the kimodo package")
    raise ValueError(f"unknown skeleton {skeleton!r}")


def detect_skeleton(joint_count: int) -> str:
    if joint_count == 30:
        return "soma30"
    if joint_count == 77:
        return "soma77"
    if joint_count == 22:
        return "smplx22"
    # Fall back to soma30 (humanoid subset still maps)
    return "soma30"


def retarget(npz_path: str, name: str, out_json: str, fps: float = 30.0,
             hips: bool = False, scale: float = 1.0, skeleton: str = "auto") -> dict:
    d = np.load(npz_path, allow_pickle=True)
    posed = d["posed_joints"].astype(np.float64)
    if posed.ndim != 3 or posed.shape[2] != 3:
        raise ValueError(f"posed_joints must be [T,J,3], got {posed.shape}")
    T, J, _ = posed.shape

    if skeleton == "auto":
        skeleton = detect_skeleton(J)
    bone_order = get_bone_order(skeleton)
    name2idx = {n: i for i, (n, _) in enumerate(bone_order)}
    if len(name2idx) != J:
        # layout length mismatch — best-effort: trust name2idx subset
        pass

    times = [round(i / fps, 5) for i in range(T)]
    bones: dict[str, dict] = {}

    for soma_name, vrm_bone in VRM_MAP.items():
        if vrm_bone is None:
            continue
        ci = name2idx.get(soma_name)
        if ci is None:
            continue
        # parent: for Hips (root) use Spine1 direction as a proxy for root orientation
        if soma_name == "Hips":
            pi = name2idx.get("Spine1")
        else:
            pname = dict(bone_order).get(soma_name)
            pi = name2idx.get(pname) if pname else None
        if pi is None:
            continue
        child = posed[:, ci, :]
        parent = posed[:, pi, :]
        rd = child[0] - parent[0]
        if np.linalg.norm(rd) < 1e-9:
            continue
        rots: list[list[float]] = []
        for t in range(T):
            td = child[t] - parent[t]
            if np.linalg.norm(td) < 1e-9:
                td = rd
            q = quat_from_to(rd, td)
            rots.append([float(q[0]), float(q[1]), float(q[2]), float(q[3])])
        bones[vrm_bone] = {"times": times, "rotation": rots}

    out: dict = {
        "name": name,
        "fps": fps,
        "duration": round(T / fps, 4),
        "restHipsPosition": [0.0, 0.8, 0.0],
        "bones": bones,
    }

    if hips:
        hip_idx = name2idx.get("Hips")
        if hip_idx is not None:
            hip = posed[:, hip_idx, :]
            rest = hip[0]
            position = [[float((hip[t, 0] - rest[0]) * scale),
                         float((hip[t, 1] - rest[1]) * scale),
                         float((hip[t, 2] - rest[2]) * scale)] for t in range(T)]
            out["translation"] = {"times": times, "position": position}

    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


def main():
    ap = argparse.ArgumentParser(description="Retarget a KIMODO NPZ to a VRM gesture-clip JSON")
    ap.add_argument("npz", help="input KIMODO motion.npz")
    ap.add_argument("--name", required=True, help="clip name (e.g. wave)")
    ap.add_argument("--out", required=True, help="output JSON path")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--hips", action="store_true", help="emit hips translation track")
    ap.add_argument("--scale", type=float, default=1.0, help="translation scale (meters)")
    ap.add_argument("--skeleton", default="auto", choices=["auto", "soma30", "soma77", "smplx22"])
    args = ap.parse_args()
    retarget(args.npz, args.name, args.out, fps=args.fps,
             hips=args.hips, scale=args.scale, skeleton=args.skeleton)
    print(f"[retarget] wrote {args.out}")


if __name__ == "__main__":
    main()
