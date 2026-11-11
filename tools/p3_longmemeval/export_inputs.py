#!/usr/bin/env python3
"""Input-only, complete source eligibility ledger. No retrieval or model execution."""
import argparse
import collections
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import re

DATA_SHA = 'd6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442'
PLAN = 'a7961cf8cde1de659c2272a664d4c936a50484c4'
OFFICIAL = '9e0b455f4ef0e2ab8f2e582289761153549043fc'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode()


def timestamp(text):
    match = re.search(r'(\d{4})/(\d{2})/(\d{2})\s*\(\w+\)\s*(\d{2}):(\d{2})', text)
    return dt.datetime(*map(int, match.groups()), tzinfo=dt.timezone.utc).timestamp() * 1000 if match else None


def export(data, output, official):
    raw = data.read_bytes()
    assert sha(raw) == DATA_SHA
    source = json.loads(raw)
    assert len(source) == len({q['question_id'] for q in source}) == 500
    output.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, relative in [('README.md', 'README.md'), ('print_retrieval_metrics.py', 'src/evaluation/print_retrieval_metrics.py'), ('LICENSE', 'LICENSE')]:
        content = (official / name).read_bytes()
        manifest.append(dict(path=name, url=f'https://raw.githubusercontent.com/xiaowu0162/LongMemEval/{OFFICIAL}/{relative}', sha256=sha(content), bytes=len(content)))
    metrics_source = (official / 'print_retrieval_metrics.py').read_text()
    assert "'_abs' not in x['question_id']" in metrics_source
    sessions = collections.defaultdict(list)
    summary = collections.Counter()
    types = collections.Counter()
    answerable_types = collections.Counter()
    with gzip.open(output / 'eligibility.jsonl.gz', 'xt', encoding='utf-8') as ledger, gzip.open(output / 'expected-answers.jsonl.gz', 'xt', encoding='utf-8') as answers:
        for index, q in enumerate(source):
            abstention = '_abs' in q['question_id']
            assert abstention == q['question_id'].endswith('_abs')
            types[q['question_type']] += 1
            if not abstention:
                answerable_types[q['question_type']] += 1
            turns, gold, session_rows = [], [], []
            text_counts = collections.Counter()
            source_marks = collections.Counter()
            for s, session in enumerate(q['haystack_sessions']):
                sid = q['haystack_session_ids'][s] if s < len(q['haystack_session_ids']) else f'session_{s}'
                date = q['haystack_dates'][s] if s < len(q['haystack_dates']) else ''
                start = timestamp(date)
                fallback = start is None
                if fallback:
                    start = dt.datetime(2023, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000 + s * 86_400_000
                session_hash = sha(canonical([{'role': t.get('role'), 'content': t.get('content', '')} for t in session]))
                sessions[sid].append((index, s, session_hash))
                session_rows.append(dict(position=s, id=sid, rawDate=date, timestamp=start, dateFallback=fallback, contentSha256=session_hash))
                for j, turn in enumerate(session):
                    text = turn.get('content', '') or ''
                    marked = turn.get('has_answer') is True
                    turn_id = f'{s}:{sid}#{j}'
                    text_hash = sha(text.encode())
                    text_counts[text_hash] += 1
                    if marked:
                        gold.append(turn_id)
                        source_marks[(sid, j)] += 1
                    turns.append(dict(id=turn_id, sessionPosition=s, turnPosition=j, role=turn.get('role'), rolePresent='role' in turn,
                                      hasAnswer=marked, hasAnswerPresent='has_answer' in turn, rawHasAnswer=turn.get('has_answer'), contentPresent='content' in turn,
                                      contentSha256=text_hash, utf8Bytes=len(text.encode()),
                                      utf16Length=len(text.encode('utf-16-le')) // 2, blank=not text.strip(), timestamp=start + j * 60_000))
            assert gold or abstention, q['question_id']
            summary['rawQuestions'] += 1
            summary['abstentionQuestions'] += abstention
            summary['markedQuestions'] += bool(gold)
            summary['primaryQuestions'] += not abstention
            summary['abstentionWithMarks'] += abstention and bool(gold)
            summary['turnOccurrences'] += len(turns)
            summary['blankTurns'] += sum(t['blank'] for t in turns)
            summary['blankMarkedTurns'] += sum(t['blank'] and t['hasAnswer'] for t in turns)
            summary['markedTurns'] += len(gold)
            summary['primaryMarkedTurns'] += len(gold) if not abstention else 0
            summary['duplicateTextHistories'] += any(n > 1 for n in text_counts.values())
            summary['repeatedSessionIdHistories'] += len({s['id'] for s in session_rows}) < len(session_rows)
            summary['duplicatedMarkedSourceOccurrences'] += sum(n - 1 for n in source_marks.values())
            summary['plannedProductWrites'] += sum(not t['blank'] for t in turns)
            row = dict(rawIndex=index, questionId=q['question_id'], questionType=q['question_type'],
                       sourceQuestionCanonicalSha256=sha(canonical(q)), question=q['question'], questionSha256=sha(q['question'].encode()),
                       answerable=not abstention, officialAbstention=abstention, legacyMarked=bool(gold),
                       inclusionReason='official-non-abstention-with-marked-evidence' if not abstention else 'official-abstention-excluded-even-if-marked',
                       questionDate=q.get('question_date'), questionDateFallback=timestamp(q.get('question_date', '')) is None,
                       markedIds=gold, sessions=session_rows, turns=turns,
                       duplicateTextGroups={k: n for k, n in text_counts.items() if n > 1})
            ledger.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
            answers.write(json.dumps(dict(rawIndex=index, questionId=q['question_id'], answer=q.get('answer'), answerSessionIds=q.get('answer_session_ids')), ensure_ascii=False) + '\n')
    assert dict((k, summary[k]) for k in ['primaryQuestions', 'abstentionQuestions', 'markedQuestions', 'abstentionWithMarks', 'turnOccurrences', 'blankTurns', 'plannedProductWrites']) == dict(primaryQuestions=470, abstentionQuestions=30, markedQuestions=479, abstentionWithMarks=9, turnOccurrences=246750, blankTurns=12, plannedProductWrites=246738)
    dependence = [dict(id=sid, occurrences=[dict(rawIndex=i, sessionPosition=s, contentSha256=h) for i, s, h in rows], contentVariants=len({h for _, _, h in rows})) for sid, rows in sessions.items()]
    with gzip.open(output / 'session-dependence.json.gz', 'xt', encoding='utf-8') as f:
        json.dump(dependence, f, ensure_ascii=False, separators=(',', ':'))
    receipt = dict(schema='aijade.p3.longmemeval.input.v2', planCommit=PLAN, corpusSha256=DATA_SHA, counts=summary,
                   rawQuestionTypes=types, primaryQuestionTypes=answerable_types, uniqueSessionIds=len(sessions),
                   crossQuestionSharedSessionIds=sum(len({i for i, _, _ in rows}) > 1 for rows in sessions.values()),
                   inconsistentSessionIds=sum(len({h for _, _, h in rows}) > 1 for rows in sessions.values()), officialSources=manifest,
                   frames=['answerable-v2', 'legacy-marked-v1', 'all-questions-v1'],
                   limitations='Question cases reuse source sessions; no independent-user population claim. Frozen cleaned _s release, not V2.')
    (output / 'input-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    assert sha(data.read_bytes()) == DATA_SHA
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--official', type=Path, required=True)
    args = parser.parse_args()
    export(args.data, args.out, args.official)
