"""端到端复现性比对的测试。

## 为什么这个测试盯着一句话

`verify_end_to_end_determinism` 返回 `all_identical=True` 时，很容易顺手把它
写成"解码 bit-exact"或"端到端可复现 ⇒ 解码可复现"。**两者都是错的**：

* 观测面被截断——只覆盖被检索返回的条目，且每条只取前 200 字符；
* 采样参数不可观测——mem0 不透传 seed/top_k。

端到端观测与解码观测是**两个不可互换**的结论：端到端不蕴含解码（观测面更窄，
未检索到的记忆与第 200 字符之后的内容测不到），解码也不保证端到端（向量库写入
顺序、并发、分片皆可引入差异）。唯一能说的是「在本次可观测面上未观测到差异」。

因此测试除了比对逻辑，还要锁住 `claim` 用词、`does_not_establish` 与
`observation_surface` 字段的存在，让"这个测量不成立什么"随结果一起被记录，
而不是靠人记得写。

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
    # 用词必须是"未观测到差异"，不得是"可复现"这类更强的断言
    assert r["claim"] == "no-difference-observed-on-observable-surface"
    assert "未观测到差异" in r["claim_zh"]


def test_claim_never_asserts_reproducibility_or_decoding(tmp_path: Path) -> None:
    """claim 不得声称"可复现"或"解码一致"，那会超出观测面。

    这是本测试最核心的一条：措辞比数字更容易被误读，而产物里的 claim 会被
    直接抄进论文。**只扫 claim 字段**——`does_not_establish` 里出现
    "bit-exact decoding"是正确的（那里本就是在声明*不*成立什么）。
    """
    a = _art(tmp_path / "a.json", [("q1", 3, ["x"])])
    b = _art(tmp_path / "b.json", [("q1", 3, ["x"])])
    r = verify_end_to_end_determinism(a, b)
    claim = (r["claim"] + " " + r["claim_zh"]).lower()
    for banned in ("reproducible", "bit-exact", "bit_exact", "可复现"):
        assert banned not in claim, f"claim 不得声称 {banned!r}：超出观测面"


def test_evidence_files_are_distinguished_from_descriptive_paths(
    tmp_path: Path,
) -> None:
    """产物里除证据路径外还会出现说明性路径字样（如 /tmp 的历史出处）。

    后者**不是**需要解析的依赖。若不显式区分，日后有人 `grep '/tmp'` 做卫生
    检查会误报，也分不清"哪条路径真的缺失"。故断言：
      · evidence_files_in_tree 只收录**实际存在**的文件；
      · path_literals_are_descriptive_only 恒为 True。
    """
    a = _art(tmp_path / "a.json", [("q1", 1, ["x"])])
    b = _art(tmp_path / "b.json", [("q1", 1, ["x"])])
    r = verify_end_to_end_determinism(a, b)

    assert r["path_literals_are_descriptive_only"] is True
    assert set(r["evidence_files_in_tree"]) == {a, b}
    for p in r["evidence_files_in_tree"]:
        assert Path(p).exists()

    # 缺失文件不得被误列为证据
    c = _art(tmp_path / "c.json", [("q1", 1, ["x"])])
    missing = str(tmp_path / "nope.json")
    r2 = verify_end_to_end_determinism(c, missing)
    assert missing not in r2["evidence_files_in_tree"]
    assert r2["evidence_files_in_tree"] == [c]


def test_observation_surface_is_declared(tmp_path: Path) -> None:
    """必须声明观测面的三处截断，否则读者会以为比对了全部记忆。"""
    a = _art(tmp_path / "a.json", [("q1", 1, ["x"])])
    b = _art(tmp_path / "b.json", [("q1", 1, ["x"])])
    surf = verify_end_to_end_determinism(a, b)["observation_surface"]
    assert surf["text_truncation_chars"] == 200
    assert surf["covers_retrieved_items_only"] is True
    assert surf["misses_unretrieved_memories"] is True
    assert surf["misses_beyond_truncation"] is True


def test_differing_output_is_not_silently_passed(tmp_path: Path) -> None:
    """检索文本不同 ⇒ 必须报 NOT-identical，不能因计数相同而误判通过。"""
    a = _art(tmp_path / "a.json", [("q1", 3, ["x", "y"])])
    b = _art(tmp_path / "b.json", [("q1", 3, ["x", "DIFFERENT"])])
    r = verify_end_to_end_determinism(a, b)
    assert r["all_identical"] is False
    assert r["claim"] == "NOT-identical"
    assert r["n_identical"] == 0


def test_result_always_records_what_it_does_not_establish(tmp_path: Path) -> None:
    """无论一致与否，都必须写明不能证明什么。"""
    a = _art(tmp_path / "a.json", [("q1", 1, ["x"])])
    b = _art(tmp_path / "b.json", [("q1", 1, ["y"])])
    for art_a, art_b in ((a, b), (a, a)):
        r = verify_end_to_end_determinism(art_a, art_b)
        assert "substrate-level bit-exact decoding" in r["does_not_establish"]
        assert r["relation_to_decoding_determinism"]


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