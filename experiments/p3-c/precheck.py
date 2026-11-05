#!/usr/bin/env python3
"""The scorer pre-check of P3 on independent memory systems (experiments/plans/2026-11-05-p3-c-external-memory-systems.md).

Runs inside an isolated environment (experiments/p3-c/README.md) on the corpus as the kernel reads it (`aijade-experiments
locomo-export`). Each system is written one turn per item through its own interface and read through its own scoring code.
Embeddings come from a local Ollama (nomic-embed-text v1.5). Nothing is sent anywhere else.

  python precheck.py <langchain|llamaindex|mem0> --corpus locomo-export.json --out DIR
"""
import argparse
import datetime as dt
import json
import os
import random
import statistics
import sys
import tempfile
import urllib.request

KS = (1, 2, 4, 8)
ITERATIONS = 10000
MODEL = "nomic-embed-text"
MANIFEST = "0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f"
OLLAMA = "http://127.0.0.1:11434"
COMMITS = {"langchain": "b4aa7e7d00c452251720ce30b8bc2c41ca44e1f5", "llamaindex": "444fdf0684707de62ebb447d658dba137dd9cb99",
           "mem0": "ed1f10fc87080f0b67f99be370817504888462ab"}


class Embedder:
    """nomic-embed-text with its documented task prefixes; each text is embedded once."""

    def __init__(self, cache_path):
        self.path = cache_path
        self.cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}

    def embed(self, texts, prefix):
        keys = [prefix + t for t in texts]
        missing = sorted({k for k in keys if k not in self.cache})
        for i in range(0, len(missing), 64):
            batch = missing[i:i + 64]
            req = urllib.request.Request(OLLAMA + "/api/embed", json.dumps({"model": MODEL, "input": batch}).encode(),
                                         {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                vectors = json.load(r)["embeddings"]
            self.cache.update(zip(batch, vectors))
        if missing:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f)
        return [self.cache[k] for k in keys]


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (sum(x * x for x in a) ** 0.5 * sum(y * y for y in b) ** 0.5)


class LangChainSystem:
    name = "LangChain TimeWeightedVectorStoreRetriever"
    deviations = ["k = 8 (its default is 4) so that recall@8 can be read; decay_rate and search_kwargs at their defaults (0.01, k = 100)."]
    time_term = "linear"

    def __init__(self, conv, embedder):
        from langchain_classic.retrievers.time_weighted_retriever import TimeWeightedVectorStoreRetriever
        from langchain_community.vectorstores import FAISS
        from langchain_core.documents import Document
        from langchain_core.embeddings import Embeddings
        import faiss
        from langchain_community.docstore.in_memory import InMemoryDocstore

        class E(Embeddings):
            def embed_documents(self, texts):
                return embedder.embed(texts, "search_document: ")

            def embed_query(self, text):
                return embedder.embed([text], "search_query: ")[0]

        self.embedder = embedder
        dim = len(embedder.embed(["x"], "search_query: ")[0])
        store = FAISS(E(), faiss.IndexFlatL2(dim), InMemoryDocstore({}), {}, normalize_L2=True)
        self.retriever = TimeWeightedVectorStoreRetriever(vectorstore=store, k=8)
        self.now = dt.datetime(2026, 11, 5, 12, 0, 0)
        end = conv["endTs"]
        docs = []
        for t in conv["turns"]:
            when = self.now - dt.timedelta(milliseconds=end - t["createdAt"])
            docs.append(Document(page_content=t["content"], metadata={"turn": t["id"], "last_accessed_at": when, "created_at": when}))
        self.retriever.add_documents(docs)

    def rank(self, query):
        """The retriever's own candidates and combined score, without the write-back of last_accessed_at."""
        r = self.retriever
        pool = {d.metadata["buffer_idx"]: (d, r.default_salience) for d in r.memory_stream[-r.k:]}
        pool.update(r.get_salient_docs(query))
        q = self.embedder.embed([query], "search_query: ")[0]
        rows = []
        for doc, relevance in pool.values():
            d = self.embedder.embed([doc.page_content], "search_document: ")[0]
            rows.append({"turn": doc.metadata["turn"], "own": r._get_combined_score(doc, relevance, self.now), "relevance": cosine(q, d)})
        return rows

    steps = []


class LlamaIndexSystem:
    name = "LlamaIndex TimeWeightedPostprocessor"
    deviations = ["top_k = 8 (its default is 1) and time_access_refresh off, so that one read does not change the next; the candidates are the 100 most similar items, the size LangChain's retriever uses, since the postprocessor takes whatever list it is given."]
    time_term = "linear"

    def __init__(self, conv, embedder):
        self.embedder = embedder
        self.now = dt.datetime(2026, 11, 5, 12, 0, 0).timestamp()
        end = conv["endTs"]
        self.turns = [(t["id"], t["content"], self.now - (end - t["createdAt"]) / 1000.0) for t in conv["turns"]]
        self.vectors = embedder.embed([t[1] for t in self.turns], "search_document: ")

    def rank(self, query):
        from llama_index.core.postprocessor import TimeWeightedPostprocessor
        from llama_index.core.schema import NodeWithScore, TextNode
        q = self.embedder.embed([query], "search_query: ")[0]
        sims = sorted(((cosine(q, v), i) for i, v in enumerate(self.vectors)), reverse=True)[:100]
        nodes = [NodeWithScore(node=TextNode(id_=self.turns[i][0], text=self.turns[i][1], metadata={"__last_accessed__": self.turns[i][2]}), score=s) for s, i in sims]
        post = TimeWeightedPostprocessor(time_decay=0.99, top_k=len(nodes), now=self.now, time_access_refresh=False)
        out = post.postprocess_nodes(nodes)
        relevance = {n.node.id_: n.score for n in nodes}
        return [{"turn": n.node.id_, "own": n.score, "relevance": relevance[n.node.id_]} for n in out]

    steps = []


class Mem0System:
    name = "Mem0"
    deviations = ["Written with infer=False, which stores each turn as given: its default runs a language model over every write, which is not practical for 5,882 turns on the Mac, so the stored items are turns and not extracted facts."]
    time_term = "none"

    def __init__(self, conv, embedder):
        from mem0 import Memory
        self.embedder = embedder
        self.dir = tempfile.mkdtemp(prefix="p3c-mem0-")
        self.memory = Memory.from_config({
            "vector_store": {"provider": "qdrant", "config": {"path": self.dir, "on_disk": False, "embedding_model_dims": 768, "collection_name": "c"}},
            "embedder": {"provider": "ollama", "config": {"model": MODEL, "embedding_dims": 768, "ollama_base_url": OLLAMA}},
            "llm": {"provider": "ollama", "config": {"model": "qwen2.5-coder:7b-instruct", "ollama_base_url": OLLAMA}},
            "history_db_path": os.path.join(self.dir, "history.db"),
        })
        self.by_text = {}
        for t in conv["turns"]:
            self.by_text.setdefault(t["content"], t["id"])
            self.memory.add([{"role": "user", "content": t["content"]}], user_id="u", infer=False)

    def rank(self, query, threshold=0.1):
        from mem0.utils.scoring import score_and_rank  # noqa: F401  (the code under test, reached through search)
        own = self.memory.search(query, filters={"user_id": "u"}, top_k=60, threshold=threshold)["results"]
        vectors = self.memory.embedding_model.embed(query, "search")
        semantic = self.memory.vector_store.search(query=query, vectors=vectors, top_k=60, filters={"user_id": "u"})
        rel = {m.payload["data"]: m.score for m in semantic}
        rows = [{"turn": self.by_text.get(m["memory"]), "own": m["score"], "relevance": rel.get(m["memory"], 0.0)} for m in own]
        return rows

    steps = [("semantic threshold off", {"threshold": 0.0})]


SYSTEMS = {"langchain": LangChainSystem, "llamaindex": LlamaIndexSystem, "mem0": Mem0System}


def hits(rows, gold, order, k):
    top = sorted(rows, key=lambda r: -r[order])[:k]
    return any(r["turn"] in gold for r in top)


def bootstrap(a, b, n, statistic, seed=0x5EED2026):
    rng = random.Random(seed)
    idx = list(range(len(a)))
    values = []
    for _ in range(ITERATIONS):
        sample = [rng.choice(idx) for _ in idx]
        values.append(statistic(sample))
    values.sort()
    return values[int(0.025 * (ITERATIONS - 1))], values[int(0.975 * (ITERATIONS - 1) + 0.999999)]


def micro_contrast(a, b, n):
    """a, b: hits per conversation; n: questions per conversation. Conversation bootstrap and exact sign-flip test."""
    def rate(hits_, idx):
        return sum(hits_[i] for i in idx) / max(1, sum(n[i] for i in idx))
    all_ = list(range(len(n)))
    diff = rate(a, all_) - rate(b, all_)
    lo, hi = bootstrap(a, b, n, lambda s: rate(a, s) - rate(b, s))
    d = [x - y for x, y in zip(a, b)]
    total = sum(n)
    observed = abs(sum(d) / total)
    extreme = 0
    for mask in range(1 << len(d)):
        s = sum(-x if mask >> i & 1 else x for i, x in enumerate(d))
        if abs(s / total) >= observed - 1e-12:
            extreme += 1
    return {"a": rate(a, all_), "b": rate(b, all_), "difference": diff, "bootstrap95": [lo, hi], "signFlipP": extreme / (1 << len(d)),
            "unitsPositive": sum(1 for x, m in zip(d, n) if x > 0), "unitsNegative": sum(1 for x in d if x < 0), "units": len(d)}


def quartiles(xs):
    xs = sorted(xs)
    q = statistics.quantiles(xs, n=4)
    return {"median": statistics.median(xs), "q1": q[0], "q3": q[2], "max": xs[-1]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("system", choices=sorted(SYSTEMS))
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default=os.path.expanduser("~/.local/share/aijade-data/p3c-embeddings.json"))
    args = ap.parse_args()
    corpus = json.load(open(args.corpus, encoding="utf-8"))
    embedder = Embedder(args.cache)
    # every text once, up front, so that the cache is written once
    embedder.embed([t["content"] for c in corpus for t in c["turns"]], "search_document: ")
    embedder.embed([q["question"] for c in corpus for q in c["questions"]], "search_query: ")
    cls = SYSTEMS[args.system]
    per_conv = {"answerable": [], "all": []}
    for ci, conv in enumerate(corpus):
        print(f"{args.system}: conversation {ci + 1}/{len(corpus)}", flush=True)
        system = cls(conv, embedder)
        times = {t["id"]: t["createdAt"] for t in conv["turns"]}
        created = sorted(times.values())
        for key, keep in (("answerable", lambda q: q["category"] != 5), ("all", lambda q: True)):
            per_conv[key].append({"n": 0, "covered": 0, "own": {k: 0 for k in KS}, "rel": {k: 0 for k in KS}, "newer": [], "unbiased": [], "steps": {}})
        for q in conv["questions"]:
            gold = {e for e in q["evidence"] if e in times}  # a cited id that names no turn is not evidence in the store
            rows = system.rank(q["question"])
            step_rows = {name: system.rank(q["question"], **kw) for name, kw in system.steps}
            for key, keep in (("answerable", q["category"] != 5), ("all", True)):
                if not keep:
                    continue
                c = per_conv[key][-1]
                c["n"] += 1
                c["covered"] += any(r["turn"] in gold for r in rows)
                for k in KS:
                    c["own"][k] += hits(rows, gold, "own", k)
                    c["rel"][k] += hits(rows, gold, "relevance", k)
                if gold:
                    newest = max(times[e] for e in gold if e in times)
                    top = sorted(rows, key=lambda r: -r["own"])[:8]
                    c["newer"].append(sum(1 for r in top if r["turn"] in times and times[r["turn"]] > newest))
                    c["unbiased"].append(8 * sum(1 for t in created if t > newest) / len(created))
                for name, sr in step_rows.items():
                    c["steps"][name] = c["steps"].get(name, 0) + hits(sr, gold, "own", 8)
    report = {
        "experiment": "the scorer pre-check of P3 on one independent memory system",
        "plan": "experiments/plans/2026-11-05-p3-c-external-memory-systems.md", "system": cls.name, "systemCommit": COMMITS[args.system],
        "codeCommit": os.environ.get("AIJADE_GIT_COMMIT"), "embeddingModel": MODEL, "embeddingManifestSha256": MANIFEST,
        "timeTerm": cls.time_term, "deviations": ["Run on 5 November 2026 on the Mac, before the supervisor's review of the plan: the first author's decision."] + cls.deviations,
        "storedUnit": {"unit": "one dialogue turn per item", "sourceTurnsPerItem": 1, "itemChars": quartiles([len(t["content"]) for c in corpus for t in c["turns"]])},
    }
    for key, convs in per_conv.items():
        n = [c["n"] for c in convs]
        def macro(values):
            return sum(values) / len(values)
        own8, rel8 = [c["own"][8] for c in convs], [c["rel"][8] for c in convs]
        contrast = micro_contrast(rel8, own8, n)
        newer = [x for c in convs for x in c["newer"]]
        unbiased = [x for c in convs for x in c["unbiased"]]
        s = {
            "questions": sum(n), "poolCoverage": sum(c["covered"] for c in convs) / sum(n),
            "recallOwn": {str(k): sum(c["own"][k] for c in convs) / sum(n) for k in KS},
            "recallRelevanceAlone": {str(k): sum(c["rel"][k] for c in convs) / sum(n) for k in KS},
            "contrastRelevanceAloneMinusOwn": contrast,
            "newerInTop8": statistics.mean(newer), "unbiasedExpectation": statistics.mean(unbiased),
        }
        s["ratioRelevanceOverOwn"] = contrast["a"] / contrast["b"] if contrast["b"] > 0 else None
        s["newerOverExpectation"] = s["newerInTop8"] / s["unbiasedExpectation"]
        s["markedA"] = None if not s["ratioRelevanceOverOwn"] else (s["ratioRelevanceOverOwn"] > 2 or s["ratioRelevanceOverOwn"] < 0.5)
        s["markedB"] = s["newerOverExpectation"] > 1.5
        delivered = macro([c["own"][8] / c["n"] for c in convs])
        s["step3"] = [{"switchedOff": name, "deliveredOnMacro": delivered, "deliveredOffMacro": macro([c["steps"][name] / c["n"] for c in convs])} for name, _ in cls.steps]
        report[key] = s
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{args.system}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("wrote", path, json.dumps({k: report["answerable"][k] for k in ("poolCoverage", "newerInTop8", "unbiasedExpectation", "ratioRelevanceOverOwn", "markedA", "markedB")}))


if __name__ == "__main__":
    sys.exit(main())
