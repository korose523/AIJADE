"""FNV-1a 与采样哈希 —— 与 AIJADE `packages/model-substrate/src/fingerprint.ts` 同算法。

为什么要在Python 侧**重写一遍**而不是从 TS 侧导入：mem0 是Python 库，被测侧的
指纹必须在被测侧算出来（否则就成了"我们的装置声称对方可复现"）。两份实现用同一
算法与同一 schema，因此指纹**可比**；若算法不同，比的就是两个不同定义的哈希。

算法与常量逐字对齐 TS 侧：
  初始值 0x811C9DC5，质数 0x01000193，按 UTF-16 码元逐字符异或后乘。
"""

from __future__ import annotations

from typing import Any

SAMPLING_KEYS: tuple[str, ...] = (
    "temperature",
    "seed",
    "top_p",
    "top_k",
    "repeat_penalty",
    "num_ctx",
    "num_predict",
    "think",
)


def fnv1a(input_str: str) -> str:
    """FNV-1a 32-bit，返回 8 位十六进制。

    按 **UTF-16 码元** 迭代以匹配 TS 侧 `charCodeAt`：Python 的 `str` 按码点迭代，
    对非 BMP 字符会比 JS 多一迭代。实验中的采样配置全是 ASCII，故当前无实际差异，
    但保留该说明是为了避免"以后换个含 emoji 的模型名时静默算出不同哈希"。
    """
    hash_val = 0x811C9DC5
    # 逐 UTF-16 码元处理（JS 的 charCodeAt 语义），非 BMP 字符会占两字节。
    encoded = input_str.encode("utf-16-le")
    for i in range(0, len(encoded), 2):
        code = encoded[i] | (encoded[i + 1] << 8)
        hash_val ^= code
        hash_val = (hash_val * 0x01000193) & 0xFFFFFFFF
    return f"{hash_val:08x}"


def hash_sampling(sampling: dict[str, Any]) -> str:
    """采样配置的顺序无关哈希。

    键顺序必须与 TS 侧 `SAMPLING_KEYS.map(k => ...)` 一致，否则两个装置
    对同一配置会给出不同哈希 —— 而"同一配置不同哈希"正是本装置要防的失败。
    """
    joined = ";".join(f"{k}={sampling[k]}" for k in SAMPLING_KEYS)
    return fnv1a(joined)