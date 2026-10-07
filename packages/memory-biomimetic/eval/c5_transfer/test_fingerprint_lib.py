"""指纹实现的正确性测试 —— 用**标准测试向量**而非"与TS 侧对拍"。

为什么不对拍：Python 与 TS 两侧若互为参照，两边同时写错时会互相确认通过。
FNV-1a 32-bit 有公开的规范测试向量（`""`、`"a"`、`"foobar"`），用它做锚点，
才能证明本实现算的是FNV-1a 而不是"某种自洽的哈希"。

运行：
    /Users/mac/.workbuddy/binaries/python/envs/default/bin/python -m pytest \
        packages/memory-biomimetic/eval/c5_transfer/test_fingerprint_lib.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from c5_transfer.fingerprint_lib import (  # noqa: E402
    SAMPLING_KEYS,
    fnv1a,
    hash_sampling,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0x811C9DC5),
        ("a", 0xE40C292C),
        ("foobar", 0xBF9CF968),
    ],
)
def test_fnv1a_matches_published_vectors(text: str, expected: int) -> None:
    """FNV-1a 32-bit 规范测试向量。"""
    assert int(fnv1a(text), 16) == expected


def test_sampling_keys_match_typescript_side() -> None:
    """键顺序必须与 `model-substrate/src/fingerprint.ts` 的 SAMPLING_KEYS 一致。

    顺序不同会让同一份采样配置在两套装置下算出不同哈希 —— 而"同一配置不同
    哈希"正是本装置存在的理由，故此项一旦失败必须硬失败。
    """
    assert SAMPLING_KEYS == (
        "temperature",
        "seed",
        "top_p",
        "top_k",
        "repeat_penalty",
        "num_ctx",
        "num_predict",
        "think",
    )


def test_hash_sampling_is_key_order_independent() -> None:
    """与 TS 侧同语义：哈希只取决于键值对，不取决于 dict 插入顺序。"""
    a = {
        "temperature": 0.0,
        "seed": 42,
        "top_p": 1.0,
        "top_k": 1,
        "repeat_penalty": 1.0,
        "num_ctx": 16384,
        "num_predict": 512,
        "think": False,
    }
    b = dict(reversed(list(a.items())))
    assert hash_sampling(a) == hash_sampling(b)


def test_hash_sampling_changes_when_any_param_changes() -> None:
    """任一采样参数变化都必须改变哈希，否则指纹会掩盖解码差异。"""
    base = {
        "temperature": 0.0,
        "seed": 42,
        "top_p": 1.0,
        "top_k": 1,
        "repeat_penalty": 1.0,
        "num_ctx": 16384,
        "num_predict": 512,
        "think": False,
    }
    hashes = {hash_sampling(base)}
    for key in SAMPLING_KEYS:
        mutated = {**base, key: 999 if key != "think" else True}
        hashes.add(hash_sampling(mutated))
    assert len(hashes) == len(SAMPLING_KEYS) + 1