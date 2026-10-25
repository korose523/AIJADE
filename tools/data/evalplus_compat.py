#!/usr/bin/env python3
"""Static compatibility check of EvalPlus tasks against the RQ-C JavaScript executor (P2-A stage 0).

The RQ-C oracle (src/Aijade.Research/SkillBench/Sandbox.cs) passes each test's arguments as JavaScript literals and
compares the result with the expected value by exact structural equality: no float tolerance, no BigInt, no Set or
tuple types, object keys are strings. This script classifies every HumanEval+ and MBPP+ task by whether its inputs and
outputs fit that oracle as it stands. It is a screen, not a port: the expected outputs are not computed (that needs
running the canonical Python solutions), so a task classed "direct" can still fail when it is ported.

Nothing from the datasets is executed. Prompts, solutions and assertions are only parsed (ast.parse, ast.literal_eval);
inputs are read as JSON. Run with python3 -I.
  usage: python3 -I tools/data/evalplus_compat.py [--data DIR] [--out FILE]
"""
import argparse
import ast
import datetime
import gzip
import hashlib
import json
import os
import subprocess
import sys
import warnings

DATASETS = [  # (name, file, pinned SHA-256); fetched by tools/data/fetch-corpora.sh evalplus
    ("HumanEval+", "HumanEvalPlus-v0.1.10.jsonl.gz", "272720b90ac375502c8ed23cd791c2a93dfb22a911641a494da74a426c09f101"),
    ("MBPP+", "MbppPlus-v0.2.0.jsonl.gz", "af43697e8791c4c149bdfd6b489d8b5412507551ac20e28a439f650b8225db63"),
]
# Evaluator-level special cases of EvalPlus (evalplus/eval/__init__.py and _special_oracle.py at commit 26d6d00, 2025-10-02):
# float outputs are compared with atol 1e-6 even when the task's atol is 0, and these entry points are not judged by
# equality with the canonical output.
SPECIAL_ORACLES = {
    ("HumanEval+", "find_zero"): "special-oracle",            # |poly(xs, out)| <= atol: any root passes
    ("MBPP+", "are_equivalent"): "degenerate-oracle",         # exact_match or True: every output passes
    ("MBPP+", "sum_div"): "special-oracle",                   # out == 0 also passes
    ("MBPP+", "surface_Area"): "special-oracle",              # compared with a second formula
    ("MBPP+", "digit_distance_nums"): "special-oracle",       # compared with a second implementation
    **{("MBPP+", e): "set-equality-oracle" for e in ("similar_elements", "find_char_long", "common_in_nested_lists",
        "extract_singly", "larg_nnum", "intersection_array", "find_dissimilar", "Diff")},
    **{("MBPP+", e): "special-oracle" for e in ("check_str", "text_match_three", "text_starta_endb")},  # None vs not None
}
SAFE_INT = 2**53 - 1
LARGE_INPUT_CHARS = 100_000  # all inputs of a task serialized; Jint runs far slower than CPython

# Reasons, by the class they put a task in (the most severe one wins).
INCOMPATIBLE = {
    "output-set": "returns a set or frozenset; Jint deep equality treats any two Set objects as equal",
    "output-dict-nonstr-keys": "returns a dict with non-string keys; JavaScript object keys are strings",
    "output-complex": "returns a complex number",
    "bigint": "an input or expected literal exceeds 2^53 - 1; numbers would need BigInt",
    "degenerate-oracle": "EvalPlus accepts every output for this task, so its tests cannot separate usable from unusable code",
}
ADAPTER = {
    "float-tolerance": "compared with a tolerance (atol > 0, abs(...) < eps / math.isclose, or EvalPlus's enforced 1e-6 for float outputs); the oracle compares exactly",
    "special-oracle": "EvalPlus judges this task with a task-specific check instead of equality with the canonical output",
    "set-equality-oracle": "EvalPlus compares this task's output as a set, i.e. order and duplicates are ignored",
    "order-from-set": "the canonical solution builds its result by iterating a set, so the expected order is CPython's hash order",
    "assert-order-insensitive": "the task's own assertion compares set(...) or sorted(...), i.e. order is not specified",
}
CAUTION = {
    "float-exact": "returns floats inside mixed-type values, which EvalPlus compares exactly; Python and .NET math may differ in the last bit",
    "input-any": "a parameter is annotated Any; Python's type tests (bool is an int) do not carry over to JavaScript",
    "returns-none": "may return None; the JavaScript candidate must return null, not undefined",
    "astral-strings": "inputs contain characters outside the BMP; string length and indexing differ between Python and JavaScript",
    "large-inputs": f"inputs exceed {LARGE_INPUT_CHARS:,} JSON characters in total",
    "no-output-type": "no return annotation or literal expected value to type the output",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def walk_json(v, flags):
    if isinstance(v, bool):
        return
    if isinstance(v, int):
        if abs(v) > SAFE_INT:
            flags.add("bigint")
    elif isinstance(v, str):
        if any(ord(c) > 0xFFFF for c in v):
            flags.add("astral-strings")
    elif isinstance(v, list):
        for x in v:
            walk_json(x, flags)
    elif isinstance(v, dict):
        for x in v.values():
            walk_json(x, flags)


def literal_type(node):
    """Type of a literal expected value, or None when the node is not a literal."""
    try:
        v = ast.literal_eval(node)
    except Exception:
        return None
    return value_type(v)


def value_type(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "bigint" if abs(v) > SAFE_INT else "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, complex):
        return "complex"
    if isinstance(v, str):
        return "str"
    if v is None:
        return "none"
    if isinstance(v, (set, frozenset)):
        return "set"
    if isinstance(v, dict):
        return "dict-str" if all(isinstance(k, str) for k in v) else "dict-nonstr"
    if isinstance(v, tuple):
        inner = {value_type(x) for x in v}
        return "tuple[" + ",".join(sorted(inner)) + "]"
    if isinstance(v, list):
        inner = {value_type(x) for x in v}
        return "list[" + ",".join(sorted(inner)) + "]"
    return type(v).__name__


def annotation_type(ann):
    """Coarse output type from a return annotation (HumanEval prompts carry them)."""
    if ann is None:
        return None
    s = ast.unparse(ann)
    for name, t in (("Optional", "optional"), ("Set", "set"), ("FrozenSet", "set"), ("set", "set"),
                    ("Dict", "dict"), ("dict", "dict"), ("Tuple", "tuple"), ("tuple", "tuple"),
                    ("List", "list"), ("list", "list")):
        if s.startswith(name + "[") or s == name:
            return t + ":" + s
    return s


def is_set_expr(node):
    return (isinstance(node, (ast.Set, ast.SetComp))
            or (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("set", "frozenset")))


def is_sorted_call(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sorted"


ORDER_FREE = {"len", "sum", "min", "max", "any", "all", "sorted", "set", "frozenset", "bool", "Counter"}


def returns_from_set(tree):
    """Flags for return values that are a set, or an ordered value built by iterating a set (CPython's hash order)."""
    flags = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        root = node.value
        if is_set_expr(root):
            flags.add("output-set")
            continue
        parent = {c: p for p in ast.walk(root) for c in ast.iter_child_nodes(p)}
        for n in ast.walk(root):
            if not is_set_expr(n):
                continue
            cur, ordered = n, False
            while cur is not root and cur in parent:
                p = parent[cur]
                if isinstance(p, (ast.Compare, ast.BoolOp)) or (
                        isinstance(p, ast.Call) and isinstance(p.func, ast.Name) and p.func.id in ORDER_FREE):
                    ordered = False
                    break
                if (isinstance(p, ast.Call) and ((isinstance(p.func, ast.Name) and p.func.id in ("tuple", "list"))
                                                 or (isinstance(p.func, ast.Attribute) and p.func.attr == "join"))) \
                        or isinstance(p, (ast.ListComp, ast.GeneratorExp)):
                    ordered = True
                cur = p
            if ordered:
                flags.add("order-from-set")
    return flags


def expected_from_asserts(source, entry):
    """Types of the literal expected values in `assert f(...) == literal` lines, and comparison flags."""
    types, flags = set(), set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return types, {"unparsable-asserts"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        t = node.test
        text = ast.unparse(t)
        if "isclose" in text or (isinstance(t, ast.Compare) and isinstance(t.ops[0], ast.Lt) and "abs(" in text):
            flags.add("float-tolerance")
        if isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], (ast.Eq, ast.Is)):
            left, right = t.left, t.comparators[0]
            if is_set_expr(left) or is_sorted_call(left):
                flags.add("assert-order-insensitive")
            if (isinstance(left, ast.Call) and isinstance(left.func, ast.Name) and left.func.id in (entry, "candidate")):
                lt = literal_type(right)
                if lt is not None:
                    types.add(lt)
    return types, flags


def classify(row, dataset):
    entry = row["entry_point"]
    flags = set()
    inputs = (row.get("base_input") or []) + (row.get("plus_input") or [])
    for inp in inputs:
        walk_json(inp, flags)
    input_chars = len(json.dumps(inputs))
    if input_chars > LARGE_INPUT_CHARS:
        flags.add("large-inputs")
    if row.get("atol", 0):
        flags.add("float-tolerance")

    ann = None
    if dataset == "HumanEval+":
        try:
            for node in ast.walk(ast.parse(row["prompt"])):
                if isinstance(node, ast.FunctionDef) and node.name == entry:
                    ann = annotation_type(node.returns)
                    if any(a.annotation is not None and "Any" in ast.unparse(a.annotation) for a in node.args.args):
                        flags.add("input-any")
        except SyntaxError:
            flags.add("unparsable-prompt")
        asserts = row.get("test", "")
    else:
        asserts = row.get("assertion", "") or row.get("prompt", "")
    expected, aflags = expected_from_asserts(asserts, entry)
    flags |= aflags
    try:
        flags |= returns_from_set(ast.parse(row["canonical_solution"]) if dataset == "MBPP+"
                                  else ast.parse(row["prompt"] + row["canonical_solution"]))
    except SyntaxError:
        flags.add("unparsable-solution")

    otypes = set(expected)
    if ann:
        otypes.add("annotation:" + ann)
    joined = " ".join(sorted(otypes))
    if "set" in {t.split("[")[0] for t in expected} or ann and ann.startswith("set:"):
        flags.add("output-set")
    if "dict-nonstr" in joined:
        flags.add("output-dict-nonstr-keys")
    if "complex" in joined:
        flags.add("output-complex")
    if "bigint" in joined:
        flags.add("bigint")
    float_only = {"float", "list[float]", "tuple[float]", "annotation:float", "annotation:list:List[float]",
                  "annotation:tuple:Tuple[float, float]"}
    if otypes & float_only:
        flags.add("float-tolerance")  # EvalPlus enforces atol 1e-6 when the expected value is a float or all floats
    elif "float" in joined and "float-tolerance" not in flags:
        flags.add("float-exact")
    special = SPECIAL_ORACLES.get((dataset, entry))
    if special:
        flags.add(special)
    if "none" in expected or (ann and ann.startswith("optional:")) or ann == "None":
        flags.add("returns-none")
    if not otypes:
        flags.add("no-output-type")

    if flags & INCOMPATIBLE.keys():
        cls = "incompatible"
    elif flags & ADAPTER.keys():
        cls = "needs-adapter"
    elif flags & CAUTION.keys():
        cls = "direct-with-caution"
    else:
        cls = "direct"
    return {
        "taskId": row["task_id"], "entryPoint": entry, "class": cls, "reasons": sorted(flags),
        "outputTypes": sorted(otypes), "atol": row.get("atol", 0),
        "baseCases": len(row.get("base_input") or []), "plusCases": len(row.get("plus_input") or []),
        "inputChars": input_chars,
    }


def git(*args):
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True,
                              cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
    except Exception:
        return None


def main():
    warnings.simplefilter("ignore", SyntaxWarning)  # invalid escapes in dataset strings; parsing only
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(os.environ.get("AIJADE_DATA_DIR", os.path.expanduser("~/.local/share/aijade-data")), "evalplus"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    result = {"experiment": "P2-A stage 0: static compatibility of EvalPlus tasks with the RQ-C JavaScript oracle "
                            "(no generation, nothing from the datasets executed)",
              "reasonCodes": {"incompatible": INCOMPATIBLE, "needs-adapter": ADAPTER, "direct-with-caution": CAUTION},
              "datasets": {}}
    for name, fname, want in DATASETS:
        path = os.path.join(a.data, fname)
        got = sha256(path)
        if got != want:
            sys.exit(f"{name}: SHA-256 mismatch for {path} (got {got}, expected {want})")
        rows = [json.loads(line) for line in gzip.open(path, "rt", encoding="utf-8")]
        tasks = [classify(r, name) for r in rows]
        by_class, by_reason = {}, {}
        for t in tasks:
            by_class[t["class"]] = by_class.get(t["class"], 0) + 1
            for r in t["reasons"]:
                by_reason[r] = by_reason.get(r, 0) + 1
        result["datasets"][name] = {
            "file": fname, "sha256": got, "tasks": len(tasks),
            "byClass": dict(sorted(by_class.items())), "byReason": dict(sorted(by_reason.items())),
            "perTask": tasks,
        }
    result["provenance"] = {
        "script": "tools/data/evalplus_compat.py", "gitCommit": git("rev-parse", "HEAD"),
        "scriptDirty": bool(git("status", "--porcelain", "--", "evalplus_compat.py")),
        "python": sys.version.split()[0],
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    for name, d in result["datasets"].items():
        print(name, d["tasks"], d["byClass"])
        print("  ", d["byReason"])


if __name__ == "__main__":
    main()
