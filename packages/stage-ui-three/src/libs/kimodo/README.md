# KIMODO / HY-Motion → VRM Gesture Pipeline

Offline gesture pipeline that turns a text prompt into a **VRM gesture-clip JSON**
consumed by `packages/stage-ui-three/src/libs/kimodo-gestures.ts` (`buildVRMAnimation`).

## 1. Where the motion comes from

| Source | Model | Skeleton | Notes |
|--------|-------|----------|-------|
| **HY-Motion 1.0** | Tencent Hunyuan DiT + flow-matching text-to-motion, ~1B params. 3000 h pretrain + 400 h finetune + RLHF/Reward. Covers 200 motion categories / 6 classes (locomotion, daily, fitness, game, social, sports). Repo: `Tencent-Hunyuan/HY-Motion-1.0`. | **SMPL-H 22-joint** (`posed_joints` [T,22,3] world positions; raw output is `rot6d` + `transl`) | Entrypoint: `retarget_smplh_to_vrm.py` |
| **KIMODO** | Offline gesture generator (SOMA 30/77-joint or SMPL-X 22-joint). | **SOMA30** (humanoid core) or SMPL-X | Entrypoint: `retarget_soma_to_vrm.py` |

Both entrypoints produce the **same output schema** (see §4) so the TS side needs
only one loader.

## 2. Pipeline stages

```
text prompt
   │  HY-Motion.generate_motion()  →  rot6d + transl
   │  (or KIMODO → SOMA/SMPL-X posed_joints)
   ▼
body-model LBS / FBX export  →  posed_joints [T, J, 3]   (world joint positions)
   ▼
retarget_*(npz, --name, --out, --fps, --hips, --scale)   ← position method
   ▼
VRM gesture-clip JSON  (bones: {vrmBone: {times, rotation}}, optional translation)
   ▼
kimodo-gestures.ts  buildVRMAnimation()  →  plays on the live VRM avatar
```

### Position method (validated)
Each bone's local rotation is derived from the **positions** of the bone and its
children (not from raw joint rotations). This yields clean **unit quaternions**
and is robust to axis/scale mismatches between the source skeleton and VRM human
bones — preferred over a rotation-matrix transfer. An optional **hips translation**
track is derived from the Hips world position so dance/walk actually displaces the
avatar instead of floating in place.

## 3. Usage

```bash
# HY-Motion (SMPL-H 22-joint) → VRM
python retarget_smplh_to_vrm.py motion.npz --name wave --out wave.json \
    --fps 30 --hips --scale 1.0

# KIMODO (SOMA30 / auto-detect by joint count) → VRM
python retarget_soma_to_vrm.py motion.npz --name wave --out wave.json \
    --fps 30 --hips --scale 1.0 --skeleton auto
```

| Flag | Meaning |
|------|---------|
| `--name` | clip name embedded in the JSON (must match what TS requests) |
| `--fps` | source fps (default 30) |
| `--hips` | emit hips `translation` track |
| `--scale` | uniform scale applied to positions before retarget |
| `--skeleton` | `auto` (default, picks by joint count) \| `soma30` \| `smplh22` |

## 4. Output schema (contract with `kimodo-gestures.ts`)

```jsonc
{
  "name": "wave",
  "fps": 30.0,
  "duration": 2.0,
  "bones": {
    "hips":   { "times": [0.0, 0.033, ...], "rotation": [[x,y,z,w], ...] },
    "spine":  { "times": [...], "rotation": [...] },
    // ...all mapped VRM human bones (chest, head, neck, *UpperArm,
    //     *LowerArm, *Hand, *UpperLeg, *LowerLeg, *Foot, *Toes, jaw, eyes)
  },
  "translation": { "times": [...], "values": [[x,y,z], ...] }   // only if --hips
}
```

VRM bone names follow the VRM humanoid spec (`hips`, `spine`, `chest`, `upperChest`,
`neck`, `head`, `jaw`, `leftEye`, `rightEye`, `leftShoulder`, `leftUpperArm`,
`leftLowerArm`, `leftHand`, `rightShoulder`, `rightUpperArm`, `rightLowerArm`,
`rightHand`, `leftUpperLeg`, `leftLowerLeg`, `leftFoot`, `leftToes`,
`rightUpperLeg`, `rightLowerLeg`, `rightFoot`, `rightToes`).

## 5. Environment

See `requirements.txt`. Recommended (CUDA) setup:

```bash
uv venv -p 3.11 kimodo_env
uv pip install --python kimodo_env/Scripts/python.exe torch torchvision --torch-backend cu128
SKIP_MOTION_CORRECTION_IN_SETUP=1 uv pip install --python kimodo_env/Scripts/python.exe -e <kimodo_repo>
HF_ENDPOINT=https://hf-mirror.com TEXT_ENCODER_DEVICE=cpu python build_clips.py --generate
```

`numpy` + `scipy` are the only hard deps for the **retarget scripts themselves**
(`motion_common.py`); the heavier stack above is only needed to *generate* motions
from text.

## 6. Verification (no GPU / no real model needed)

`kimodo_dryrun.py` fabricates a synthetic SOMA30 `posed_joints` (a right-arm wave)
and runs the full retarget end-to-end, asserting the output JSON matches the
`buildVRMAnimation` contract:

```bash
python kimodo_dryrun.py
# → schema valid: True  (25 VRM bones, 60 frames/bone, hips translation present)
```

`py_compile` of all retarget scripts must pass:
```bash
python -m py_compile retarget_smplh_to_vrm.py retarget_soma_to_vrm.py \
                    retarget_to_vmd.py motion_common.py build_clips.py gestures.py
```

## 7. Type gate

The TS consumer (`stage-ui-three`) must stay type-clean:

```bash
pnpm --filter @proj-aijade/stage-ui-three run typecheck
```

> Note: `pmx-loader.ts` imports `three-stdlib` via a **variable specifier** so the
> typecheck does not fail when the optional `three-stdlib` (PMX/PMD) dependency is
> absent. PMX/PMD loading is best-effort and degrades gracefully.
