"""语料加载器的测试 —— 锁死 `.jsonl` 扩展名带来的那个静默损坏陷阱。

## 这个测试盯着的不是"能读出500 项"

而是**读法本身**：仓库里`eval/data/longmemeval_oracle.jsonl` 的扩展名写着
`.jsonl`，内容却是 pretty-print 的 JSON 数组。逐行解析它**不会可靠地报错**——
文件里有 1,500 行是独立的 JSON 字符串字面量（`answer_*` 证据 id、时间戳），
它们单独解析完全合法。一个"跳过坏行、留下好行"的读取器会拿到 1,500 个 `str`，
不报任何错。

本项目已有两名 worker 以这种方式产出过垃圾数据。所以这里既测"整体读法能拿到
500 个 dict"，也测"逐行读法拿不到500 项"—— 后者把陷阱本身钉成可执行的文档。

运行：
    /Users/mac/.workbuddy/binaries/python/envs/default/bin/python -m pytest \
        packages/memory-biomimetic/eval/c5_transfer/test_corpus_loader.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from c5_transfer.adapter import (  # noqa: E402
    CorpusFormatError,
    probe_leak_free_oracle,
    read_corpus,
)

EVAL_DIR = Path(__file__).resolve().parent.parent
ORACLE = EVAL_DIR / "data" / "longmemeval_oracle.jsonl"
CLEANED = EVAL_DIR / "data" / "longmemeval_s_cleaned.json"


def _line_based_parse(path: Path) -> tuple[int, int]:
    """按jsonl 的错误读法解析，返回 (成功数, 失败数)。

    刻意复现真实读取器的行为：逐行 `json.loads`，解析失败的行**跳过**
    而不是抛出。这正是静默损坏发生的地方。
    """
    ok = 0
    bad = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                json.loads(s)
            except json.JSONDecodeError:
                bad += 1
            else:
                ok += 1
    return ok, bad


# ── 正常路径：两个语料都必须是 500 个 dict ──────────────────────────────────


@pytest.mark.skipif(not ORACLE.exists(), reason="LongMemEval oracle 语料未下载")
def test_oracle_corpus_loads_as_500_dicts() -> None:
    """整体解析 `longmemeval_oracle.jsonl` ⇒ 恰好 500 个 dict。"""
    rows = read_corpus(ORACLE)
    assert len(rows) == 500
    assert all(isinstance(r, dict) for r in rows)
    # 不能只有数量对：元素必须真的长得像题目记录。
    assert all("question_id" in r for r in rows)


@pytest.mark.skipif(not CLEANED.exists(), reason="LongMemEval cleaned 语料未下载")
def test_cleaned_corpus_loads_as_500_dicts() -> None:
    """同一个loader 也必须正确处理 `.json` 版本的语料（1,101,877 行 / 500 项）。"""
    rows = read_corpus(CLEANED)
    assert len(rows) == 500
    assert all(isinstance(r, dict) for r in rows)


@pytest.mark.skipif(not ORACLE.exists(), reason="LongMemEval oracle 语料未下载")
def test_line_based_parse_does_not_yield_500_items() -> None:
    """把陷阱钉成可执行文档：逐行读法**拿不到** 500 项。

    这条测试的作用是"反向锁定"。如果哪天有人把`read_corpus` 改成逐行读，
    `test_oracle_corpus_loads_as_500_dicts` 会先失败；而这条测试保证
    失败原因被说清楚：是格式，不是数据坏了。
    """
    ok, bad = _line_based_parse(ORACLE)
    assert ok + bad > 67_000, "文件行数与实测不符（应约 67k 行）"
    # 关键断言：能解析出来的行数**不等于**题目数。
    assert ok != 500, "若逐行解析恰好得到 500 项，本测试的前提需重新评估"
    # 且这些"成功"行全是字符串字面量，不是题目记录 —— 静默损坏的实质。
    fragments = []
    with ORACLE.open(encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                fragments.append(json.loads(s))
            except json.JSONDecodeError:
                pass
    assert fragments, "应至少解析出一些片段"
    assert all(isinstance(x, str) for x in fragments), (
        "逐行解析出的应是裸字符串（证据 id / 时间戳），"
        "若变成了 dict 说明文件格式变了，本测试需重写"
    )


# ── 失败路径：形状不对时必须**响亮**失败，且信息可操作 ──────────────────────


def test_non_list_top_level_is_rejected(tmp_path: Path) -> None:
    """顶层是 dict（而非 list）⇒ 抛错，且错误信息点名文件与真实形状。"""
    p = tmp_path / "corpus.jsonl"
    p.write_text(json.dumps({"question_id": "q1"}), encoding="utf-8")
    with pytest.raises(CorpusFormatError) as ei:
        read_corpus(p)
    msg = str(ei.value)
    assert "corpus.jsonl" in msg
    assert "dict" in msg and "list" in msg
    # 必须给出正确读法，否则读者无从下手。
    assert "json.loads" in msg and "jsonl" in msg


def test_list_of_non_dict_elements_is_rejected(tmp_path: Path) -> None:
    """顶层是 list 但元素不是 dict（正是逐行解析会产出的形状）⇒ 抛错。

    这个case 就是 1,500 个 `str` 的现场复现：它**是**合法 JSON，
    只靠"能否解析"判断的读取器会放它过。
    """
    p = tmp_path / "fragments.jsonl"
    p.write_text(json.dumps(["answer_4be1b6b4_1", "2023/04/10 (Mon) 17:15"]), encoding="utf-8")
    with pytest.raises(CorpusFormatError) as ei:
        read_corpus(p)
    msg = str(ei.value)
    assert "fragments.jsonl" in msg
    assert "不全是 dict" in msg
    assert "str" in msg


def test_empty_list_is_rejected(tmp_path: Path) -> None:
    """空数组必须报错 —— 0 项不能被读成"语料为空但正常"。"""
    p = tmp_path / "empty.jsonl"
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(CorpusFormatError) as ei:
        read_corpus(p)
    assert "空数组" in str(ei.value)


def test_error_message_names_the_pretty_print_trap(tmp_path: Path) -> None:
    """错误信息必须**明确**说出"扩展名是 .jsonl 但内容是 pretty-print 数组"。

    这是给下一个踩坑的人看的：只说"格式异常"等于没���。
    """
    p = tmp_path / "tricky.jsonl"
    p.write_text('{\n    "a": 1\n}\n', encoding="utf-8")  # 缩进多行但顶层非数组
    with pytest.raises(CorpusFormatError) as ei:
        read_corpus(p)
    msg = str(ei.value)
    assert ".jsonl" in msg and "JSON Lines" in msg
    assert "禁止读法" in msg and "逐行解析" in msg
    assert "1,500" in msg
    assert "read_corpus" in msg


def test_error_message_does_not_falsely_assert_pretty_print(tmp_path: Path) -> None:
    """对**单行**的坏文件，提示不得硬套"pretty-print 数组"。

    措辞纪律：形状描述必须量出来，不能从扩展名推。否则真正损坏的语料
    会被误诊为"格式已知问题"，把人往错误方向带。
    """
    p = tmp_path / "oneline.jsonl"
    p.write_text('{"a": 1}', encoding="utf-8")  # 单行、非数组
    with pytest.raises(CorpusFormatError) as ei:
        read_corpus(p)
    msg = str(ei.value)
    assert "单个 JSON 值" in msg
    assert "pretty-print 的 JSON 数组" not in msg


# ── 加载器与既有探针的接线 ──────────────────────────────────────────────────


@pytest.mark.skipif(not ORACLE.exists(), reason="LongMemEval oracle 语料未下载")
def test_leak_probe_agrees_with_loader() -> None:
    """`probe_leak_free_oracle` 必须与 `read_corpus` 读出同一份语料。

    两者曾各自 `json.load` 同一个文件；现在共用入口，这条测试防止
    将来某一方被改回自己的读法而两边静默分歧。
    """
    v = probe_leak_free_oracle(corpus_path=str(ORACLE))
    assert v.computable is True
    # 语料里确实存在 has_answer 标注 ⇒ 泄漏向量非空（实测两类）。
    assert v.leak_vectors, "实测应至少测到 per_turn_has_answer_flag 一类"


@pytest.mark.skipif(not ORACLE.exists(), reason="LongMemEval oracle 语料未下载")
def test_leak_probe_rejects_a_fragment_file(tmp_path: Path) -> None:
    """把片段文件喂给探针，必须响亮失败而不是静默扫0 个 turn。"""
    p = tmp_path / "fragments.jsonl"
    p.write_text(json.dumps(["answer_x", "2023/01/01 (Sun) 00:00"]), encoding="utf-8")
    with pytest.raises(CorpusFormatError):
        probe_leak_free_oracle(corpus_path=str(p))
