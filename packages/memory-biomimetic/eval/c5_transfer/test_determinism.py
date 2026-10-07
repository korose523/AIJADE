"""端到端复现性比对的测试。

## 为什么这个测试盯着一句话

`verify_end_to_end_determinism` 返回 `all_identical=True` 时，很容易顺手把它
写成"解码 bit-exact"。**那是错的**：本函数比较的是 `add()` + `search()` 的
最终输出文本，它无法观测 mem0 内部传给 LLM 的采样参数（mem0 不透传 seed/top_k）。
端到端一致**蕴含**解码一致，反之不成立 —— 挂错术语会让论文把一个真的结论
写在一个错的限定语上。

因此测试除了比对逻辑本身，还要锁住 `does_not_establish` 这个字段存在，
让"这个测量不成立什么"随结果一起被记录，而不是靠人记得写。

运行：
    /Users/mac/.workbuddy/binaries/python/envs/default/bin/python -m pytest \
        packages/memory-biomimetic/eval/c5_transfer/test_determinism.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from c5_transfer.adapter import verify_end_to_end_determinism  # noqa: E402


def _art(path: Path, items: list[tuple[str, int, list[str]]]) -> str:
    payload = {
        "sample": {
            "items": [
                {
                    "question_id": qid,
                    "n_add_events": n,
                    "n_retrieved": len(texts),
                    "retrieved": [{"text": t} for t in texts],
                    "inputs_sha256": f"in-{qid}",
                }
                for qid, n, texts in items
            ]
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_identical_runs_are_detected(tmp_path: Path) -> None:
    a = _art(tmp_path / "a.json", [("q1", 3, ["x", "y"]), ("q2", 5, ["z"])])
    b = _art(tmp_path / "b.json", [("q1", 3, ["x", "y"]), ("q2", 5, ["z"])])
    r = verify_end_to_end_determinism(a, b)
    assert r["all_identical"] is True
    assert r["n_identical"] == 2
    assert r["claim"] == "end-to-end-reproducible"


def test_differing_output_is_not_silently_passed(tmp_path: Path) -> None:
    """检索文本不同 ⇒ 必须报 NOT-identical，不能因计数相同而误判通过。"""
    a = _art(tmp_path / "a.json", [("q1", 3, ["x", "y"])])
    b = _art(tmp_path / "b.json", [("q1", 3, ["x", "DIFFERENT"])])
    r = verify_end_to_end_determinism(a, b)
    assert r["all_identical"] is False
    assert r["claim"] == "NOT-identical"
    assert r["n_identical"] == 0


def test_result_always_records_what_it_does_not_establish(tmp_path: Path) -> None:
    """无论一致与否，都必须写明"这不能证明解码 bit-exact"。"""
    a = _art(tmp_path / "a.json", [("q1", 1, ["x"])])
    b = _art(tmp_path / "b.json", [("q1", 1, ["y"])])
    for art_a, art_b in ((a, b), (a, a)):
        r = verify_end_to_end_determinism(art_a, art_b)
        assert r["does_not_establish"] == "substrate-level bit-exact decoding"


def test_empty_comparison_is_not_reported_as_reproducible(tmp_path: Path) -> None:
    """题集为空（交集为 0）时不得报 all_identical=True。

    否则"两次运行都没产出任何可比实例"会被读成"完美复现"。
    """
    a = _art(tmp_path / "a.json", [("q1", 1, ["x"])])
    b = _art(tmp_path / "b.json", [("other", 1, ["x"])])
    r = verify_end_to_end_determinism(a, b)
    assert r["n_items_compared"] == 0
    assert r["all_identical"] is False
    assert r["claim"] == "NOT-identical"