"""C5 可迁移性实验 runner —— 实跑并产出可审计判定。

用法（venv 内）：
    /Users/mac/.workbuddy/binaries/python/envs/default/bin/python \
        packages/memory-biomimetic/eval/c5-transfer/run.py --limit N

## 这个 runner 做什么、不做什么

**做**：把 AIJADE 的五条约束逐条挂到 mem0 上，对每条给出
`完整施加 / 部分施加 / 不可施加` 的判定 + 缺什么可观测性的具体说明，
并把 abstention 子集**单独**统计。

**不做**：不比较 mem0 与 AIJADE 的分数高低。那个比较需要 A/B 与等算力，
本实验两者都不具备。任何"mem0 表现更好/更差"的表述都不许进入产物。

## 算力现实（决定了 n 必须小，且必须写进产物）

本机为纯 CPU（Intel i7-8569U，无 GPU 卸载）。实测prefill 8.1 tok/s、
生成 1.0 tok/s。mem0 每次 `add()` 至少两次 LLM 调用（事实抽取 + 记忆更新判定），
单会话实测分钟级。因此：

- 500 题全量在本机不可行（数量级估算见产物 `feasibility`段）；
- 任何小n 结果都**只能**支撑"判据能否被计算"，**不能**支撑"mem0 的能力水平"。

产物里 `sampleSize` 与 `inferenceScope` 两个字段就是为这条边界服务的：
写作者若引用本产物，只能引用前者。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from c5_transfer.adapter import (  # noqa: E402
    C5_APPARATUS_VERSION,
    build_run_fingerprint,
    environment_receipt,
    mem0_observability,
    probe_artifact_registry,
    probe_degeneracy_guard,
    probe_determinism_precheck,
    probe_leak_free_oracle,
    read_corpus,
    scrub_turn,
    sha256_file,
    verify_end_to_end_determinism,
)
from c5_transfer.degeneracy import classify_degeneracy  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = EVAL_DIR / "data" / "longmemeval_oracle.jsonl"
DEFAULT_OUT = EVAL_DIR / "results" / "c5-mem0-transfer.json"

OLLAMA_HOST = "http://127.0.0.1:11434"
LLM_MODEL = "c5-qwythos-16k:latest"
EMBED_MODEL = "nomic-embed-text"
EMBED_DIMS = 768

# mem0 的遥测向量库使用**进程级固定路径**（`$MEM0_DIR/migrations_qdrant`，
# 见 mem0/memory/main.py:534）。同一进程内构造第二个 Memory 实例会触发 Qdrant
# 本地存储的文件锁，报"already accessed by another instance of Qdrant client"，
# 使第 2 题起全部实例化失败。
#
# 两个应对措施，二者都**不修改 mem0 源码**：
#   1. `MEM0_TELEMETRY=False` 关闭遥测，从根上不创建该向量库；
#   2. 每题一个子进程（`--one` 模式），使跨题状态彻底隔离。
# 措施 2 顺带保证"一题一库"，避免上一题的抽取结果污染下一题 —— 那是复现性
# 装置必须防的跨实例污染，与被测系统的能力无关。
os.environ.setdefault("MEM0_TELEMETRY", "False")
_RUN_TMP = Path("/tmp") / "c5-transfer-store"
_RUN_TMP.mkdir(parents=True, exist_ok=True)

# 当前臂：`infer` 走 LLM 事实抽取；`store` 走 add(infer=False) 原样入库。
# 由 `--arm` 设定，`_run_single` 通过模块级变量读取（子进程内单臂执行）。
ARM = "infer"


def build_memory(store_path: Path, *, arm: str = "infer"):
    """构造一个 mem0 实例。

    每项配置都显式写出：默认值里`embedding_dims=512` 与 nomic-embed-text 的
    768 不符（实测），不显式指定会直接失败 —— 这一条要进产物，否则下次
    换机器复现时会踩同一个坑。

    `arm` 决定事实抽取方式，两个取值都是 mem0 的**公开配置/参数**，
    不修改其源码：
      · `infer`（默认）：`add(infer=True)`，走 LLM 事实抽取管线；
      · `store`        ：`add(infer=False)`，原样入库，不过 LLM。
    之所以需要第二条臂：本机底座模型在mem0 的抽取提示词下恒产出空结果
    （见 adapter.mem0_observability().json_suffix_liveness），
    只有 `infer=False` 能产生非空记忆，从而让约束 3 的"操纵可达"分支
    也能被实测到，而不是只测到"装置失效"分支。
    """
    from mem0 import Memory

    # 每实例独立 MEM0_DIR，避免遥测/迁移目录跨题争用。
    os.environ["MEM0_DIR"] = str(store_path / "mem0dir")
    (store_path / "mem0dir").mkdir(parents=True, exist_ok=True)

    return Memory.from_config(
        {
            "llm": {
                "provider": "ollama",
                "config": {
                    "model": LLM_MODEL,
                    "temperature": 0.0,
                    "top_p": 1.0,
                    "max_tokens": 512,
                    "ollama_base_url": OLLAMA_HOST,
                },
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": EMBED_MODEL,
                    "embedding_dims": EMBED_DIMS,
                    "ollama_base_url": OLLAMA_HOST,
                },
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": str(store_path / "qdrant"),
                    "embedding_model_dims": EMBED_DIMS,
                    "collection_name": "c5_transfer",
                },
            },
        }
    )

def _run_one_in_subprocess(item: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    """在独立子进程中跑一题，返回该题的记录。

    为什么不直接循环调用：mem0 的遥测向量库使用进程级固定路径，第二次
    `Memory.from_config` 必然撞 Qdrant 本地存储锁（实测第 2–4 题全部
    `RuntimeError: Storage folder ... already accessed`）。用子进程隔离
    既绕开该锁，也顺带消除跨题状态污染。

    失败时只回传 question_id 与错误类型/首段，**不回传答案**（约束 4）。
    """
    import subprocess

    qid = str(item["question_id"])
    out_path = _RUN_TMP / f"{qid}.json"
    if out_path.exists():
        out_path.unlink()

    env = {**os.environ, "MEM0_TELEMETRY": "False", "PYTHONUNBUFFERED": "1"}
    try:
        proc = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--one",
                qid,
                "--corpus",
                str(DEFAULT_CORPUS),
                "--arm",
                ARM,
                "--out",
                str(out_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=env,
            cwd=str(Path(__file__).resolve().parents[4]),
        )
    except subprocess.TimeoutExpired:
        return {
            "question_id": qid,
            "ok": False,
            "error_type": "TimeoutExpired",
            "error_head": f"超过单题预算 {timeout_s}s",
        }

    if out_path.exists():
        rec = json.loads(out_path.read_text(encoding="utf-8"))
    else:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        rec = {
            "question_id": qid,
            "ok": False,
            "error_type": "NoResultFile",
            "error_head": tail[-1][:200] if tail else f"exit={proc.returncode}",
        }
    rec.setdefault("question_id", qid)
    rec["is_abstention"] = qid.endswith("_abs")
    return rec


def _run_single(item: dict[str, Any], out_path: Path) -> int:
    """`--one` 模式：跑单题并落盘，供父进程收集。"""
    import shutil

    qid = str(item["question_id"])
    store = _RUN_TMP / qid
    shutil.rmtree(store, ignore_errors=True)
    store.mkdir(parents=True, exist_ok=True)

    msgs = [
        scrub_turn(t) for sess in (item.get("haystack_sessions") or []) for t in sess
    ]
    inputs_sha = hashlib.sha256(
        json.dumps(msgs, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()

    rec: dict[str, Any] = {
        "question_id": qid,
        "question_type": item["question_type"],
        "arm": ARM,
        "n_messages_fed": len(msgs),
        "inputs_sha256": inputs_sha,
    }

    try:
        t0 = time.time()
        mem = build_memory(store, arm=ARM)
        add_res = mem.add(msgs, user_id=f"c5_{qid}", infer=(ARM == "infer"))
        t_add = time.time() - t0

        # mem0 2.2.1 起 search() 拒绝顶层 user_id，必须走 filters。
        search_res = mem.search(item["question"], filters={"user_id": f"c5_{qid}"}, limit=5)
        retrieved = _normalize_search(search_res)

        events = add_res.get("results", []) if isinstance(add_res, dict) else []
        rec.update(
            {
                "ok": True,
                "add_seconds": round(t_add, 1),
                "n_add_events": len(events) if isinstance(events, list) else None,
                "n_retrieved": len(retrieved),
                "retrieved": retrieved,
                "constructive_zero": len(retrieved) == 0,
            }
        )
    except Exception as exc:  # noqa: BLE001 - 失败只报 id 与原因，绝不带答案
        rec.update({"ok": False, "error_type": type(exc).__name__, "error_head": str(exc)[:300]})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def main() -> int:  # noqa: PLR0915 - 线性流程，拆开反而更难审计
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--limit", type=int, default=3, help="题数上限（小 n，见文件头算力说明）")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="只跑装置探针与语料体检，不调用 LLM（不产生任何能力数字）",
    )
    ap.add_argument(
        "--one",
        default="",
        help="内部使用：只跑指定 question_id 并落盘，由父进程收集",
    )
    ap.add_argument(
        "--per-item-timeout",
        type=float,
        default=3600.0,
        help="单题墙钟预算（秒），超时按失败记账而非无限等待",
    )
    ap.add_argument(
        "--arm",
        choices=("infer", "store"),
        default="infer",
        help=(
            "事实抽取臂：infer=add(infer=True) 走 LLM 抽取（默认）；"
            "store=add(infer=False) 原样入库，不经 LLM"
        ),
    )
    ap.add_argument(
        "--compare-with",
        default="",
        help=(
            "内部/审计用：与指定产物比对检索结果，判断端到端是否可复现。"
            "约束一在灰盒下可实测的正是这个较弱命题。"
        ),
    )
    ap.add_argument(
        "--determinism-evidence",
        default="",
        help=(
            "把一次独立重跑与本产物比对的结果写入 end_to_end_determinism 段。"
            "用于把『灰盒下端到端可复现』从终端观察变成产物内的可审计记录。"
        ),
    )
    args = ap.parse_args()

    global ARM  # noqa: PLW0603 - 子进程单臂执行，模块级状态是最小传递手段
    ARM = args.arm

    # ── `--compare-with`：只做端到端复现性比对，不重跑实验、不写新产物 ──
    if args.compare_with:
        cmp = verify_end_to_end_determinism(args.compare_with, str(args.out))
        print(json.dumps(cmp, ensure_ascii=False, indent=2))
        return 0 if cmp["all_identical"] else 1

    corpus_path = Path(args.corpus)
    if not corpus_path.exists():
        print(f"语料不存在：{corpus_path}", file=sys.stderr)
        print("获取：curl -L -o <path> https://huggingface.co/datasets/xiaowu0162/longmemeval/resolve/main/longmemeval_oracle", file=sys.stderr)
        return 2

    corpus_sha = sha256_file(str(corpus_path))
    rows: list[dict[str, Any]] = read_corpus(corpus_path)

    # ── `--one`：单题执行并落盘后立即退出 ────────────────────────────────
    if args.one:
        target = next((r for r in rows if r["question_id"] == args.one), None)
        if target is None:
            print(f"未找到 question_id={args.one}", file=sys.stderr)
            return 2
        return _run_single(target, Path(args.out))

    print(f"=== C5 可迁移性实验 ===")
    print(f"语料: {corpus_path}")
    print(f"sha256: {corpus_sha}")
    print(f"题数: {len(rows)}")

    # ── 装置探针（与被测系统无关的部分先跑，任何一条失败都不产出产物）──────
    probes = {
        "c1_determinism_precheck": probe_determinism_precheck(),
        "c2_run_fingerprint": build_run_fingerprint(
            corpus_path=str(corpus_path), corpus_sha256=corpus_sha
        ),
        "c3_degeneracy_guard": probe_degeneracy_guard(),
        "c4_leak_free_oracle": probe_leak_free_oracle(corpus_path=str(corpus_path)),
        "c5_artifact_registry": probe_artifact_registry(),
    }
    fp_verdict = probes["c2_run_fingerprint"]

    oracle_verdict = probes["c4_leak_free_oracle"]
    print(f"\n[约束4] 实测泄漏向量 {len(oracle_verdict.leak_vectors)} 类：")
    for v in oracle_verdict.leak_vectors:
        print(f"  · {v['vector']}: {v.get('why', '')[:70]}...")

    # ── 选样：分层 + abstention 单独标记 ─────────────────────────────────
    abstention_items = [r for r in rows if r["question_id"].endswith("_abs")]
    regular_items = [r for r in rows if not r["question_id"].endswith("_abs")]

    # 确定性抽样：按 question_id 字典序取前n 个，不引入随机数依赖。
    regular_items.sort(key=lambda r: r["question_id"])
    picked = regular_items[: max(0, args.limit)]
    picked_abs: list[dict[str, Any]] = []
    if args.limit > 0:
        # abstention 至少取 1 题（若语料中存在），否则该子集无任何数字。
        picked_abs = abstention_items[:1]

    selected = picked + picked_abs
    print(f"\n选样:常规 {len(picked)} 题 + abstention {len(picked_abs)} 题")

    per_item: list[dict[str, Any]] = []
    timings: list[float] = []

    if args.dry_run:
        print("\n--dry-run：跳过 LLM 调用，不产生任何能力数字")
    else:
        for idx, item in enumerate(selected, start=1):
            qid = item["question_id"]
            is_abs = qid.endswith("_abs")
            print(
                f"\n[{idx}/{len(selected)}] {qid} "
                f"({'abstention' if is_abs else item['question_type']}) —— 子进程隔离执行"
            )
            rec = _run_one_in_subprocess(item, timeout_s=args.per_item_timeout)
            if rec.get("ok") and rec.get("add_seconds") is not None:
                timings.append(float(rec["add_seconds"]))
            per_item.append(rec)
            if rec.get("ok"):
                print(
                    f"  add {rec['add_seconds']}s, 抽取事件 {rec['n_add_events']}, "
                    f"检索命中 {rec['n_retrieved']}"
                )
            else:
                print(f"  失败：{rec.get('error_type')}: {str(rec.get('error_head'))[:120]}")



    # ── 约束 3 的实测判定（构造性零 vs 经验零）───────────────────────────
    # 判定逻辑在 degeneracy.classify_degeneracy，并有单测锁定；
    # 这里的注释只说明为什么必须区分三种"零"。
    degeneracy_measured = classify_degeneracy(per_item)

    # ── abstention 子集单独报告 ─────────────────────────────────────────
    abs_records = [r for r in per_item if r.get("is_abstention")]
    abstention_block = {
        "present_in_corpus": len(abstention_items) > 0,
        "corpus_count": len(abstention_items),
        "corpus_share_of_500": round(len(abstention_items) / len(rows), 4),
        "evaluated": len(abs_records),
        "definition": (
            "question_id 以 _abs 结尾；其 gold answer 形如"
            "『The information provided is not enough...』，"
            "即正确答案就是弃权。这是现成的外部『宁缺勿伪造』判据。"
        ),
        "records": [
            {
                "question_id": r["question_id"],
                "ok": r.get("ok"),
                "n_retrieved": r.get("n_retrieved"),
                "constructive_zero": r.get("constructive_zero"),
            }
            for r in abs_records
        ],
        "caveat": (
            "本机算力下 abstention 子集样本量为 "
            f"{len(abs_records)}，**不足以**给出该子集的准确率；"
            "只能报告装置在该子集上可运行/可判定。"
        ),
    }

    # ── 产物 ────────────────────────────────────────────────────────────
    # 端到端复现性：若提供了独立重跑的产物，比对结果写进产物本身，
    # 使「灰盒下可复现」成为可审计记录而非终端里的一句话。
    determinism_result: dict[str, Any]
    if args.determinism_evidence and Path(args.determinism_evidence).exists():
        determinism_result = verify_end_to_end_determinism(
            str(args.out), args.determinism_evidence
        )
    else:
        determinism_result = {
            "measured": False,
            "reason": (
                "本次运行未提供 --determinism-evidence（独立重跑产物），"
                "故未测。可用两次独立运行比对检索文本哈希来测。"
            ),
            "does_not_establish": "substrate-level bit-exact decoding",
        }

    artifact = {
        "experiment": {
            "id": "c5-mem0-transfer",
            "apparatus_version": C5_APPARATUS_VERSION,
            "question": (
                "D1 装置可迁移性：AIJADE 的五条可复现性约束能否在第三方记忆系统"
                "（mem0）上被计算出来。D2 判据可迁移性：逐条施加性判定。"
            ),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "seed": args.seed,
            "dry_run": args.dry_run,
        },
        "verdict_scope": {
            "inferenceScope": "judge-computability-only",
            "excluded": [
                "mem0 与 AIJADE 的分数高低比较",
                "任何『五条约束在别的项目里带来提升』的结论（需A/B，本实验不具备）",
                "mem0 的能力水平评估（小 n + 本机算力，见 feasibility）",
            ],
            "why": (
                "判据是『我们的判据能否被计算出来』，不是『对方分数多少』。"
                "把可计算性说成效度是本实验最容易被误用的方向。"
            ),
        },
        "corpus": {
            "name": "LongMemEval (oracle split)",
            "path": str(corpus_path),
            "sha256": corpus_sha,
            "items_total": len(rows),
            "format_note": "上游文件名为 longmemeval_oracle，内容为 JSON 数组（非 jsonl）",
            "license": "MIT (Hugging Face: xiaowu0162/longmemeval)",
            "n_sessions_total": sum(len(r.get("haystack_sessions") or []) for r in rows),
            "chars_total": sum(
                len(json.dumps(r.get("haystack_sessions") or [], ensure_ascii=False)) for r in rows
            ),
            "abstention_items": len(abstention_items),
        },
        "target_system": mem0_observability(),
        "fingerprint": {
            "fingerprint": fp_verdict.fingerprint,
            "fields_present": fp_verdict.fields_present,
            "fields_absent": fp_verdict.fields_absent,
            "tier": fp_verdict.tier,
            "reason": fp_verdict.reason,
        },
        "environment": environment_receipt(),
        "D1_criterion_probe": {
            "c1_determinism_precheck": _verdict_row(probes["c1_determinism_precheck"]),
            "c2_run_fingerprint": _verdict_row(fp_verdict),
            "c3_degeneracy_guard": _verdict_row(probes["c3_degeneracy_guard"]),
            "c4_leak_free_oracle": _verdict_row(oracle_verdict),
            "c5_artifact_registry": _verdict_row(probes["c5_artifact_registry"]),
        },
        "D2_applicability": {
            "c1_determinism_precheck": _grade(probes["c1_determinism_precheck"]),
            "c2_run_fingerprint": _grade(fp_verdict),
            "c3_degeneracy_guard": _grade(probes["c3_degeneracy_guard"]),
            "c4_leak_free_oracle": _grade(oracle_verdict),
            "c5_artifact_registry": _grade(probes["c5_artifact_registry"]),
        },
        "artifact_registry_entry": {
            "schema": "c5.artifact_registry_entry@1",
            "experiment_id": "c5-mem0-transfer",
            "apparatus_version": C5_APPARATUS_VERSION,
            "arm": ARM,
            "role": "control" if ARM == "infer" else "main_result",
            "role_semantics": (
                "control 臂：走 mem0 的 LLM 事实抽取（add(infer=True)）。"
                "本机底座模型在该臂下抽取恒为空，因此它的作用是展示同一套装置"
                "如何把『底座失效』与『构造性零』区分开—— 即拦下一个会被误读为"
                "科学结论的数字。它不是 mem0 能力的结果。"
                if ARM == "infer"
                else "main_result 臂：给出 D1/D2 的施加性判定。"
                "该臂用 add(infer=False) 绕过 LLM 抽取，"
                "故其检索数字只证明判据可计算，不表征 mem0 的抽取能力。"
            ),
            "corpus_sha256": corpus_sha,
            "run_fingerprint": fp_verdict.fingerprint,
            "sample_size": len(per_item),
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "registry_note": (
                "本条目写在**本产物内**而非 experiments.registry.json："
                "该注册表当前有其他 worker 的未提交改动，本次实验不得触碰它"
                "（git 纪律）。如需并入，须由改动者在合并时统一登记。"
            ),
        },
        "leak_vectors": oracle_verdict.leak_vectors,
        "degeneracy_measured": degeneracy_measured,
        "end_to_end_determinism": determinism_result,
        "abstention_subset": abstention_block,
        "sample": {
            "sampleSize": len(per_item),
            "arm": ARM,
            "arm_semantics": {
                "infer": "add(infer=True)：mem0 走 LLM 事实抽取管线",
                "store": "add(infer=False)：原样入库，不经 LLM",
            }[ARM],
            "arm_caveat": (
                "本机底座模型在 infer 臂下抽取恒为空（见 "
                "target_system.json_suffix_liveness），"
                "故只有 store 臂能产出非空记忆。两臂都是 mem0 公开参数，"
                "未修改其源码；store 臂**不**代表 mem0 的事实抽取能力。"
                if ARM == "infer"
                else "store 臂绕过了 mem0 的 LLM 事实抽取环节，"
                "因此其检索数字只用于验证约束 3 的可计算性，"
                "**不可**作为 mem0 事实抽取能力的证据。"
            ),
            "regular": len(picked),
            "abstention": len(picked_abs),
            "selection": "按 question_id 字典序取前 n（确定性，无随机依赖）",
            "items": per_item,
        },
        "timings": {
            "add_seconds": [round(t, 1) for t in timings],
            "add_seconds_mean": round(sum(timings) / len(timings), 1) if timings else None,
        },
        "feasibility": {
            "hardware": "Intel i7-8569U，纯 CPU，无 GPU 卸载（size_vram=0.00GB）",
            "measured_prefill_tok_per_s": 8.1,
            "measured_gen_tok_per_s": 1.0,
            "corpus_sessions_total": sum(len(r.get("haystack_sessions") or []) for r in rows),
            "oracle_split_vs_cleaned": (
                "oracle 切分 948 会话 ≈ 1.4e7 字符；cleaned 切分 23,867 会话 "
                "≈ 2.4e8 字符，两者体量差约 15 倍。任何算力估算必须指明是哪个切分。"
            ),
            "full_500_status": "NOT_RUN",
            "full_500_reason": (
                "本机纯 CPU、生成 1 tok/s；mem0 每次 add 至少两次 LLM 调用。"
                "全量 500 题所需时间远超本任务预算，故本产物只覆盖小 n，"
                "并在 verdict_scope 中限定结论范围。"
            ),
        },
        "honesty": {
            "no_fabricated_numbers": True,
            "failed_items_reported_by_id_only": True,
            "expected_output_never_fed": True,
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"{json.dumps(artifact, ensure_ascii=False, indent=2)}\n", encoding="utf-8")

    print(f"\n产物已写入：{out}")
    print("\n=== D2 逐条施加性 ===")
    for k, v in artifact["D2_applicability"].items():
        print(f"  {k}: {v['grade']} ({v['tier']})")
    print(f"\n实测退化守卫：{degeneracy_measured['verdict']}")
    return 0


def _normalize_search(res: Any) -> list[dict[str, Any]]:
    """把 mem0 search 返回值归一成 [{text, score}]，供退化守卫判定。

    归一而非直接比较 dict 的原因：mem0 不同版本/不同 provider 的返回形状会变，
    而退化守卫要盯的是**条数**，不是字段名。让形状变化影响守卫判定会把
    「库升级了」误报成「构造性零」。
    """
    items = res.get("results", []) if isinstance(res, dict) else res
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict):
            out.append(
                {
                    "text": str(it.get("memory") or it.get("text") or "")[:200],
                    "score": it.get("score"),
                }
            )
    return out


def _verdict_row(v: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "computable": getattr(v, "computable", None),
        "tier": getattr(v, "tier", None),
        "reason": getattr(v, "reason", ""),
    }
    for extra in ("measured", "leak_vectors", "note", "fields_present", "fields_absent", "fingerprint"):
        val = getattr(v, extra, None)
        if val:
            row[extra] = val
    return row


def _grade(v: Any) -> dict[str, Any]:
    """把探针结果翻译成论文可用的三档判定。

    判定必须由**可观测性**推出，而不是由"我们做到了没有"推出：
    做到了但原理上不可复现（例如在灰盒里靠记录日志凑出指纹）仍是可施加，
    因为指纹的作用就是让第三方复算；反过来，原理上可算但本次没做，
    应记为可施加-未执行，而不是不可施加。
    """
    row = _verdict_row(v)
    tier = row.get("tier")
    computable = row.get("computable")
    if not computable:
        grade = "NOT_APPLICABLE"
    elif tier == "black":
        grade = "FULLY_APPLICABLE"
    elif tier == "gray":
        grade = "PARTIALLY_APPLICABLE"
    else:
        grade = "PARTIALLY_APPLICABLE"
    row["grade"] = grade
    return row


if __name__ == "__main__":
    raise SystemExit(main())