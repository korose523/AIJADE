#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_fusion_clips.py — fabricate persona-tagged KIMODO + HY-Motion VRM gesture
clips WITHOUT a GPU or the real models, so the runtime fusion actually has clips
to select from out-of-the-box.

It mirrors the EXACT position-method retarget used by `retarget_soma_to_vrm.py`
(KIMODO / SOMA30) and `motion_common.build_vrm_json` (HY-Motion / SMPL-H22), so
the produced JSON is byte-compatible with `demo_dance.json` and the contract in
`kimodo-gestures.ts` (buildVRMAnimation). The only difference: every clip carries
`intents` + `source` tags so the persona fusion selector can match them.

Pure numpy — no scipy, no torch, no network. Run:

  cd H:/AIJADE/packages/stage-ui-three/src/libs/kimodo
  python gen_fusion_clips.py

Outputs (written next to this script's configured PUBLIC dirs):
  apps/stage-web/public/kimodo/{wave,nod,agree,point,shrug,think}.json + manifest.json
  apps/stage-web/public/hy-motion/{reach_out,lean_in,sway,fidget,look_away,affirm}.json + manifest.json
"""
from __future__ import annotations

import json
import math
import os

import numpy as np

# ──_paths ────────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))


def repo_root():
    """Walk up from this file until we find the AIJADE repo root (contains apps/stage-web/public)."""
    d = HERE
    for _ in range(8):
        if os.path.isdir(os.path.join(d, "apps", "stage-web", "public")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    # fallback: assume 5 levels up from packages/stage-ui-three/src/libs/kimodo
    return os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))


ROOT = repo_root()
KIMODO_DIR = os.path.join(ROOT, "apps", "stage-web", "public", "kimodo")
HYMOTION_DIR = os.path.join(ROOT, "apps", "stage-web", "public", "hy-motion")

FPS = 30.0


# ── quaternion + skeleton defs (mirrors retarget_soma_to_vrm.py) ──────────────
def quat_from_to(a, b):
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


SOMA30_BONES = [
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

VRM_MAP = {
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

SOMA_REST = {
    "Hips": (0.0, 0.80, 0.0), "Spine1": (0.0, 0.95, 0.0), "Spine2": (0.0, 1.10, 0.0),
    "Chest": (0.0, 1.25, 0.0), "Neck1": (0.0, 1.45, 0.0), "Neck2": (0.0, 1.50, 0.0),
    "Head": (0.0, 1.60, 0.0), "Jaw": (0.0, 1.57, 0.05), "LeftEye": (0.04, 1.62, 0.08),
    "RightEye": (-0.04, 1.62, 0.08), "LeftShoulder": (0.05, 1.30, 0.0),
    "LeftArm": (0.18, 1.25, 0.0), "LeftForeArm": (0.35, 1.20, 0.0),
    "LeftHand": (0.50, 1.15, 0.0), "LeftHandThumbEnd": (0.52, 1.15, 0.02),
    "LeftHandMiddleEnd": (0.53, 1.15, 0.0), "RightShoulder": (-0.05, 1.30, 0.0),
    "RightArm": (-0.18, 1.25, 0.0), "RightForeArm": (-0.35, 1.20, 0.0),
    "RightHand": (-0.50, 1.15, 0.0), "RightHandThumbEnd": (-0.52, 1.15, 0.02),
    "RightHandMiddleEnd": (-0.53, 1.15, 0.0), "LeftLeg": (0.09, 0.45, 0.0),
    "LeftShin": (0.09, 0.20, 0.0), "LeftFoot": (0.09, 0.03, 0.05),
    "LeftToeBase": (0.09, 0.02, 0.15), "RightLeg": (-0.09, 0.45, 0.0),
    "RightShin": (-0.09, 0.20, 0.0), "RightFoot": (-0.09, 0.03, 0.05),
    "RightToeBase": (-0.09, 0.02, 0.15),
}

SMPLH22_BONES = [
    ("pelvis", None), ("left_hip", "pelvis"), ("right_hip", "pelvis"),
    ("spine1", "pelvis"), ("left_knee", "left_hip"), ("right_knee", "right_hip"),
    ("spine2", "spine1"), ("left_ankle", "left_knee"), ("right_ankle", "right_knee"),
    ("spine3", "spine2"), ("left_foot", "left_ankle"), ("right_foot", "right_ankle"),
    ("neck", "spine3"), ("left_collar", "neck"), ("right_collar", "neck"),
    ("head", "neck"), ("left_shoulder", "left_collar"), ("right_shoulder", "right_collar"),
    ("left_elbow", "left_shoulder"), ("right_elbow", "right_shoulder"),
    ("left_wrist", "left_elbow"), ("right_wrist", "right_elbow"),
]

SMPLH_VRM_MAP = {
    "pelvis": "hips", "left_hip": "leftUpperLeg", "right_hip": "rightUpperLeg",
    "spine1": "spine", "spine2": "chest", "spine3": "upperChest", "neck": "neck",
    "left_collar": "leftShoulder", "right_collar": "rightShoulder", "head": "head",
    "left_shoulder": "leftUpperArm", "left_elbow": "leftLowerArm", "left_wrist": "leftHand",
    "right_shoulder": "rightUpperArm", "right_elbow": "rightLowerArm", "right_wrist": "rightHand",
    "left_knee": "leftLowerLeg", "right_knee": "rightLowerLeg",
    "left_ankle": "leftFoot", "right_ankle": "rightFoot",
    "left_foot": "leftToes", "right_foot": "rightToes",
}

SMPLH_REST_OFFSETS = {
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


# ── children / subtree helpers ───────────────────────────────────────────────
def build_children(bone_order):
    children = {n: [] for n, _ in bone_order}
    for n, p in bone_order:
        if p:
            children[p].append(n)
    return children


def subtree(root, children):
    out, stack = [], [root]
    while stack:
        n = stack.pop()
        out.append(n)
        stack.extend(children[n])
    return out


def apply_offset(posed, name2idx, nodes, offset):
    """Add `offset` (T,3) to every joint in `nodes` for every frame."""
    for n in nodes:
        ji = name2idx[n]
        posed[:, ji, :] += offset


# ── SOMA30 (KIMODO) fabrication ──────────────────────────────────────────────
def fabricate_soma(name, seconds):
    T = int(round(seconds * FPS))
    J = len(SOMA30_BONES)
    posed = np.zeros((T, J, 3), dtype=float)
    for ji, (bn, _) in enumerate(SOMA30_BONES):
        x, y, z = SOMA_REST[bn]
        posed[:, ji, 0] = x
        posed[:, ji, 1] = y
        posed[:, ji, 2] = z
    children = build_children(SOMA30_BONES)
    name2idx = {n: i for i, (n, _) in enumerate(SOMA30_BONES)}
    t = np.arange(T) / FPS
    phase = 2 * np.pi * t

    if name == "wave":
        off = np.stack([0.05 * np.sin(phase * 0.5),
                        np.zeros(T),
                        0.18 * np.sin(phase * (2 * np.pi * 0.8 / FPS * FPS))], axis=1)
        # simpler: 2 oscillations over the clip
        wave = 0.18 * np.sin(np.linspace(0, 4 * np.pi, T))
        off = np.stack([0.04 * np.sin(np.linspace(0, 2 * np.pi, T)), np.zeros(T), wave], axis=1)
        apply_offset(posed, name2idx, subtree("RightArm", children), off)
    elif name == "nod":
        down = -0.05 * np.sin(np.linspace(0, 2 * np.pi, T))
        apply_offset(posed, name2idx, subtree("Neck1", children), np.stack([np.zeros(T), down, np.zeros(T)], 1))
    elif name == "agree":
        down = -0.045 * np.sin(np.linspace(0, 4 * np.pi, T))
        apply_offset(posed, name2idx, subtree("Neck1", children), np.stack([np.zeros(T), down, np.zeros(T)], 1))
        fwd = 0.03 * np.ones(T)
        apply_offset(posed, name2idx, subtree("Spine1", children), np.stack([np.zeros(T), np.zeros(T), fwd], 1))
    elif name == "point":
        off = np.stack([np.zeros(T), 0.05 * np.ones(T), 0.22 * np.ones(T)], 1)
        apply_offset(posed, name2idx, subtree("RightArm", children), off)
    elif name == "shrug":
        up = 0.05 * np.ones(T)
        apply_offset(posed, name2idx, subtree("LeftShoulder", children), np.stack([np.zeros(T), up, np.zeros(T)], 1))
        apply_offset(posed, name2idx, subtree("RightShoulder", children), np.stack([np.zeros(T), up, np.zeros(T)], 1))
    elif name == "think":
        up = 0.16 * np.ones(T) + 0.01 * np.sin(phase)
        fwd = 0.10 * np.ones(T)
        apply_offset(posed, name2idx, subtree("LeftForeArm", children), np.stack([np.zeros(T), up, fwd], 1))
    else:
        raise ValueError(f"unknown soma clip {name}")

    # subtle whole-body idle bob (gives a non-degenerate hips translation track)
    bob = np.stack([np.zeros(T), 0.01 * np.sin(np.linspace(0, 2 * np.pi, T)), np.zeros(T)], 1)
    for ji in range(J):
        posed[:, ji, :] += bob
    return posed


def retarget_soma(posed, name, fps=FPS, hips=True, scale=1.0):
    T, J, _ = posed.shape
    name2idx = {n: i for i, (n, _) in enumerate(SOMA30_BONES)}
    times = [round(i / fps, 5) for i in range(T)]
    bones = {}
    for soma_name, vrm_bone in VRM_MAP.items():
        if vrm_bone is None:
            continue
        ci = name2idx.get(soma_name)
        if ci is None:
            continue
        pi = name2idx.get("Spine1") if soma_name == "Hips" else name2idx.get(dict(SOMA30_BONES)[soma_name])
        if pi is None:
            continue
        child, parent = posed[:, ci, :], posed[:, pi, :]
        rd = child[0] - parent[0]
        if np.linalg.norm(rd) < 1e-9:
            continue
        rots = []
        for tt in range(T):
            td = child[tt] - parent[tt]
            if np.linalg.norm(td) < 1e-9:
                td = rd
            q = quat_from_to(rd, td)
            rots.append([float(q[0]), float(q[1]), float(q[2]), float(q[3])])
        bones[vrm_bone] = {"times": times, "rotation": rots}
    out = {"name": name, "fps": fps, "duration": round(T / fps, 4),
           "restHipsPosition": [0.0, 0.8, 0.0], "bones": bones}
    if hips:
        hip = posed[:, name2idx["Hips"], :]
        rest = hip[0]
        out["translation"] = {"times": times,
                              "position": [[float((hip[tt, 0] - rest[0]) * scale),
                                            float((hip[tt, 1] - rest[1]) * scale),
                                            float((hip[tt, 2] - rest[2]) * scale)] for tt in range(T)]}
    return out


# ── SMPL-H22 (HY-Motion) fabrication ────────────────────────────────────────
def fabricate_smplh_rest_world():
    world = {}
    children = build_children(SMPLH22_BONES)
    name2idx = {n: i for i, (n, _) in enumerate(SMPLH22_BONES)}
    # recursive FK from offsets with identity rotations
    def fk(n):
        if n in world:
            return world[n]
        p = dict(SMPLH22_BONES)[n]
        base = fk(p) if p else np.zeros(3)
        world[n] = base + np.array(SMPLH_REST_OFFSETS[n], dtype=float)
        return world[n]
    for n, _ in SMPLH22_BONES:
        fk(n)
    return world, name2idx, children


def fabricate_smplh(name, seconds):
    T = int(round(seconds * FPS))
    J = len(SMPLH22_BONES)
    rest_world, name2idx, children = fabricate_smplh_rest_world()
    posed = np.zeros((T, J, 3), dtype=float)
    for ji, (bn, _) in enumerate(SMPLH22_BONES):
        posed[:, ji, :] = rest_world[bn]
    t = np.arange(T) / FPS
    center = np.array(rest_world["pelvis"], dtype=float)

    if name == "reach_out":
        ext = 0.6 + 0.4 * np.sin(np.linspace(0, 2 * np.pi, T))
        fwd = 0.16 * ext
        l = np.stack([0.04 * np.ones(T), 0.02 * np.ones(T), fwd], 1)
        r = np.stack([-0.04 * np.ones(T), 0.02 * np.ones(T), fwd], 1)
        apply_offset(posed, name2idx, subtree("left_shoulder", children), l)
        apply_offset(posed, name2idx, subtree("right_shoulder", children), r)
    elif name == "lean_in":
        fwd = 0.10 + 0.04 * np.sin(np.linspace(0, 2 * np.pi, T))
        apply_offset(posed, name2idx, subtree("spine2", children), np.stack([np.zeros(T), np.zeros(T), fwd], 1))
    elif name == "sway":
        x = 0.06 * np.sin(np.linspace(0, 2 * np.pi, T))
        # whole-body side sway via pelvis translation
        off = np.stack([x, np.zeros(T), np.zeros(T)], 1)
        for ji in range(J):
            posed[:, ji, :] += off
        # slight upper-body counter-sway for a natural twist
        cx = 0.02 * np.sin(np.linspace(0, 2 * np.pi, T) + np.pi)
        apply_offset(posed, name2idx, subtree("spine3", children), np.stack([cx, np.zeros(T), np.zeros(T)], 1))
    elif name == "fidget":
        x = 0.03 * np.sin(np.linspace(0, 8 * np.pi, T))
        off = np.stack([x, np.zeros(T), np.zeros(T)], 1)
        for ji in range(J):
            posed[:, ji, :] += off
        jit = np.stack([np.zeros(T), np.zeros(T), 0.02 * np.sin(np.linspace(0, 10 * np.pi, T))], 1)
        apply_offset(posed, name2idx, subtree("right_wrist", children), jit)
    elif name == "look_away":
        off = np.stack([0.05 * np.ones(T), 0.0 * np.ones(T), -0.02 * np.ones(T)], 1)
        apply_offset(posed, name2idx, subtree("head", children), off)
        apply_offset(posed, name2idx, subtree("neck", children), off * 0.4)
    elif name == "affirm":
        down = -0.03 * np.sin(np.linspace(0, 4 * np.pi, T))
        apply_offset(posed, name2idx, subtree("neck", children), np.stack([np.zeros(T), down, np.zeros(T)], 1))
        fwd = 0.10 * (0.6 + 0.4 * np.sin(np.linspace(0, 2 * np.pi, T)))
        l = np.stack([0.03 * np.ones(T), 0.0 * np.ones(T), fwd], 1)
        r = np.stack([-0.03 * np.ones(T), 0.0 * np.ones(T), fwd], 1)
        apply_offset(posed, name2idx, subtree("left_shoulder", children), l)
        apply_offset(posed, name2idx, subtree("right_shoulder", children), r)
    else:
        raise ValueError(f"unknown smplh clip {name}")
    return posed


def retarget_smplh(posed, name, fps=FPS, hips=True, scale=1.0):
    bone_order, vrm_map, _, root_name = SMPLH22_BONES, SMPLH_VRM_MAP, None, "pelvis"
    world = {}
    name2idx = {n: i for i, (n, _) in enumerate(bone_order)}
    for n, p in bone_order:
        ci = name2idx.get(n)
        pi = name2idx.get(p) if p else None
        if ci is None:
            world[n] = np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (posed.shape[0], 1))
            continue
        if pi is None:
            world[n] = np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (posed.shape[0], 1))
            continue
        rest = posed[0, ci] - posed[0, pi]
        quats = np.empty((posed.shape[0], 4))
        for tt in range(posed.shape[0]):
            cur = posed[tt, ci] - posed[tt, pi]
            quats[tt] = quat_from_to(rest, cur)
        world[n] = quats
    T = posed.shape[0]
    times = [round(i / fps, 5) for i in range(T)]
    bones = {}
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
        for tt in range(T):
            td = child[tt] - parent[tt]
            if np.linalg.norm(td) < 1e-9:
                td = rd
            q = quat_from_to(rd, td)
            rots.append([float(q[0]), float(q[1]), float(q[2]), float(q[3])])
        bones[vrm_bone] = {"times": times, "rotation": rots}
    out = {"name": name, "fps": fps, "duration": round(T / fps, 4),
           "restHipsPosition": [0.0, 0.8, 0.0], "bones": bones}
    if hips:
        ri = name2idx.get(root_name)
        if ri is not None:
            hip = posed[:, ri, :]
            rest = hip[0]
            out["translation"] = {"times": times,
                                  "position": [[float((hip[tt, 0] - rest[0]) * scale),
                                                float((hip[tt, 1] - rest[1]) * scale),
                                                float((hip[tt, 2] - rest[2]) * scale)] for tt in range(T)]}
    return out


# ── clip plan (name -> intents + source + seconds) ──────────────────────────
KIMODO_CLIPS = [
    ("wave", ["playful", "open"], 2.0),
    ("nod", ["agreeable"], 2.0),
    ("agree", ["agreeable", "confident"], 2.0),
    ("point", ["alert", "confident"], 2.0),
    ("shrug", ["bashful", "thoughtful"], 2.0),
    ("think", ["thoughtful"], 2.0),
]
HYMOTION_CLIPS = [
    ("reach_out", ["open", "tender"], 3.0),
    ("lean_in", ["open", "confident"], 3.0),
    ("sway", ["playful", "wistful"], 3.0),
    ("fidget", ["restless"], 2.5),
    ("look_away", ["wistful", "bashful"], 3.0),
    ("affirm", ["agreeable", "confident"], 3.0),
]


def assert_schema(doc, min_bones=10):
    bones = doc.get("bones", {})
    assert doc.get("name"), "name missing"
    assert isinstance(doc.get("fps"), (int, float)), "fps missing"
    assert isinstance(doc.get("duration"), (int, float)), "duration missing"
    assert len(bones) >= min_bones, f"too few bones: {len(bones)}"
    n_frames = None
    for b in bones.values():
        assert "rotation" in b and "times" in b, "bone missing rotation/times"
        vals = b["rotation"]
        for q in vals:
            n = math.sqrt(sum(x * x for x in q))
            assert abs(n - 1.0) < 1e-3, f"non-unit quaternion norm={n}"
        if n_frames is None:
            n_frames = len(b["times"])
        else:
            assert len(b["times"]) == n_frames, "inconsistent frame counts"
    if "translation" in doc:
        assert len(doc["translation"]["position"]) == n_frames, "translation frame mismatch"
    return n_frames


def write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def main():
    os.makedirs(KIMODO_DIR, exist_ok=True)
    os.makedirs(HYMOTION_DIR, exist_ok=True)

    kimodo_manifest = {"version": "1.0", "clips": []}
    hymotion_manifest = {"version": "1.0", "clips": []}

    print("=== KIMODO (SOMA30) persona-tagged clips ===")
    for name, intents, secs in KIMODO_CLIPS:
        posed = fabricate_soma(name, secs)
        doc = retarget_soma(posed, name, hips=True)
        doc["intents"] = intents
        doc["source"] = "kimodo"
        n = assert_schema(doc)
        out = os.path.join(KIMODO_DIR, f"{name}.json")
        write_json(out, doc)
        kimodo_manifest["clips"].append({"name": name, "source": "kimodo", "intents": intents})
        print(f"  {name:8s} -> {out}  bones={len(doc['bones'])} frames={n} intents={intents}")

    # reference the pre-existing real KIMODO dance clip
    demo = os.path.join(KIMODO_DIR, "demo_dance.json")
    if os.path.exists(demo):
        kimodo_manifest["clips"].insert(0, {"name": "demo_dance", "source": "kimodo", "intents": ["playful"]})
        print(f"  demo_dance (pre-existing) -> referenced in manifest")

    write_json(os.path.join(KIMODO_DIR, "manifest.json"), kimodo_manifest)
    print(f"  manifest.json -> {os.path.join(KIMODO_DIR, 'manifest.json')}")

    print("=== HY-Motion (SMPL-H22) persona-tagged clips ===")
    for name, intents, secs in HYMOTION_CLIPS:
        posed = fabricate_smplh(name, secs)
        doc = retarget_smplh(posed, name, hips=True)
        doc["intents"] = intents
        doc["source"] = "hy-motion"
        n = assert_schema(doc)
        out = os.path.join(HYMOTION_DIR, f"{name}.json")
        write_json(out, doc)
        hymotion_manifest["clips"].append({"name": name, "source": "hy-motion", "intents": intents})
        print(f"  {name:10s} -> {out}  bones={len(doc['bones'])} frames={n} intents={intents}")

    write_json(os.path.join(HYMOTION_DIR, "manifest.json"), hymotion_manifest)
    print(f"  manifest.json -> {os.path.join(HYMOTION_DIR, 'manifest.json')}")

    total = len(kimodo_manifest["clips"]) + len(hymotion_manifest["clips"])
    print(f"\nAll {total} clips generated + tagged + validated. KIMODO×HY-Motion fusion library ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
