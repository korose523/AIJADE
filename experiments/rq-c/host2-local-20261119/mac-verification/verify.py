#!/usr/bin/env python3
"""Offline verification of SVN r882 (P2-R local Windows run) on the Mac. Reads only; runs no model and no program.
Checks: manifest hashes; repeat passes differ only in durationMs; per-configuration summary vs the archived GPU runs;
per-task execution rates; oracle verdicts on byte-identical programs; self-verdicts on identical program hashes."""
import collections, hashlib, json
from pathlib import Path
HERE = Path(__file__).resolve().parent; X = HERE.parent / 'release'; A = HERE.parents[1]  # experiments/rq-c
PAIRS = {'template-a': 'template-gpu/A', 'template-b': 'template-gpu/B', 'second-family': 'family-gpu'}
L = lambda p: json.loads(Path(p).read_text(encoding='utf-8-sig'))
rows = lambda p: [json.loads(l) for l in open(p, encoding='utf-8-sig')]
out = {}
m = L(X / 'delivery-manifest.json'); bad = []
for it in m['files']:
    b = (X / it['path']).read_bytes()
    if hashlib.sha256(b).hexdigest() != it['sha256'] or len(b) != it['bytes']: bad.append(it['path'])
present = {str(p.relative_to(X)) for p in X.rglob('*') if p.is_file()}
out['manifest'] = dict(listed=len(m['files']), mismatched=bad, unlisted=sorted(present - {i['path'] for i in m['files']}),
                       exportedFiles=len(present), sha256=hashlib.sha256((X / 'delivery-manifest.json').read_bytes()).hexdigest())
rep = {}
for g in PAIRS:
    base = rows(X / f'qualification/{g}/pass-01/rq-c-s42-ollama-t5-r5/trials.jsonl'); keys = set()
    for k in range(2, 6):
        for a, b in zip(base, rows(X / f'qualification/{g}/pass-0{k}/rq-c-s42-ollama-t5-r5/trials.jsonl')):
            keys |= {f for f in a if a[f] != b.get(f)}
    rep[g] = dict(trialsPerPass=len(base), fieldsDifferingAcrossPasses=sorted(keys))
out['repeats'] = rep
cmp = {}
for r, a in PAIRS.items():
    x = L(X / f'regeneration/{r}/rq-c-s42-ollama-t30-r5/summary.json'); y = L(A / a / 'rq-c-s42-ollama-t30-r5/summary.json')
    rt, at = rows(X / f'regeneration/{r}/rq-c-s42-ollama-t30-r5/trials.jsonl'), rows(A / a / 'rq-c-s42-ollama-t30-r5/trials.jsonl')
    def rate(ts):
        c = collections.defaultdict(lambda: [0, 0])
        for t in ts: c[t['taskId']][0] += bool(t['execOk']); c[t['taskId']][1] += 1
        return c
    ra, rr = rate(at), rate(rt)
    arch = {}
    for c in rows(A / a / 'rq-c-s42-ollama-t30-r5/candidates.jsonl'): arch.setdefault(c['code'], set()).add(c['execOk'])
    same = conflict = 0
    for c in rows(X / f'regeneration/{r}/rq-c-s42-ollama-t30-r5/candidates.jsonl'):
        if c['code'] in arch: same += arch[c['code']] == {c['execOk']}; conflict += arch[c['code']] != {c['execOk']}
    def sv(ts):
        d = collections.defaultdict(collections.Counter)
        for t in ts:
            if t.get('selfVerdict') is not None: d[t['codeHash']][t['selfVerdict']] += 1
        return d
    sa, sr = sv(at), sv(rt); sh = set(sa) & set(sr)
    cmp[r] = dict(archive=f'experiments/rq-c/{a}', model=x['sampling']['model'],
                  ollama=[y['sampling'].get('ollamaVersion'), x['sampling'].get('ollamaVersion')],
                  digestSame=x['sampling'].get('modelDigest') == y['sampling'].get('modelDigest'),
                  nSkills=[y['nSkills'], x['nSkills']],
                  precision={f"sv{int(t['selfVerificationEnabled'])}-ef{int(t['envFeedbackEnabled'])}": [round(u['precision'], 4), round(t['precision'], 4)] for u, t in zip(y['table'], x['table'])},
                  diagnostics={k: [y['diagnostics'].get(k), x['diagnostics'].get(k)] for k in ('n', 'agreement', 'falseDiscoveryRate', 'falseOmissionRate')},
                  tasksWithExecRateChangeOver3pts={k: [f'{ra[k][0]}/{ra[k][1]}', f'{rr[k][0]}/{rr[k][1]}'] for k in ra if abs(ra[k][0] / ra[k][1] - rr[k][0] / max(rr[k][1], 1)) > 0.03},
                  oracleOnIdenticalPrograms=dict(sameVerdict=same, conflicting=conflict),
                  selfVerdictOnIdenticalPrograms=dict(programs=len(sh), sameMajority=sum(sa[h].most_common(1)[0][0] == sr[h].most_common(1)[0][0] for h in sh)))
out['regenerationVsArchive'] = cmp
out['outcome'] = L(X / 'outcome.json')
(HERE / 'verification.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
print(json.dumps({k: v for k, v in out.items() if k != 'regenerationVsArchive'}, ensure_ascii=False)[:900])
