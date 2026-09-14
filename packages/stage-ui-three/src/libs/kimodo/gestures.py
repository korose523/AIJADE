#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gesture definitions for the offline KIMODO → VRM pipeline.

Each entry drives one clip: a text prompt is sent to KIMODO, the resulting
motion NPZ is retargeted to a VRM gesture-clip JSON. ``translate=True`` enables
the hips translation track so locomotion gestures (dance) actually displace the
avatar; upper-body gestures keep it planted.

Clip names MUST match the gesture names used by AIJADE's performance layer
(see GESTURE_TO_VRM_EMOTE / animation-state-machine GESTURES):
wave, nod, disagree, agree, point, shrug, cheer, dance, celebrate.
"""

GESTURES = [
    {"name": "wave", "prompt": "a person waves their right hand to greet someone warmly", "duration": 3.0, "translate": False},
    {"name": "nod", "prompt": "a person nods their head up and down affirmatively", "duration": 2.5, "translate": False},
    {"name": "disagree", "prompt": "a person shakes their head side to side to say no", "duration": 2.5, "translate": False},
    {"name": "agree", "prompt": "a person nods along while listening and agreeing", "duration": 2.5, "translate": False},
    {"name": "point", "prompt": "a person points forward with their right arm to emphasize a point", "duration": 2.5, "translate": False},
    {"name": "shrug", "prompt": "a person shrugs their shoulders in uncertainty", "duration": 2.5, "translate": False},
    {"name": "cheer", "prompt": "a person raises both arms and cheers happily", "duration": 3.5, "translate": False},
    {"name": "dance", "prompt": "a person dances joyfully, swaying their hips and moving their arms to the music", "duration": 5.0, "translate": True},
]

# Default KIMODO model: SOMA-RP-v1.1 (NVIDIA Open Model License — no gated access).
DEFAULT_MODEL = "nvidia/Kimodo-SOMA-RP-v1.1"
DEFAULT_DIFFUSION_STEPS = 100
DEFAULT_SEED = 42
