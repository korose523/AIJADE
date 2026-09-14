#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_clips.py — generate real AI motions (KIMODO / HY-Motion) and retarget them
to BOTH a VRM gesture-clip JSON (for AIJADE's VRM avatar) AND a MikuMikuDance .vmd
(for MMD). One text prompt => two deliverables.

This is the offline pipeline that produces the clip files served from
``apps/stage-web/public/kimodo/`` and ``apps/stage-web/public/hy-motion/``.
It requires a CUDA GPU and the model environments (see requirements.txt / README).

Examples:
    # KIMODO (SOMA30) -> VRM + VMD
    HF_ENDPOINT=... TEXT_ENCODER_DEVICE=cpu python build_clips.py --generate --source kimodo

    # HY-Motion (SMPL-H 22) -> VRM + VMD  (needs ~24-26GB VRAM; HY-Motion 1.0-Lite ~24GB)
    USE_HF_MODELS=0 python build_clips.py --generate --source hy-motion

Flags:
    --generate      actually run the model (default: dry validation only)
    --source        kimodo | hy-motion   (default kimodo)
    --out DIR       output directory for clip JSON + VMD + manifest
    --model         model id (default depends on --source)
    --steps         diffusion steps (KIMODO only; default 100)
    --fps           clip fps (default 30)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
DEFAULT_OUT_KIMODO = os.path.join(REPO_ROOT, "apps", "stage-web", "public", "kimodo")
DEFAULT_OUT_HY = os.path.join(REPO_ROOT, "apps", "stage-web", "public", "hy-motion")

sys.path.insert(0, HERE)
from gestures import GESTURES, DEFAULT_MODEL, DEFAULT_DIFFUSION_STEPS, DEFAULT_SEED  # noqa: E402
from motion_common import smplh_fk_from_rot6d  # noqa: E402

RETARGET_VRM_SOMA = os.path.join(HERE, "retarget_soma_to_vrm.py")
RETARGET_VRM_SMPLH = os.path.join(HERE, "retarget_smplh_to_vrm.py")
RETARGET_VMD = os.path.join(HERE, "retarget_to_vmd.py")

DEFAULT_HY_MODEL = "tencent/HY-Motion-1.0"


# ── KIMODO (SOMA30) ──────────────────────────────────────────────────────────
def generate_kimodo(gesture, workdir, model, steps, seed):
    npz = os.path.join(workdir, f"{gesture['name']}.npz")
    cmd = [
        sys.executable, "-m", "kimodo.scripts.generate",
        gesture["prompt"], "--model", model,
        "--duration", str(gesture["duration"]),
        "--num_samples", "1", "--diffusion_steps", str(steps),
        "--no-postprocess", "--seed", str(seed), "--output", npz,
    ]
    print(f"[build] KIMODO '{gesture['name']}': {gesture['prompt']!r}")
    subprocess.run(cmd, check=True)
    return npz if os.path.exists(npz) else None


def retarget_kimodo(npz, gesture, out_dir, fps):
    json_path = os.path.join(out_dir, f"{gesture['name']}.json")
    vmd_path = os.path.join(out_dir, f"{gesture['name']}.vmd")
    vrm_cmd = [sys.executable, RETARGET_VRM_SOMA, npz, "--name", gesture["name"],
               "--out", json_path, "--fps", str(fps)]
    if gesture.get("translate"):
        vrm_cmd.append("--hips")
    subprocess.run(vrm_cmd, check=True)
    subprocess.run([sys.executable, RETARGET_VMD, npz, "--name", gesture["name"],
                    "--out", vmd_path, "--skeleton", "soma30", "--fps", str(fps),
                    "--handedness", "mmd"], check=True)
    return json_path, vmd_path


# ── HY-Motion (SMPL-H 22) ─────────────────────────────────────────────────────
def generate_hymotion(gesture, workdir, model, seed):
    """Run HY-Motion text-to-motion, convert rot6d+transl to a posed_joints npz."""
    try:
        from hymotion.utils.t2m_runtime import T2MRuntime
    except Exception as e:  # pragma: no cover - heavy dep, validated logically
        raise RuntimeError(
            "HY-Motion runtime not importable. Install it in the HY-Motion env "
            "(see H:/refs/HY-Motion-1.0/requirements.txt) and run build_clips "
            "from that env. Error: %s" % e)
    runtime = T2MRuntime(model_path=model)
    out = runtime.generate_motion(gesture["prompt"], seeds_csv=str(seed),
                                  duration=gesture["duration"], cfg_scale=4.0,
                                  output_format="dict")
    rot6d = out["rot6d"]            # [B, T, J, 6]; J>=22 (body + hands)
    transl = out["transl"]          # [B, T, 3]
    rot6d = rot6d[0, :, :22, :] if rot6d.ndim == 4 else rot6d[:, :22, :]
    transl = transl[0] if transl.ndim == 3 else transl
    posed = smplh_fk_from_rot6d(rot6d, transl)  # [T, 22, 3]
    npz = os.path.join(workdir, f"{gesture['name']}.npz")
    import numpy as np
    np.savez(npz, posed_joints=posed.astype(np.float32))
    return npz


def retarget_hymotion(npz, gesture, out_dir, fps):
    json_path = os.path.join(out_dir, f"{gesture['name']}.json")
    vmd_path = os.path.join(out_dir, f"{gesture['name']}.vmd")
    subprocess.run([sys.executable, RETARGET_VRM_SMPLH, npz, "--name", gesture["name"],
                    "--out", json_path, "--fps", str(fps)], check=True)
    subprocess.run([sys.executable, RETARGET_VMD, npz, "--name", gesture["name"],
                    "--out", vmd_path, "--skeleton", "smplh22", "--fps", str(fps),
                    "--handedness", "mmd"], check=True)
    return json_path, vmd_path


# ── manifest ──────────────────────────────────────────────────────────────────
def write_manifest(out_dir, clips):
    manifest = {"version": "1.0.0", "formats": ["vrm", "vmd"], "clips": clips}
    path = os.path.join(out_dir, "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return path


def main():
    ap = argparse.ArgumentParser(description="Build VRM + VMD clips from AI motion models")
    ap.add_argument("--generate", action="store_true", help="run the model (otherwise dry-run)")
    ap.add_argument("--source", default="kimodo", choices=["kimodo", "hy-motion"])
    ap.add_argument("--out", default=None, help="output dir (default per source)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--steps", type=int, default=DEFAULT_DIFFUSION_STEPS)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args()

    model = args.model or (DEFAULT_MODEL if args.source == "kimodo" else DEFAULT_HY_MODEL)
    out_dir = args.out or (DEFAULT_OUT_KIMODO if args.source == "kimodo" else DEFAULT_OUT_HY)
    os.makedirs(out_dir, exist_ok=True)

    if not args.generate:
        print(f"[build] dry-run: source={args.source}, model={model}, "
              f"{len(GESTURES)} gestures -> {out_dir}")
        for g in GESTURES:
            print(f"  - {g['name']}: translate={g.get('translate', False)}")
        print("[build] pass --generate to actually run the model on GPU.")
        return

    workdir = tempfile.mkdtemp(prefix=f"{args.source}_clips_")
    clips = []
    gen = generate_kimodo if args.source == "kimodo" else generate_hymotion
    ret = retarget_kimodo if args.source == "kimodo" else retarget_hymotion
    try:
        for g in GESTURES:
            npz = gen(g, workdir, model, args.steps, args.seed)
            if not npz:
                print(f"[build] WARNING: no NPZ for {g['name']}, skipping")
                continue
            ret(npz, g, out_dir, args.fps)
            clips.append(g["name"])
    finally:
        print(f"[build] intermediate NPZs left in {workdir}")

    write_manifest(out_dir, clips)
    print(f"[build] DONE: {len(clips)} clips (VRM + VMD) -> {out_dir}")


if __name__ == "__main__":
    main()
