#!/usr/bin/env python3
"""Actual pinned external write/read APIs, crossed scoring/policy settings, no model calls.

Run in the existing P3-C environment. Production and installed package sources are not edited.
All vectors are replayed from the hash-checked public capture; missing inputs reject execution.
"""
import argparse
import array
import datetime as dt
import gzip
import hashlib
import importlib.metadata as metadata
import inspect
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch
import warnings

os.environ['MEM0_TELEMETRY'] = 'False'
os.environ['ANONYMIZED_TELEMETRY'] = 'False'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'

ROOT = Path(__file__).resolve().parents[3]
PLAN = '132bfda51b95fd4b0ebfc23304142d56bfcb455b'
CORPUS_SHA = '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
PINS = {'langchain-classic': 'b4aa7e7d00c452251720ce30b8bc2c41ca44e1f5',
        'mem0ai': 'ed1f10fc87080f0b67f99be370817504888462ab'}
CELLS = [('on', 'own'), ('on', 'relevance'), ('off', 'own'), ('off', 'relevance')]
START = dt.datetime(2026, 11, 10, 12, 0)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def write_row(stream, row):
    stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    stream.flush()


class Replay:
    def __init__(self, packet):
        receipt = json.loads((packet / 'receipt.json').read_text())
        rel = 'attempt-02/embedding/embeddings-shared-memory-only-embedding.jsonl.gz'
        source = packet / rel
        assert sha(source) == receipt['artifactSha256'][rel]
        self.vectors = {}
        self.calls = 0
        self.misses = 0
        self.source_sha = sha(source)
        with gzip.open(source, 'rt') as stream:
            for line in stream:
                event = json.loads(line)
                assert event['status'] == 200
                inputs = event['input']['input']
                data = json.loads(event['response'])['data']
                assert len(data) == len(inputs)
                for item in data:
                    key = inputs[item['index']]
                    vector = array.array('f', item['embedding'])
                    assert len(vector) == 768 and all(math.isfinite(v) for v in vector)
                    assert key not in self.vectors or self.vectors[key] == vector, 'conflicting repeat'
                    self.vectors[key] = vector

    def get(self, text):
        self.calls += 1
        if text not in self.vectors:
            self.misses += 1
            raise KeyError('Vector replay miss; a live model call is forbidden')
        return list(self.vectors[text])


class FixtureReplay:
    calls = 0
    misses = 0

    def get(self, text):
        self.calls += 1
        cosine = 0.05 if text == 'fixture-low' else 0.8 if text == 'fixture-mid' else 1.0
        return [cosine, math.sqrt(1 - cosine * cosine)] + [0.0] * 766


def identities():
    from langchain_classic.retrievers.time_weighted_retriever import TimeWeightedVectorStoreRetriever
    from mem0 import Memory
    from mem0.utils.scoring import score_and_rank
    source = {}
    packages = {}
    for name, pin in PINS.items():
        dist = metadata.distribution(name)
        origin = json.loads(dist.read_text('direct_url.json'))
        assert pin in origin['url'], (name, origin)
        packages[name] = {'version': dist.version, 'origin': origin}
    for name in ['langchain-community', 'langchain-core', 'qdrant-client', 'faiss-cpu', 'numpy', 'pydantic']:
        packages[name] = {'version': metadata.version(name)}
    for obj in [TimeWeightedVectorStoreRetriever, Memory, score_and_rank]:
        path = Path(inspect.getfile(obj))
        source[obj.__module__] = {'filename': path.name, 'sha256': sha(path)}
    return {'python': sys.version, 'packages': packages, 'sourceFiles': source}


class LangChainTrajectory:
    def __init__(self, conv, replay, policy, scorer):
        import faiss
        from langchain_classic.retrievers.time_weighted_retriever import TimeWeightedVectorStoreRetriever
        from langchain_community.vectorstores import FAISS
        from langchain_community.docstore.in_memory import InMemoryDocstore
        from langchain_core.documents import Document
        from langchain_core.embeddings import Embeddings
        from pydantic import Field

        class E(Embeddings):
            def embed_documents(self, texts):
                return [replay.get(text) for text in texts]

            def embed_query(self, text):
                return replay.get(text.strip())

        class Observed(TimeWeightedVectorStoreRetriever):
            relevance_only: bool = False
            trace: list = Field(default_factory=list)

            def _get_combined_score(self, document, vector_relevance, current_time):
                own = super()._get_combined_score(document, vector_relevance, current_time)
                score = (vector_relevance if vector_relevance is not None else 0.0) if self.relevance_only else own
                self.trace.append({'source': document.metadata['source_turn'], 'own': own, 'relevance': vector_relevance,
                                   'used': score, 'lastAccess': document.metadata['last_accessed_at'].isoformat(),
                                   'time': current_time.isoformat()})
                return score

        faiss.omp_set_num_threads(1)
        store = FAISS(E(), faiss.IndexFlatL2(768), InMemoryDocstore({}), {}, normalize_L2=True)
        self.retriever = Observed(vectorstore=store, k=8, relevance_only=scorer == 'relevance')
        self.policy = policy
        docs = []
        for turn in conv['turns']:
            when = START - dt.timedelta(milliseconds=conv['endTs'] - turn['createdAt'])
            docs.append(Document(id=turn['id'], page_content=turn['content'],
                                 metadata={'source_turn': turn['id'], 'created_at': when, 'last_accessed_at': when}))
        self.ids = self.retriever.add_documents(docs, current_time=START)
        assert len(self.ids) == len(docs)
        assert [d.metadata['source_turn'] for d in self.retriever.memory_stream] == [t['id'] for t in conv['turns']]
        self.initial = [{'id': key, 'source': doc.metadata['source_turn'], 'content': doc.page_content,
                         'createdAt': doc.metadata['created_at'].isoformat(), 'lastAccess': doc.metadata['last_accessed_at'].isoformat()}
                        for key, doc in zip(self.ids, self.retriever.memory_stream)]

    def read(self, question, q):
        from langchain_core.utils import mock_now
        retriever = self.retriever
        before = [doc.metadata['last_accessed_at'] for doc in retriever.memory_stream]
        retriever.trace.clear()
        with warnings.catch_warnings(record=True) as caught, mock_now(START + dt.timedelta(minutes=q)):
            docs = retriever.invoke(question)
        actual_writes = []
        for i, doc in enumerate(retriever.memory_stream):
            after = doc.metadata['last_accessed_at']
            if after != before[i]:
                actual_writes.append({'source': doc.metadata['source_turn'], 'before': before[i].isoformat(),
                                      'written': after.isoformat(), 'retained': self.policy == 'on'})
            if self.policy == 'off':
                doc.metadata['last_accessed_at'] = before[i]
        trace = list(retriever.trace)
        ordered = sorted(trace, key=lambda row: -row['used'])[:8]
        assert [doc.metadata['source_turn'] for doc in docs] == [row['source'] for row in ordered]
        by_source = {row['source']: row for row in trace}
        delivered = [{'id': str(doc.id), 'source': doc.metadata['source_turn'], 'content': doc.page_content,
                      'score': by_source[doc.metadata['source_turn']]['used']} for doc in docs]
        return {'candidates': trace, 'poolIds': [row['source'] for row in trace], 'aboveIds': [row['source'] for row in trace],
                'delivered': delivered, 'accessWrites': actual_writes, 'warnings': [str(w.message) for w in caught],
                'rankTies': sum(a['used'] == b['used'] for a, b in zip(sorted(trace, key=lambda x: -x['used']), sorted(trace, key=lambda x: -x['used'])[1:]))}


class ForbiddenLLM:
    calls = 0

    def generate_response(self, *args, **kwargs):
        self.calls += 1
        raise RuntimeError('LLM call is outside this turn-storage policy comparison')


class Mem0Store:
    def __init__(self, conv, replay, directory):
        from mem0 import Memory
        from mem0.embeddings.base import EmbeddingBase

        class E(EmbeddingBase):
            def embed(self, text, memory_action=None):
                return replay.get(text.strip() if memory_action == 'search' else text)

        directory.mkdir()
        self.llm = ForbiddenLLM()
        with patch('mem0.memory.main.EmbedderFactory.create', return_value=E()), patch('mem0.memory.main.LlmFactory.create', return_value=self.llm):
            self.memory = Memory.from_config({
                'vector_store': {'provider': 'qdrant', 'config': {'path': str(directory / 'qdrant'), 'on_disk': False,
                                  'embedding_model_dims': 768, 'collection_name': 'policy'}},
                'embedder': {'provider': 'ollama', 'config': {'model': 'nomic-embed-text', 'embedding_dims': 768}},
                'llm': {'provider': 'ollama', 'config': {'model': 'qwen2.5-coder:7b-instruct'}},
                'history_db_path': str(directory / 'history.db'),
            })
        self.writes = []
        for turn in conv['turns']:
            result = self.memory.add([{'role': 'user', 'content': turn['content']}], user_id='p3-policy',
                                     metadata={'source_turn': turn['id'], 'source_created_at_ms': turn['createdAt']},
                                     infer=False)
            assert len(result['results']) == 1
            self.writes.append({'source': turn['id'], 'id': result['results'][0]['id'], 'event': result['results'][0]['event']})
        stored = self.memory.get_all(filters={'user_id': 'p3-policy'}, top_k=2000)['results']
        assert len(stored) == len(conv['turns'])
        by_source = {row['metadata']['source_turn']: row for row in stored}
        assert len(by_source) == len(stored)
        for turn in conv['turns']:
            assert by_source[turn['id']]['memory'] == turn['content']
        self.initial = stored

    def read(self, question, policy, scorer):
        from mem0.utils.scoring import score_and_rank
        trace = []

        def observe(semantic_results, bm25_scores, entity_boosts, threshold, top_k, explain=False):
            trace.extend({'source': row['payload']['source_turn'], 'id': str(row['id']), 'semantic': float(row['score']),
                          'bm25': bm25_scores.get(str(row['id']), 0.0), 'entity': entity_boosts.get(str(row['id']), 0.0),
                          'divisor': 1.0 + (1.0 if bm25_scores else 0.0) + (0.5 if entity_boosts else 0.0)}
                         for row in semantic_results)
            return score_and_rank(semantic_results, bm25_scores if scorer == 'own' else {},
                                  entity_boosts if scorer == 'own' else {}, threshold, top_k, explain)

        threshold = 0.1 if policy == 'on' else 0.0
        with patch('mem0.memory.main.score_and_rank', side_effect=observe):
            raw = self.memory.search(question, filters={'user_id': 'p3-policy'}, top_k=60, threshold=threshold,
                                     rerank=False, explain=True)
        assert trace and self.llm.calls == 0
        source = {str(row['id']): row['source'] for row in trace}
        delivered = [{'id': row['id'], 'source': source[str(row['id'])], 'content': row['memory'], 'score': row['score']}
                     for row in raw['results'][:8]]
        return {'candidates': trace, 'poolIds': [row['source'] for row in trace],
                'aboveIds': [row['source'] for row in trace if row['semantic'] >= threshold],
                'delivered': delivered, 'rawApiOutput': raw, 'threshold': threshold, 'apiOutputLimit': 60,
                'internalCandidateLimit': 240, 'accessWrites': [], 'warnings': []}

    def close(self):
        assert self.llm.calls == 0
        self.memory.vector_store.client.close()
        if self.memory._entity_store is not None:
            self.memory._entity_store.client.close()
        if hasattr(self.memory.db, 'close'):
            self.memory.db.close()


def qualify(out):
    replay = FixtureReplay()
    conv = {'endTs': 60000, 'turns': [
        {'id': 'F1', 'content': 'fixture-high', 'createdAt': -10800000},
        {'id': 'F2', 'content': 'fixture-low', 'createdAt': -7200000},
        {'id': 'F3', 'content': 'fixture-mid', 'createdAt': 0},
    ]}
    trajectories = {cell: LangChainTrajectory(conv, replay, *cell) for cell in CELLS}
    for (policy, scorer), trajectory in trajectories.items():
        row = trajectory.read('fixture-query', 1)
        assert len(row['delivered']) == 3 and len(row['accessWrites']) == 3
        initial = {r['source']: r['lastAccess'] for r in trajectory.initial}
        after = {d.metadata['source_turn']: d.metadata['last_accessed_at'].isoformat() for d in trajectory.retriever.memory_stream}
        assert (after == initial) == (policy == 'off')
        if scorer == 'relevance':
            assert all(t['used'] == (t['relevance'] if t['relevance'] is not None else 0.0) for t in row['candidates'])
    store = Mem0Store(conv, replay, out / 'fixture-mem0')
    counts = {}
    for policy, scorer in CELLS:
        row = store.read('fixture-query', policy, scorer)
        counts[policy + '-' + scorer] = len(row['delivered'])
        assert ('F2' in {r['source'] for r in row['delivered']}) == (policy == 'off')
    store.close()
    dump(out / 'qualification.json', {'status': 'PASS', 'packageIdentities': identities(), 'mem0OutputCounts': counts,
                                    'langchainCells': 4, 'sourceMapping': 'one unique source per stored turn',
                                    'newModelCalls': 0, 'fixtureOnly': True})
    print('External synthetic write/read/scorer/policy qualification PASS', flush=True)


def run(args):
    started = time.monotonic()
    args.out.mkdir(parents=True, exist_ok=False)
    identity = identities()
    if args.qualify:
        qualify(args.out)
        return
    assert sha(args.raw_corpus) == CORPUS_SHA
    corpus = json.loads(args.corpus.read_text())
    assert len(corpus) == 10 and sum(len(c['questions']) for c in corpus) == 1986
    replay = Replay(args.source)
    for c, conv in enumerate(corpus):
        with gzip.open(args.source / f'attempt-02/embedding/store-shared-memory-only-embedding-{c}.json.gz', 'rt') as f:
            by_id = {row['Id']: row for row in json.load(f)}
        assert len(by_id) == len(conv['turns'])
        for turn in conv['turns']:
            key = 'ep_locomo-%s-%s' % (c, turn['id'].replace(':', '-'))
            assert by_id[key]['Content'] == turn['content']
            assert turn['content'] in replay.vectors
        for question in conv['questions']:
            assert question['question'].strip() in replay.vectors
    code = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dump(args.out / 'started.json', {'schema': 'aijade.p3.policy.external-start.v1', 'system': args.system,
                                    'planCommit': PLAN, 'codeCommit': code, 'identities': identity,
                                    'corpusSha256': CORPUS_SHA, 'exportSha256': sha(args.corpus),
                                    'embeddingSourceSha256': replay.source_sha, 'uniqueReplayInputs': len(replay.vectors),
                                    'deviations': ['unprefixed captured vectors, conditional replay',
                                                   'Mem0 native top_k=60 over-fetches 240 candidates; final readout K=8',
                                                   'Mem0 OSS rejects timestamp; its own write clock is used and corpus time remains source metadata',
                                                   'LangChain relevance-only preserves native FAISS relevance; missing default salience maps to zero']})
    total = 0
    path = args.out / (args.system + '.jsonl.gz')
    with gzip.open(path, 'xt', encoding='utf-8') as journal:
        for c, conv in enumerate(corpus):
            store = None
            if args.system == 'langchain':
                trajectories = {cell: LangChainTrajectory(conv, replay, *cell) for cell in CELLS}
                snapshots = {policy + '-' + scorer: trajectory.initial for (policy, scorer), trajectory in trajectories.items()}
            else:
                store = Mem0Store(conv, replay, args.out / ('store-%s' % c))
                snapshots = {'items': store.initial, 'writes': store.writes}
            with gzip.open(args.out / ('store-%s.json.gz' % c), 'xt', encoding='utf-8') as f:
                json.dump(snapshots, f, ensure_ascii=False, allow_nan=False)
            source_ids = {turn['id'] for turn in conv['turns']}
            for q, question in enumerate(conv['questions']):
                for policy, scorer in CELLS:
                    result = trajectories[(policy, scorer)].read(question['question'], q) if store is None else store.read(question['question'], policy, scorer)
                    assert set(result['poolIds']) <= source_ids and len(result['poolIds']) == len(set(result['poolIds']))
                    assert {r['source'] for r in result['delivered']} <= set(result['aboveIds'])
                    row = {'system': args.system, 'c': c, 'q': q, 'question': question['question'], 'category': question['category'],
                           'answerable': question['category'] != 5, 'gold': list(dict.fromkeys(question['evidence'])),
                           'policy': policy, 'scorer': scorer, 'storedSources': len(source_ids), 'sourceItems': 'one turn', **result}
                    write_row(journal, row)
                    total += 1
                if q % 25 == 0:
                    (args.out / 'progress.json').write_text(json.dumps({'system': args.system, 'c': c, 'q': q, 'rows': total,
                                                                      'elapsedMinutes': (time.monotonic() - started) / 60}) + '\n')
            if store is not None:
                store.close()
            print(args.system, 'conversation', c, 'rows', total, flush=True)
    assert total == 7944 and replay.misses == 0
    dump(args.out / 'receipt.json', {'schema': 'aijade.p3.policy.external.v1', 'status': 'ALL_CONFIGURED_CELLS_COMPLETE',
                                   'system': args.system, 'rows': total, 'conversations': 10, 'questionsPerCell': 1986,
                                   'planCommit': PLAN, 'codeCommit': code, 'identities': identity,
                                   'sourceSha256': sha(Path(__file__)), 'journalSha256': sha(path),
                                   'replayLookups': replay.calls, 'replayMisses': replay.misses, 'newModelCalls': 0,
                                   'elapsedMinutes': (time.monotonic() - started) / 60,
                                   'scope': 'complete named write/read policy configuration, one source turn/item, conditional vector replay; not an LLM fact-extraction or answer benchmark'})
    print('COMPLETE', args.system, total, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--system', choices=['langchain', 'mem0'])
    parser.add_argument('--qualify', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT / 'experiments/p3-e/2026-11-10-shared-runtime')
    parser.add_argument('--corpus', type=Path, default=Path('/Users/mac/.local/share/aijade-data/locomo-export.json'))
    parser.add_argument('--raw-corpus', type=Path, default=Path('/Users/mac/.local/share/aijade-data/locomo10.json'))
    options = parser.parse_args()
    assert options.qualify or options.system
    run(options)
