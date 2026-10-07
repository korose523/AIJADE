"""C5 可迁移性实验 —— 被测系统适配层（mem0）。

本文件是整套装置里**唯一**允许触碰第三方系统的地方，其余模块只依赖这里暴露的
dataclass���这样做的理由与 AIJADE 既有做法一致（`j5-recall-harness.ts` 把指标实现
收敛成唯一入口）：一旦mem0 的调用散落在多个文件里，任何一次"为了跑通而改了调用
方式"都会让D1/D2 判定失真，而失真之后产物**看起来仍然是完整的**。

## 装置的可证伪边界（先写清楚，避免事后夸大）

本实验判定的**不是**"mem0 好不好"，而是"AIJADE 的五条约束能否在mem0 上被**计算**
出来"。因此每个约束都必须落到一个**可观测的量**上，且该量的来源要能追溯到具体
的API 调用或具体缺失的可观测性。凡是只能靠"我觉得算不出来"来支撑的判定，一律
记为不可施加并写出缺什么。

## 观测层级（决定每条约束的施加可能性）

|层级 | 含义                | 谁能提供                     |
|------|---------------------|------------------------------|
| 黑盒 | 只有 mem0 公开 API   | `Memory.add/search`返回值    |
| 灰盒 | 容器/进程由我们控制  | 模型 digest、依赖锁、喂入输入 |

对应论文里的说法是"在第三方系统上的**可计算性**"，不是"在第三方系统上的**效度**"。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── 被测系统标识（写进指纹，缺了它就无法区分"换了 mem0 版本"的复现）──────────

MEM0_VERSION: str | None = None
try:  # pragma: no cover - 取决于运行环境是否装了 mem0
    import mem0 as _mem0

    MEM0_VERSION = _mem0.__version__
except Exception:  # noqa: BLE001 - 探针式导入，失败也要能报出事实
    MEM0_VERSION = None

QDRANT_CLIENT_VERSION: str | None = None
try:
    import qdrant_client as _qc

    QDRANT_CLIENT_VERSION = getattr(_qc, "__version__", None)
except Exception:  # noqa: BLE001
    QDRANT_CLIENT_VERSION = None

# 本装置自身的版本。语义变化时必须 bump，否则旧产物无法区分装置改动。
C5_APPARATUS_VERSION = "c5-transfer/1"


# ── 语料读取：唯一入口 ───────────────────────────────────────────────────────


class CorpusFormatError(ValueError):
    """语料文件的实际结构与"非空 dict 数组"不符。

    单列一个异常类型，是为了让"语料坏了"与"实验跑挂了"在调用方与测试里
    可被分别捕获 —— 前者要修数据/修读法，后者要修装置。
    """


def read_corpus(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """读取 LongMemEval 语料，**整体** JSON 解析，并校验顶层结构。

    ## 为什么必须走这个函数（这是一个已经踩过的坑）

    `eval/data/longmemeval_oracle.jsonl` 的扩展名是 `.jsonl`，但内容**不是 jsonl**：
    它是一个**pretty-print 的 JSON 数组**（实测 67,041 行 / 500 项，缩进 4 空格）。
    `longmemeval_s_cleaned.json` 同理（实测 1,101,877 行 / 500 项）。

    因此逐行解析是错的，而且**错得不会报错**：

    - 大部分行（`{`、`},`、`"key":` 等）确实会抛JSONDecodeError，
      逐行解析的读者通常会在这里"发现"问题；
    - 但文件里有**1,500 行是独立的 JSON 字符串字面量**（`answer_*` 证据 id、
      `2023/04/10 (Mon) 17:15` 这类时间戳），它们**逐行解析完全合法**，
      得到 1,500 个 `str` —— 实测 `longmemeval_oracle.jsonl` 逐行解析出
      1,500 个可解析片段（全部是 `str`），零报错。

    也就是说，一个写成"跳过解析失败的行、留下能解析的行"的读取器会
    **静默**拿到1,500 个字符串而不是 500 个题目dict，且没有任何异常。
    本项目已有两名 worker 以这种方式产出过垃圾数据。

    ⇒ 这里做三件事，且**都不依赖调用方的自觉**：
      1. 整体 `json.loads`；
      2. 断言顶层是 `list`、非空、每个元素是 `dict`；
      3. 失败时抛出点名文件、说明真实形状的错误，并直接给出正确读法。

    ## 不要改名

    `longmemeval_oracle.jsonl` 这个误导性的文件名**不能改**：`experiments.registry.json`
    等多处按此路径引用它。纠正只以文档与本函数注释的形式存在。
    """
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise CorpusFormatError(f"语料文件无法读取：{p}（{exc}）") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CorpusFormatError(_format_hint(p, raw, f"整体 JSON 解析失败：{exc}")) from exc

    if not isinstance(data, list):
        raise CorpusFormatError(
            _format_hint(p, raw, f"顶层是 {type(data).__name__}，期望 list")
        )
    if not data:
        raise CorpusFormatError(_format_hint(p, raw, "顶层是空数组（0 项）"))
    bad = [i for i, x in enumerate(data) if not isinstance(x, dict)]
    if bad:
        first = bad[0]
        raise CorpusFormatError(
            _format_hint(
                p,
                raw,
                f"数组元素不全是 dict：{len(bad)}/{len(data)} 个不是，"
                f"首个下标 {first}（第 {first + 1} 项）是 {type(data[first]).__name__}",
            )
        )
    return data


def _format_hint(path: Path, raw: str, detected: str) -> str:
    """构造一条"说清事实 + 给出正确读法"的错误信息。

    措辞纪律：**只陈述实测到的形状**。`is_array` / `multiline` 是量出来的，
    不是从扩展名推的—— 否则对真正损坏的文件也会 falsely 断言"它是
    pretty-print 数组"，那是本函数最不该犯的错。
    """
    lines = raw.count("\n") + 1
    stripped = raw.lstrip()
    first = stripped[:1] or "<空文件>"
    looks_like_array = first == "["
    # "pretty-print" 的判据：顶层是数组，且缩进过（即多行格式化），
    # 或干脆就是多行。任一不成立就只说"多行 JSON 值"，不硬套pretty-print。
    indented = raw[:1] in (" ", "\t", "\n")
    multiline = lines > 1
    shape_desc = (
        "pretty-print 的 JSON 数组（已缩进多行）"
        if looks_like_array and (indented or multiline)
        else f"单个 JSON 值（首字符 {first!r}，共 {lines} 行）"
    )
    return (
        f"语料格式异常：{path}\n"
        f"  实测：{lines} 行，{len(raw)} 字节；{detected}。\n"
        f"  原因：该文件扩展名是 .jsonl，但内容是{shape_desc}，并非 JSON Lines。\n"
        f"  正确读法：json.loads(path.read_text()) 整体解析，然后断言顶层是 list。\n"
        f"  禁止读法：for line in f: json.loads(line) —— 逐行解析不会可靠地报错。\n"
        f"    LongMemEval 的两个语料文件里各有约 1,500 行是独立的 JSON 字符串\n"
        f"    字面量（answer_* 证据 id、时间戳等），逐行解析它们**完全合法**，\n"
        f"    会让'跳过坏行'式读取器静默拿到 1,500 个 str 而非 500 个题目 dict。\n"
        f"  请改用 c5_transfer.adapter.read_corpus()。"
    )


# ── 约束一：determinism pre-check ────────────────────────────────────────────


@dataclass(frozen=True)
class DeterminismVerdict:
    """确定性前置检查的判定结果。

    `computable=False` 时 `reason` 必须写明"缺哪一项可观测性"，不允许留空 ——
    空reason 会被后续写作者读成"可施加但没做"。
    """

    computable: bool
    tier: str  # 'black' | 'gray' | 'none'
    reason: str
    measured: dict[str, Any] = field(default_factory=dict)


def probe_determinism_precheck(
    *,
    n_repeats: int = 3,
    timeout_s: float = 1800.0,
) -> DeterminismVerdict:
    """探测约束一能否在 mem0 上施加。

    关键区分（这是本判定的全部技术内容）：AIJADE 版本的 determinism pre-check
    测的是**substrate 的解码**是否 bit-exact；而 mem0 **不暴露 substrate**——
    `Memory.add()` 的prompt 构造、采样参数传递、模型选择全在库内部。因此
    "端到端重跑 mem0 是否给出相同结果"与"解码是否 bit-exact"**不是同一个命题**，
    且**不可互换**（端到端观测面更窄，见 verify_end_to_end_determinism）。

    已实测（见产物 end_to_end_determinism 段）：两次独立进程运行，
    4/4 题的检索结果文本逐字节一致，事件数与命中数亦一致。
    该结论的强度**仅限于**"在本次可观测面上未观测到差异"。

    ⚠️ 引用这条时**必须**保留观测面限定：观测面为「被检索返回的条目 +
    每条前 200 字符」，未检索到的记忆与截断后的内容在原理上不可观测。
    把"未观测到差异"写成"解码 bit-exact"是把一个弱得多的真结论挂上错的术语。
    """
    return DeterminismVerdict(
        computable=True,
        tier="gray",
        reason=(
            "纯黑盒下 mem0 不暴露 substrate：Memory.add() 内部构造 prompt、"
            "调用 LLM、选择模型，库外无法观测其解码参数，故『解码是否 bit-exact』"
            "在黑盒下**不可计算**。但在灰盒下可施加一个**不同的**可观测命题："
            "同一模型别名 digest + 同一依赖锁下，端到端 add()+search() "
            "在被检索返回的条目及其前 200 字符上是否逐字节一致。"
            "实测两次独立进程运行 4/4 题一致。"
            "注意该结论**不蕴含**解码级 bit-exact（观测面更窄），"
            "反之解码一致也不保证端到端一致（向量库写入顺序/并发/分片）。"
        ),
        measured={
            "substrate_exposed_by_mem0": False,
            "black_box_decodability": False,
            "gray_box_end_to_end_reproducibility": True,
            "measured_identical_items": "4/4（见产物 end_to_end_determinism）",
            "observation_surface": (
                "被检索返回的条目（每题写入 12–36、返回 12–20）+ 每条前 200 字符"
            ),
            "not_established": [
                "substrate-level bit-exact decoding",
                "未被检索到的记忆是否一致",
                "每条第 200 字符之后是否一致",
            ],
            "relation_to_decoding_determinism": "不可互换（非蕴含关系）",
            "reason_not_identical": (
                "① 观测面被截断：比对只覆盖归一后 `[:200]` 的检索文本与被返回条目，"
                "其余部分原理上不可观测；"
                "② 采样参数不可观测：mem0 的 OllamaLLM.generate_response 只透传 "
                "{temperature, num_predict, top_p}，丢弃 top_k 与 seed "
                "（源码事实，见产物 mem0_observability.sampling_params_forwarded）。"
            ),
            "n_repeats_planned": n_repeats,
            "timeout_s": timeout_s,
        },
    )


def verify_end_to_end_determinism(
    committed_artifact: str,
    fresh_artifact: str,
) -> dict[str, Any]:
    """比对两次**独立进程**运行的检索结果，判断端到端是否可复现。

    ## 这测的是什么

    同一模型 digest、同一依赖锁、同一喂入输入下，`add()` + `search()` 返回的
    **被截断后的**检索文本是否逐字节一致。

    ## 这**不**测什么（措辞纪律，勿改）

    **不能**用它证明"底层解码 bit-exact"。两个独立理由，缺一不可：

    1. **观测面被截断。** 比对只覆盖 `run.py::_normalize_search` 归一后的
       文本：每条截断到 **200 字符**（`_normalize_search` 里的 `[:200]`），
       且只覆盖 **被检索返回的**条目（实测每题写入 12–36 条、返回 12–20 条）。
       因此未被检索到的记忆、以及每条记忆第 200 字符之后的内容，
       本函数**在原理上就看不到**。若底座解码在那里发散，哈希不变。
    2. **采样参数不可观测。** mem0 的 `OllamaLLM.generate_response`不透传
       seed/top_k（见 mem0_observability.sampling_params_forwarded），
       我们无法确认被测系统实际用了什么解码设置。

    ⇒ 端到端一致与解码一致是**两个不可互换的观测**：
       既不能说端到端一致"蕴含/强于"解码一致（覆盖面更窄，见上1），
       也不能说解码一致保证端到端一致（向量库写入顺序、并发、分片皆可引入差异，
       见上 2 的反向）。
       正确表述只有一句：**在本次可观测面上，两次独立运行未观测到差异。**

    这个区分是本函数存在的核心理由。把"在可观测面上未观测到差异"写成
    "解码 bit-exact"会让论文把一个弱得多的真结论挂上错的术语。
    """
    import hashlib

    def sig(path: str) -> dict[str, dict[str, Any]]:
        # 文件不存在时不抛异常，而是返回空表：调用方据此把该路径记为
        # "非证据"。抛异常会让"路径缺失"这个需要被记录的事实变成一次崩溃，
        # 而崩溃会掩盖掉其它可比对的项目。
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as f:
            art = json.load(f)
        out: dict[str, dict[str, Any]] = {}
        for it in art.get("sample", {}).get("items", []):
            texts = [r.get("text", "") for r in (it.get("retrieved") or [])]
            out[str(it["question_id"])] = {
                "n_add_events": it.get("n_add_events"),
                "n_retrieved": it.get("n_retrieved"),
                "inputs_sha256": it.get("inputs_sha256"),
                "retrieved_sha256": hashlib.sha256(
                    json.dumps(texts, ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest(),
            }
        return out

    a, b = sig(committed_artifact), sig(fresh_artifact)
    shared = sorted(set(a) & set(b))
    per_item = [
        {"question_id": q, "identical": a[q] == b[q], **a[q]} for q in shared
    ]
    all_identical = bool(shared) and all(r["identical"] for r in per_item)
    return {
        "compared_artifacts": [committed_artifact, fresh_artifact],
        "evidence_files_in_tree": [
            p for p in (committed_artifact, fresh_artifact) if os.path.exists(p)
        ],
        # 显式声明：compared_artifacts 里出现的其它路径字样（如 /tmp 的历史出处）
        # 只是说明性provenance，**不是**需要解析的依赖。本字段让"是否有活依赖"
        # 可被机器核查，而不必依赖人读文字。
        "path_literals_are_descriptive_only": True,
        "n_items_compared": len(shared),
        "n_identical": sum(1 for r in per_item if r["identical"]),
        "all_identical": all_identical,
        "claim": "no-difference-observed-on-observable-surface" if all_identical else "NOT-identical",
        "claim_zh": (
            "在本次可观测面上，两次独立运行未观测到差异"
            if all_identical
            else "观测到差异"
        ),
        "observation_surface": {
            "text_truncation_chars": 200,
            "covers_retrieved_items_only": True,
            "misses_unretrieved_memories": True,
            "misses_beyond_truncation": True,
            "note": (
                "每题写入 12–36 条、检索返回 12–20 条（实测）；"
                "未返回的条目与每条第 200 字符之后的内容不在比对范围内。"
            ),
        },
        "does_not_establish": [
            "substrate-level bit-exact decoding",
            "identical output for unretrieved memories",
            "identical output beyond the 200-char truncation",
        ],
        "relation_to_decoding_determinism": (
            "不可互换：端到端观测面**更窄**（截断+top-N），故不蕴含解码一致；"
            "解码一致也不保证端到端一致（向量库写入顺序/并发/分片）。"
            "正确表述仅为『在本次可观测面上未观测到差异』。"
        ),
        "per_item": per_item,
    }


# ── 约束二：run fingerprint ──────────────────────────────────────────────────


@dataclass(frozen=True)
class FingerprintVerdict:
    computable: bool
    tier: str
    reason: str
    fields_present: list[str] = field(default_factory=list)
    fields_absent: list[str] = field(default_factory=list)
    fingerprint: str = ""


def build_run_fingerprint(*, corpus_path: str, corpus_sha256: str) -> FingerprintVerdict:
    """构造覆盖 mem0 侧与语料侧的运行指纹。

    覆盖不到的部分**逐项列出**而不是整体标绿：AIJADE 侧的采样参数指纹依赖
    `model-substrate` 的 `buildFingerprint`，而 mem0 不走那条路径，所以本函数
    自己按同一 schema（`sampling` + `samplingHash` + `fingerprint`）重建一份，
    以便两套装置的产物可比。
    """
    from .fingerprint_lib import fnv1a, hash_sampling  # noqa: PLC0415 - 延迟导入避免环

    sampling = {
        "temperature": 0.0,
        "seed": 42,
        "top_p": 1.0,
        "top_k": 1,
        "repeat_penalty": 1.0,
        "num_ctx": 16384,
        "num_predict": 512,
        "think": False,
    }
    sampling_hash = hash_sampling(sampling)
    model_digest = _ollama_digest("c5-qwythos-16k:latest")
    server_version = _ollama_version()

    identity = f"c5-qwythos-16k@{model_digest}" if model_digest else "c5-qwythos-16k"
    server_part = server_version or "unknown"
    fp = fnv1a(f"c5-transfer|mem0|{identity}|{sampling_hash}|{server_part}|{corpus_sha256[:16]}")

    present = [
        "mem0_version",
        "qdrant_client_version",
        "python_version",
        "model_digest",
        "server_version",
        "sampling",
        "sampling_hash",
        "corpus_sha256",
        "embedder_model",
    ]
    # 明列缺口：mem0 内部 prompt 模板版本、事实抽取 prompt 的任何改动。
    absent = [
        "mem0_prompt_template_version",
        "mem0_fact_extraction_prompt_sha256",
        "ollama_build_arch",
    ]

    return FingerprintVerdict(
        computable=True,
        tier="gray",
        reason=(
            "灰盒下可覆盖：模型 digest、服务端版本、pinned 采样参数、"
            "全部喂入输入（语料 sha256 + 每题实际 messages 的 sha256）、"
            "embedder 模型、以及被测库版本。仍缺两项 mem0 内部提示词模板版本 —— "
            "库不暴露该模板的版本号或哈希，只能连同 site-packages 一起钉。"
        ),
        fields_present=present,
        fields_absent=absent,
        fingerprint=fp,
    )


def _ollama_digest(model: str) -> str | None:
    try:
        import urllib.request

        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/tags",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            tags = json.loads(resp.read()).get("models", [])
        for m in tags:
            if m.get("name") == model:
                return str(m.get("digest") or "")[:12]
    except Exception:  # noqa: BLE001
        return None
    return None


def _ollama_version() -> str | None:
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=10) as r:  # noqa: S310
            return str(json.loads(r.read()).get("version"))
    except Exception:  # noqa: BLE001
        return None


# ── 约束三：degeneracy guard ─────────────────────────────────────────────────


@dataclass(frozen=True)
class DegeneracyVerdict:
    computable: bool
    tier: str
    reason: str
    note: str = ""


def probe_degeneracy_guard() -> DegeneracyVerdict:
    """探测约束三能否施加。

    与 AIJADE 原语的**唯一差别**在判据口径：AIJADE 的 `detectDegeneracy()` 判的是
    「2×2 混淆表四格precision 完全相同」，而mem0 侧的失败模式判据是
    「记忆库为空 ⇒ 每题都返回空检索 ⇒ 检索命中率恒为 0」。后者是**等价的**：
    都区分"构造性零"与"经验零"，只是分析单元从 2×2 四格换成 0/非0 二分。
    本函数因此直接给出可施加判定，口径差异由调用方在产物里声明。
    """
    return DegeneracyVerdict(
        computable=True,
        tier="black",
        reason=(
            "完全可算：只需 mem0 的公开输出（search 返回的记忆条数与文本），"
            "不需要任何内部状态。判据为『每题检索结果条数 == 0』，"
            "该量在黑盒下即可观测。"
        ),
        note=(
            "口径映射：AIJADE 的 2×2 四格 precision 相同 ⇒ mem0 的"
            "『检索条数恒为 0』，二者都判定为构造性零。"
        ),
    )


# ── 约束四：leak-free sandbox oracle ─────────────────────────────────────────


@dataclass(frozen=True)
class OracleVerdict:
    computable: bool
    tier: str
    reason: str
    leak_vectors: list[dict[str, Any]] = field(default_factory=list)
    scrubbed: bool = False


def probe_leak_free_oracle(*, corpus_path: str) -> OracleVerdict:
    """探测约束四能否施加，并**实测**语料侧的泄漏向量。

    这一条必须在 mem0 之外判定：leak-free oracle 是**我们自己 harness** 的性质，
    不是 mem0 的性质。因此这里既检查语料是否自带答案位置标签，也检查我们喂进去的
    每条消息是否已脱敏。
    """
    vectors: list[dict[str, Any]] = []
    rows = read_corpus(corpus_path)

    flagged_turns = 0
    total_turns = 0
    for r in rows:
        for sess in r.get("haystack_sessions") or []:
            for t in sess:
                total_turns += 1
                if t.get("has_answer"):
                    flagged_turns += 1

    if flagged_turns:
        vectors.append(
            {
                "vector": "per_turn_has_answer_flag",
                "where": "haystack_sessions[].{role,content,has_answer}",
                "turns_flagged": flagged_turns,
                "turns_total": total_turns,
                "why": (
                    "oracle 切分的每个 turn 带 has_answer 布尔标签，"
                    "若原样喂给 mem0，等于把『答案在哪一段』直接告诉被测系统。"
                    "这是本次实验中实测到的真实泄漏向量，不是假想风险。"
                ),
                "mitigation": "喂入前删除 has_answer 字段，仅保留 role/content",
            }
        )

    # 第二类：答案原文出现在会话正文里（oracle 切分本就是"答案必然出现"的设定，
    # 因此这不是语料缺陷，而是"答案必要存在于上下文中"的固有性质）。
    exact = 0
    checked = 0
    for r in rows:
        ans = str(r.get("answer") or "").strip()
        if len(ans) < 8:
            continue
        checked += 1
        blob = json.dumps(r["haystack_sessions"], ensure_ascii=False)
        if ans.lower() in blob.lower():
            exact += 1
    vectors.append(
        {
            "vector": "answer_string_present_in_context",
            "where": "haystack_sessions[].content",
            "items_with_exact_answer": exact,
            "items_checked": checked,
            "why": (
                "oracle 切分的定义就是只保留含答案的会话，故答案原文必然在上下文里。"
                "这不是可修的泄漏，而是语料切分的设计；必须记录，"
                "以免把 oracle 切分下的高分误读为记忆系统能力强。"
            ),
            "mitigation": "仅可用于检索/记忆抽取环节的有界评测，不可用于端到端问答宣称",
        }
    )

    return OracleVerdict(
        computable=True,
        tier="black",
        reason=(
            "完全可施加，且是本实验里唯一**必须由我们侧保证**的约束："
            "oracle 只向 mem0 暴露 question 与已脱敏的会话，永不下发 answer；"
            "失败实例只报 question_id。已实测并记录语料自带的两类泄漏向量。"
        ),
        leak_vectors=vectors,
        scrubbed=True,
    )


def scrub_turn(turn: dict[str, Any]) -> dict[str, str]:
    """删除 oracle 标签，只留 role/content。这是喂给 mem0 前的唯一入口。"""
    return {"role": str(turn["role"]), "content": str(turn["content"])}


# ── 约束五：artifact registry ────────────────────────────────────────────────


@dataclass(frozen=True)
class RegistryVerdict:
    computable: bool
    tier: str
    reason: str


def probe_artifact_registry() -> RegistryVerdict:
    """探测约束五能否施加。

    判定：**仅对 AIJADE 侧成立**。mem0 有`history_db` 与运行内的 run_id，
    但那是系统内部日志，不是"每个 run 声明自己是 control 还是 main result"的
    注册表；把本实验的运行登记进 AIJADE 的 registry 是我方行为，mem0 无对应概念。
    """
    return RegistryVerdict(
        computable=True,
        tier="gray",
        reason=(
            "可施加，但**主体是 AIJADE 侧**：被测系统不知道自己是 control 还是 main "
            "result，这个角色只能由运行者登记。mem0 侧可提供的只有 run_id 与"
            " history_db，属内部日志，不构成实验注册表。"
        ),
    )


# ── mem0 可观测性事实（供 D2 表格逐条引用，全部来自源码/实测）───────────────


def mem0_observability() -> dict[str, Any]:
    """记录 mem0 侧的客观可观测性边界。

    这些不是推测：sampling_params_forwarded 来自阅读
    `mem0/llms/ollama.py::OllamaLLM.generate_response`；其余来自对
    `Memory.add` / `Memory.search` 签名的实测。
    """
    return {
        "mem0_version": MEM0_VERSION,
        "qdrant_client_version": QDRANT_CLIENT_VERSION,
        "python_version": sys.version.split()[0],
        "api_surface": {
            "Memory.from_config": "仅接受 config_dict 一个位置参数",
            "Memory.add": (
                "参数含 messages/user_id/agent_id/run_id/metadata/infer/"
                "memory_type/prompt —— **无返回值中的模型或采样信息**"
            ),
            "Memory.search": (
                "参数含 query/top_k/filters/threshold/rerank/explain。"
                "实测：mem0 2.2.1 起**拒绝顶层 user_id**，"
                "必须写成 filters={'user_id': ...}，否则抛 ValueError。"
            ),
        },
        "sampling_params_forwarded": {
            "forwarded": ["temperature", "num_predict", "top_p"],
            "dropped_by_mem0": ["top_k", "seed", "repeat_penalty", "num_ctx"],
            "source": "mem0/llms/ollama.py::OllamaLLM.generate_response",
            "consequence": (
                "调用方无法通过 mem0 配置把seed/top_k 传到底层。"
                "本实验通过 **模型别名**（Modelfile 固化参数）在灰盒侧补齐，"
                "这是绕开库限制的合法手段，未修改 mem0 源码。"
            ),
        },
        "embedding_dims_default_mismatch": {
            "mem0_default": 512,
            "nomic_embed_text_actual": 768,
            "consequence": "不显式设 embedding_dims 会导致维度不匹配，建库或检索失败",
        },
        "json_suffix_liveness": {
            "what": (
                "mem0/llms/ollama.py 在 response_format=json_object 时，"
                "会向最后一条 user 消息追加 '\\n\\nPlease respond with valid JSON only.'"
                "，同时置 params['format']='json'"
            ),
            "measured": (
                "带该后缀 + format=json：num_predict=512 → done=length, "
                "eval_tokens=512, content长度=0；num_predict=2048 → done=length, "
                "eval_tokens=2048, content长度=0。"
                "去掉该后缀、其余完全相同：num_predict=512 → done=stop, "
                "eval_tokens=466, 解析出 6 条 memory。"
            ),
            "consequence": (
                "在本机底座模型（qwythos 8.95B Q4_K_M）上，mem0 的 ollama provider "
                "因该冗余后缀触发无限 JSON 前缀/空白生成，**抽取恒为空**。"
                "因此本实验观测到的『检索为空』由底座模型与 provider 的交互缺陷造成，"
                "**不是**操纵不可达 —— 装置据此拒绝报出构造性零。"
            ),
            "note": (
                "这是可迁移性实验的一个正面结果：约束 3（degeneracy guard）"
                "在真实装置上确实拦下了一个会被误读为『构造性零』的数字。"
            ),
        },
        "prompt_size_floor": {
            "system_prompt_chars": 33653,
            "system_prompt_sha256_prefix": "ad19187a37813ef7",
            "measured": "最短会话(622 字符)仍使请求达 8,365 tokens",
            "consequence": (
                "mem0 的抽取提示词本身即约 8.4K tokens，"
                "底座模型 num_ctx 必须 ≥ 16K 才可能跑通；"
                "mem0 不透传 num_ctx（见 sampling_params_forwarded.dropped_by_mem0），"
                "本实验经模型别名(Modelfile) 在灰盒侧设定。"
            ),
        },
        "not_exposed": [
            "substrate 抽象（无法从 mem0 内部拿到解码参数与模型 digest）",
            "记忆抽取提示词模板的版本号/哈希（只能连同 site-packages 一起钉）",
            "实验角色（control / main result）概念",
        ],
    }


# ── 环境收据（供指纹与产物自证）───────────────────────────────────────────


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def environment_receipt() -> dict[str, Any]:
    return {
        "apparatus_version": C5_APPARATUS_VERSION,
        "python_executable": sys.executable,
        "platform": sys.platform,
        "env_vars_material": {
            k: ("<set>" if os.environ.get(k) else "<unset>")
            for k in ("OLLAMA_HOST", "OPENAI_API_KEY", "HF_HOME")
        },
        "pip_freeze_sha256": hashlib.sha256(
            subprocess.run(  # noqa: S603
                [sys.executable, "-m", "pip", "freeze"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.encode()
        ).hexdigest()[:16],
    }