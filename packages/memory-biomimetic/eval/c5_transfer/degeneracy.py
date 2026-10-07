"""退化守卫的判定逻辑 —— 从 runner 中抽出以便单测。

抽出来的理由不是"整洁"，而是**这条判定是本实验最容易出错的一步**：
它决定产物里写"操纵可达"还是"构造性零"，而后者若被误报，会让论文出现一个
看起来像科学结论、实则源于底座模型缺陷的数字。因此必须能被独立测试锁住。

三种合法判定：
  · `reachable` —— 存在非 0 检索，操纵可达，零结果（若有）才是经验零；
  · `CONSTRUCTIVE_ZERO_BY_MEASUREMENT` —— 有抽取产出但检索恒空；
  · `APPARATUS_INADEQUATE_NOT_CONSTRUCTIVE_ZERO` —— 抽取事件全为 0，
    此时"检索为空"由底座缺陷造成，**不得**报为构造性零；
  · `NO_DATA` —— 无成功实例，守卫未获得观测量。
"""

from __future__ import annotations

from typing import Any


def classify_degeneracy(records: list[dict[str, Any]]) -> dict[str, Any]:
    """对单题记录列表给出退化守卫判定。

    `records` 中每项形如
    `{"ok": bool, "n_add_events": int | None, "n_retrieved": int}`。

    关键约定：**失败实例（ok=False）只计入 n_failed，不参与"是否为零"的判定**。
    否则一次崩溃会被算成一次构造性零 —— 那是把设备故障算进结论的另一条路径。
    """
    succeeded = [r for r in records if r.get("ok")]
    n_failed = len(records) - len(succeeded)

    n_events_total = sum(r.get("n_add_events") or 0 for r in succeeded)
    all_zero = bool(succeeded) and all(r.get("n_retrieved", 0) == 0 for r in succeeded)
    any_zero = any(r.get("n_retrieved", 0) == 0 for r in succeeded)
    extraction_dead = bool(succeeded) and n_events_total == 0

    if not succeeded:
        verdict = "NO_DATA"
        note = "无成功实例，守卫未获得任何观测量。"
    elif extraction_dead:
        verdict = "APPARATUS_INADEQUATE_NOT_CONSTRUCTIVE_ZERO"
        note = (
            "所有实例的记忆抽取事件数均为 0 ⇒ 底座模型在该提示下未能产出可入库事实。"
            "此时的『检索为空』由**底座能力不足**造成，不是操纵不可达，"
            "因此**不得**报为构造性零（NULL BY CONSTRUCTION）。"
            "本装置在此处正确地拒绝给出可复现性数字。"
        )
    elif all_zero:
        verdict = "CONSTRUCTIVE_ZERO_BY_MEASUREMENT"
        note = "抽取有产出但检索恒为空 ⇒ 构造性零，**不得**写成『mem0 没有检索能力』。"
    else:
        verdict = "reachable"
        note = "存在非 0 检索 ⇒ 操纵可达；此处的零结果（若有）才是经验零。"

    return {
        "n_succeeded": len(succeeded),
        "n_failed": n_failed,
        "n_add_events_total": n_events_total,
        "extraction_dead": extraction_dead,
        "all_retrieved_zero": all_zero,
        "any_retrieved_zero": any_zero,
        "verdict": verdict,
        "note": note,
    }