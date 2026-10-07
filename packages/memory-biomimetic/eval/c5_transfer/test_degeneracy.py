"""退化守卫的判定逻辑测试 —— 保护本实验最容易出错的那一步。

## 为什么这个测试比看起来重要

`degeneracy_measured.verdict` 只有三种合法取值���
`reachable` / `CONSTRUCTIVE_ZERO_BY_MEASUREMENT` /
`APPARATUS_INADEQUATE_NOT_CONSTRUCTIVE_ZERO`。

中间那种是最容易被误报成"我们没测出mem0 的能力"的一档，而最后那档是本项目
"先让装置不能发表不可复现的数字"立场的直接体现：如果底座模型压根没吐出任何
可入库事实，那么"检索为空"的原因是**装置失效**，把它写成"构造性零"就是
把设备故障讲成了科学发现。因此判定逻辑必须有测试锁住。

运行：
    /Users/mac/.workbuddy/binaries/python/envs/default/bin/python -m pytest \
        packages/memory-biomimetic/eval/c5_transfer/test_degeneracy.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from c5_transfer.degeneracy import classify_degeneracy  # noqa: E402


def _rec(ok: bool, events: int | None, retrieved: int) -> dict:
    return {"ok": ok, "n_add_events": events, "n_retrieved": retrieved}


def test_no_successful_instance_is_no_data() -> None:
    """全部实例失败 ⇒ 无观测量，既不是可达也不是构造性零。

    注意 `all_retrieved_zero` 必须为 **False**：没有任何成功实例时，我们对
    "检索是否为空"根本没有观测，而不是观测到"全为空"。把它记成 True 会让
    一次全崩溃的运行看起来像一次干净的构造性零。
    """
    r = classify_degeneracy([_rec(False, None, 0), _rec(False, None, 0)])
    assert r["verdict"] == "NO_DATA"
    assert r["extraction_dead"] is False
    assert r["all_retrieved_zero"] is False
    assert r["n_succeeded"] == 0
    assert r["n_failed"] == 2


def test_extraction_dead_is_not_reported_as_constructive_zero() -> None:
    """抽取事件全为 0 时必须判为装置失效，而不是构造性零。

    这是本测试存在的核心理由：把设备故障讲成"构造性零"会让论文出现
    一个看起来像科学结论、实则源于底座模型缺陷的数字。
    """
    r = classify_degeneracy([_rec(True, 0, 0), _rec(True, 0, 0)])
    assert r["verdict"] == "APPARATUS_INADEQUATE_NOT_CONSTRUCTIVE_ZERO"
    assert r["extraction_dead"] is True
    assert "底座" in r["note"]


def test_all_retrieved_zero_with_events_is_constructive_zero() -> None:
    """有抽取产出但检索恒空 ⇒ 这才是真正的构造性零。"""
    r = classify_degeneracy([_rec(True, 12, 0), _rec(True, 20, 0)])
    assert r["verdict"] == "CONSTRUCTIVE_ZERO_BY_MEASUREMENT"
    assert r["extraction_dead"] is False
    assert r["all_retrieved_zero"] is True


def test_any_nonzero_retrieval_is_reachable() -> None:
    """出现非 0 检索 ⇒ 操纵可达。"""
    r = classify_degeneracy([_rec(True, 12, 5), _rec(True, 20, 0)])
    assert r["verdict"] == "reachable"
    assert r["any_retrieved_zero"] is True
    assert r["all_retrieved_zero"] is False


def test_failed_instances_are_counted_but_not_treated_as_zero() -> None:
    """失败实例计入 n_failed，但不得被当作"检索为空"参与零的判定。

    否则一次崩溃就会被算成一次构造性零 —— 这是把设备故障算进结论的又一条路径。
    """
    r = classify_degeneracy([_rec(True, 12, 7), _rec(False, None, 0)])
    assert r["verdict"] == "reachable"
    assert r["n_succeeded"] == 1
    assert r["n_failed"] == 1


@pytest.mark.parametrize("events", [None, 0])
def test_missing_event_count_is_treated_as_dead(events: int | None) -> None:
    """事件数缺失(None) 与 0 同等对待：都没有可入库事实。"""
    r = classify_degeneracy([_rec(True, events, 0)])
    assert r["verdict"] == "APPARATUS_INADEQUATE_NOT_CONSTRUCTIVE_ZERO"