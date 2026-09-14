#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
motion_common.py — shared retargeting math for KIMODO (SOMA30) and HY-Motion (SMPL-H22)
motion, used to emit BOTH VRM gesture-clip JSON and MikuMikuDance (.vmd) files.

The "position method" (validated on real KIMODO SOMA data: 0 outliers) computes,
for each bone, a world-space quaternion that aligns its rest direction
(child - parent) with the current direction. To obtain a *local* rotation that a
hierarchical format (VRM / VMD) can replay correctly, we divide out the nearest
mapped ancestor's world quaternion, so the emitted local rotation is relative to
the correct parent in BOTH the source skeleton and the target skeleton.

This file is imported by:
    retarget_soma_to_vrm.py   (KIMODO -> VRM JSON)   [legacy, standalone copy kept]
    retarget_smplh_to_vrm.py  (HY-Motion -> VRM JSON)
    retarget_to_vmd.py        (KIMODO / HY-Motion -> .vmd)
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.spatial.transform import Rotation as R


# ── quaternion helpers (Hamilton, [x, y, z, w]) ──────────────────────────────
def quat_from_to(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Unit quaternion [x,y,z,w] rotating unit vector a onto unit vector b."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-12 or nb < 1e-12:
        return np.array([0.0, 0.0, 0.0, 1.0])
    a, b = a / na, b / nb
    dot = float(np.dot(a, b))
    if dot > 1.0 - 1e-8:
        return np.array([0.0, 0.0, 0.0, 1.0])
    if dot < -1.0 + 1e-8:
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


def quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product a*b (applies b first, then a)."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ], dtype=float)


def quat_conj(q: np.ndarray) -> np.ndarray:
    return np.array([-q[0], -q[1], -q[2], q[3]], dtype=float)


def quat_to_euler_xyz_deg(q: np.ndarray) -> np.ndarray:
    """Quaternion [x,y,z,w] -> XYZ euler angles in DEGREES (MMD convention)."""
    return R.from_quat([q[0], q[1], q[2], q[3]]).as_euler("XYZ", degrees=True)


# ── SOMA30 (KIMODO) skeleton ─────────────────────────────────────────────────
SOMA30_BONES: List[Tuple[str, Optional[str]]] = [
    ("Hips", None), ("Spine1", "Hips"), ("Spine2", "Spine1"), ("Chest", "Spine2"),
    ("Neck1", "Chest"), ("Neck2", "Neck1"), ("Head", "Neck2"), ("Jaw", "Head"),
    ("LeftEye", "Head"), ("RightEye", "Head"), ("LeftShoulder", "Chest"),
    ("LeftArm", "LeftShoulder"), ("LeftForeArm", "LeftArm"), ("LeftHand", "LeftForeArm"),
    ("LeftHandThumbEnd", "LeftHand"), ("LeftHandMiddleEnd", "LeftHand"),
    ("RightShoulder", "Chest"), ("RightArm", "RightShoulder"),
    ("RightForeArm", "RightArm"), ("RightHand", "RightForeArm"),
    ("RightHandThumbEnd", "RightHand"), ("RightHandMiddleEnd", "RightHand"),
    ("LeftLeg", "Hips"), ("LeftShin", "LeftLeg"), ("LeftFoot", "LeftShin"),
    ("LeftToeBase", "LeftFoot"), ("RightLeg", "Hips"), ("RightShin", "RightLeg"),
    ("RightFoot", "RightShin"), ("RightToeBase", "RightFoot"),
]

# KIMODO SOMA joint name -> VRM human bone (None = skip, no VRM equivalent).
VRM_MAP: Dict[str, Optional[str]] = {
    "Hips": "hips", "Spine1": "spine", "Spine2": "chest", "Chest": "upperChest",
    "Neck1": "neck", "Neck2": None, "Head": "head", "Jaw": "jaw",
    "LeftEye": "leftEye", "RightEye": "rightEye",
    "LeftShoulder": "leftShoulder", "LeftArm": "leftUpperArm",
    "LeftForeArm": "leftLowerArm", "LeftHand": "leftHand",
    "RightShoulder": "rightShoulder", "RightArm": "rightUpperArm",
    "RightForeArm": "rightLowerArm", "RightHand": "rightHand",
    "LeftLeg": "leftUpperLeg", "LeftShin": "leftLowerLeg", "LeftFoot": "leftFoot",
    "LeftToeBase": "leftToes", "RightLeg": "rightUpperLeg",
    "RightShin": "rightLowerLeg", "RightFoot": "rightFoot", "RightToeBase": "rightToes",
}

# KIMODO SOMA joint name -> MMD (Japanese) bone name.
# Only the humanoid core is mapped; the hierarchy is preserved by computing each
# bone's local rotation relative to its nearest mapped ancestor (see build_vmd).
MMD_SOMA_MAP: List[Tuple[str, str]] = [
    ("Hips", "センター"),          # root: translation only
    ("Spine1", "上半身"),
    ("Spine2", "上半身2"),
    ("Chest", "胴体"),
    ("Neck1", "首"),
    ("Head", "頭"),
    ("LeftShoulder", "左肩"),
    ("LeftArm", "左腕"),
    ("LeftForeArm", "左ひじ"),
    ("LeftHand", "左手"),
    ("RightShoulder", "右肩"),
    ("RightArm", "右腕"),
    ("RightForeArm", "右ひじ"),
    ("RightHand", "右手"),
    ("LeftLeg", "左足"),
    ("LeftShin", "左ひざ"),
    ("LeftFoot", "左足首"),
    ("LeftToeBase", "左つま先"),
    ("RightLeg", "右足"),
    ("RightShin", "右ひざ"),
    ("RightFoot", "右足首"),
    ("RightToeBase", "右つま先"),
]


# ── SMPL-H 22 (HY-Motion) skeleton ──────────────────────────────────────────
# Canonical SMPL-H body joints (hands excluded), indices 0..21.
SMPLH22_BONES: List[Tuple[str, Optional[str]]] = [
    ("pelvis", None), ("left_hip", "pelvis"), ("right_hip", "pelvis"),
    ("spine1", "pelvis"), ("left_knee", "left_hip"), ("right_knee", "right_hip"),
    ("spine2", "spine1"), ("left_ankle", "left_knee"), ("right_ankle", "right_knee"),
    ("spine3", "spine2"), ("left_foot", "left_ankle"), ("right_foot", "right_ankle"),
    ("neck", "spine3"), ("left_collar", "neck"), ("right_collar", "neck"),
    ("head", "neck"), ("left_shoulder", "left_collar"), ("right_shoulder", "right_collar"),
    ("left_elbow", "left_shoulder"), ("right_elbow", "right_shoulder"),
    ("left_wrist", "left_elbow"), ("right_wrist", "right_elbow"),
]

SMPLH_VRM_MAP: Dict[str, Optional[str]] = {
    "pelvis": "hips", "left_hip": "leftUpperLeg", "right_hip": "rightUpperLeg",
    "spine1": "spine", "spine2": "chest", "spine3": "upperChest", "neck": "neck",
    "left_collar": "leftShoulder", "right_collar": "rightShoulder", "head": "head",
    "left_shoulder": "leftUpperArm", "left_elbow": "leftLowerArm", "left_wrist": "leftHand",
    "right_shoulder": "rightUpperArm", "right_elbow": "rightLowerArm", "right_wrist": "rightHand",
    "left_knee": "leftLowerLeg", "right_knee": "rightLowerLeg",
    "left_ankle": "leftFoot", "right_ankle": "rightFoot",
    "left_foot": "leftToes", "right_foot": "rightToes",
}

MMD_SMPLH_MAP: List[Tuple[str, str]] = [
    ("pelvis", "センター"),
    ("spine1", "上半身"),
    ("spine2", "上半身2"),
    ("spine3", "胴体"),
    ("neck", "首"),
    ("head", "頭"),
    ("left_collar", "左肩"),
    ("left_shoulder", "左腕"),
    ("left_elbow", "左ひじ"),
    ("left_wrist", "左手"),
    ("right_collar", "右肩"),
    ("right_shoulder", "右腕"),
    ("right_elbow", "右ひじ"),
    ("right_wrist", "右手"),
    ("left_hip", "左足"),
    ("left_knee", "左ひざ"),
    ("left_ankle", "左足首"),
    ("left_foot", "左つま先"),
    ("right_hip", "右足"),
    ("right_knee", "右ひざ"),
    ("right_ankle", "右足首"),
    ("right_foot", "右つま先"),
]


def _skeleton_defs(skeleton: str):
    if skeleton in ("soma30", "auto"):
        return SOMA30_BONES, VRM_MAP, MMD_SOMA_MAP, "Hips"
    if skeleton == "smplh22":
        return SMPLH22_BONES, SMPLH_VRM_MAP, MMD_SMPLH_MAP, "pelvis"
    raise ValueError(f"unknown skeleton {skeleton!r}")


def compute_world_quats(posed: np.ndarray, bone_order) -> Tuple[Dict[str, np.ndarray], Dict[str, int]]:
    """Return per-bone world quaternions [T,4] using the position method.

    posed: [T, J, 3] world joint positions. bone_order: list of (name, parent).
    The root (parent None) gets identity; every other bone gets a world quaternion
    aligning its (child - parent) direction across time.
    """
    T = posed.shape[0]
    name2idx = {n: i for i, (n, _) in enumerate(bone_order)}
    parent_of = {n: p for (n, p) in bone_order}
    world: Dict[str, np.ndarray] = {}
    for name, pname in bone_order:
        ci = name2idx.get(name)
        pi = name2idx.get(pname) if pname else None
        if ci is None:
            world[name] = np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (T, 1))
            continue
        if pi is None:
            world[name] = np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (T, 1))
            continue
        rest = posed[0, ci] - posed[0, pi]
        quats = np.empty((T, 4))
        for t in range(T):
            cur = posed[t, ci] - posed[t, pi]
            quats[t] = quat_from_to(rest, cur)
        world[name] = quats
    return world, name2idx


def build_vrm_json(posed: np.ndarray, skeleton: str, name: str, fps: float,
                   hips: bool, scale: float) -> dict:
    """Emit the VRM gesture-clip JSON consumed by kimodo-gestures.ts.

    Mirrors the validated retarget_soma_to_vrm.py logic but works for both
    SOMA30 and SMPL-H22 inputs.
    """
    bone_order, vrm_map, _, root_name = _skeleton_defs(skeleton)
    world, name2idx = compute_world_quats(posed, bone_order)
    T = posed.shape[0]
    times = [round(i / fps, 5) for i in range(T)]
    bones: Dict[str, dict] = {}
    for src_name, vrm_bone in vrm_map.items():
        if vrm_bone is None:
            continue
        ci = name2idx.get(src_name)
        if ci is None:
            continue
        pname = dict(bone_order).get(src_name)
        pi = name2idx.get(pname) if pname else None
        if pi is None:
            continue
        child, parent = posed[:, ci, :], posed[:, pi, :]
        rd = child[0] - parent[0]
        if np.linalg.norm(rd) < 1e-9:
            continue
        rots = []
        for t in range(T):
            td = child[t] - parent[t]
            if np.linalg.norm(td) < 1e-9:
                td = rd
            q = quat_from_to(rd, td)
            rots.append([float(q[0]), float(q[1]), float(q[2]), float(q[3])])
        bones[vrm_bone] = {"times": times, "rotation": rots}
    out = {
        "name": name, "fps": fps, "duration": round(T / fps, 4),
        "restHipsPosition": [0.0, 0.8, 0.0], "bones": bones,
    }
    if hips:
        ri = name2idx.get(root_name)
        if ri is not None:
            hip = posed[:, ri, :]
            rest = hip[0]
            out["translation"] = {"times": times, "position": [
                [float((hip[t, 0] - rest[0]) * scale),
                 float((hip[t, 1] - rest[1]) * scale),
                 float((hip[t, 2] - rest[2]) * scale)] for t in range(T)]}
    return out


def build_vmd(posed: np.ndarray, skeleton: str, name: str, fps: float,
              scale: float = 1.0, handedness: str = "mmd") -> "object":
    """Emit a pypmxvmd.VmdMotion from world joint positions.

    Each mapped MMD bone's LOCAL rotation is computed relative to its nearest
    mapped ancestor, preserving the (source == target) hierarchy so playback is
    correct. The root (センター) carries the hip translation; MMD faces -Z so we
    negate Z by default (handedness="mmd").
    """
    from pypmxvmd import VmdMotion
    from pypmxvmd.common.models.vmd import VmdBoneFrame

    bone_order, _, mmd_map, root_name = _skeleton_defs(skeleton)
    world, name2idx = compute_world_quats(posed, bone_order)
    parent_of = {n: p for (n, p) in bone_order}
    mapped_src = {src for (src, _) in mmd_map}
    mmd_of = {src: mmd for (src, mmd) in mmd_map}

    T = posed.shape[0]
    motion = VmdMotion()
    motion.header.model_name = "AIJADE"

    def nearest_mapped_ancestor(src: str):
        p = parent_of.get(src)
        while p is not None and p not in mapped_src:
            p = parent_of.get(p)
        return p  # None or a mapped source name

    # Root translation -> センター position.
    ri = name2idx.get(root_name)
    if ri is not None:
        hip = posed[:, ri, :]
        rest = hip[0]
        for t in range(T):
            dx = (hip[t, 0] - rest[0]) * scale
            dy = (hip[t, 1] - rest[1]) * scale
            dz = (hip[t, 2] - rest[2]) * scale
            if handedness == "mmd":
                dz = -dz
            motion.bone_frames.append(VmdBoneFrame(
                bone_name="センター", frame_number=t,
                position=[float(dx), float(dy), float(dz)],
                rotation=[0.0, 0.0, 0.0]))

    # Every other mapped bone.
    for src, mmd in mmd_map:
        if src == root_name:
            continue
        ci = name2idx.get(src)
        if ci is None:
            continue
        anc = nearest_mapped_ancestor(src)
        anc_world = world[anc] if (anc and anc in world) else \
            np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (T, 1))
        wq = world[src]
        for t in range(T):
            local = quat_mul(quat_conj(anc_world[t]), wq[t])
            ex, ey, ez = quat_to_euler_xyz_deg(local)
            if handedness == "mmd":
                ey = -ey  # compensate left/right-handed Y axis
            motion.bone_frames.append(VmdBoneFrame(
                bone_name=mmd, frame_number=t,
                position=[0.0, 0.0, 0.0],
                rotation=[float(ex), float(ey), float(ez)]))
    return motion


# Approximate SMPL-H body rest offsets (parent-relative, meters). Exact lengths
# are NOT needed for the position-method retarget (only bone DIRECTIONS matter);
# these give a non-degenerate skeleton so FK produces sane world positions.
SMPLH_REST_OFFSETS: Dict[str, List[float]] = {
    "pelvis": [0.0, 0.90, 0.0],
    "left_hip": [-0.09, 0.0, 0.0], "right_hip": [0.09, 0.0, 0.0],
    "spine1": [0.0, 0.20, 0.0], "left_knee": [0.0, -0.45, 0.0], "right_knee": [0.0, -0.45, 0.0],
    "spine2": [0.0, 0.12, 0.0], "left_ankle": [0.0, -0.43, 0.0], "right_ankle": [0.0, -0.43, 0.0],
    "spine3": [0.0, 0.12, 0.0], "left_foot": [0.0, -0.05, 0.08], "right_foot": [0.0, -0.05, 0.08],
    "neck": [0.0, 0.12, 0.0], "left_collar": [0.05, 0.05, 0.0], "right_collar": [-0.05, 0.05, 0.0],
    "head": [0.0, 0.15, 0.0], "left_shoulder": [0.05, 0.0, 0.0], "right_shoulder": [-0.05, 0.0, 0.0],
    "left_elbow": [0.28, 0.0, 0.0], "right_elbow": [-0.28, 0.0, 0.0],
    "left_wrist": [0.26, 0.0, 0.0], "right_wrist": [-0.26, 0.0, 0.0],
}


def rot6d_to_mat(v: np.ndarray) -> np.ndarray:
    """Convert a 6D rotation representation (Zhou 2019) to a 3x3 rotation matrix."""
    v0, v1 = v[0:3], v[3:6]
    x = v0 / np.linalg.norm(v0)
    z = v1 - np.dot(v1, x) * x
    z = z / np.linalg.norm(z)
    y = np.cross(z, x)
    return np.stack([x, y, z], axis=1)  # columns = x, y, z


def smplh_fk_from_rot6d(rot6d: np.ndarray, transl: np.ndarray) -> np.ndarray:
    """Forward-kinematics from HY-Motion's rot6d + transl to world joint positions.

    rot6d: [T, J, 6] (J >= 22; only the first 22 body joints are used) or [T, 22, 6].
    transl: [T, 3] root translation. Returns posed_joints [T, 22, 3].
    """
    rot6d = np.asarray(rot6d, dtype=float)
    transl = np.asarray(transl, dtype=float)
    T = rot6d.shape[0]
    J = rot6d.shape[1]
    n = 22 if J >= 22 else J
    bone_order, _, _, _ = _skeleton_defs("smplh22")
    parent_of = {name: p for (name, p) in bone_order}
    idx = {name: i for i, (name, _) in enumerate(bone_order)}
    posed = np.zeros((T, 22, 3))
    Rworld = {}
    for t in range(T):
        for name, pname in bone_order:
            i = idx[name]
            R = rot6d[t, i, :] if i < J else np.array([1., 0, 0, 0, 1, 0])
            Rj = rot6d_to_mat(R)
            if pname is None:
                Rworld[name] = Rj
                posed[t, i] = transl[t]
            else:
                pp = parent_of[name]
                off = np.array(SMPLH_REST_OFFSETS[name])
                # world rotation of this joint, then world position:
                # world_pos = parent_pos + Rworld_j @ rest_offset
                Rworld[name] = Rworld[pp] @ Rj
                posed[t, i] = posed[t, idx[pp]] + Rworld[name] @ off
    return posed


def load_posed(npz_path: str) -> Tuple[np.ndarray, int]:
    """Load posed_joints [T,J,3] from a KIMODO/HY-Motion npz."""
    d = np.load(npz_path, allow_pickle=True)
    if "posed_joints" in d:
        posed = d["posed_joints"].astype(np.float64)
    elif "joint_positions" in d:
        posed = d["joint_positions"].astype(np.float64)
    else:
        raise KeyError("npz must contain 'posed_joints' or 'joint_positions' [T,J,3]")
    if posed.ndim != 3 or posed.shape[2] != 3:
        raise ValueError(f"posed_joints must be [T,J,3], got {posed.shape}")
    return posed, posed.shape[1]
