#!/usr/bin/env python3
"""Audit actual retrieved data, process order, same-database continuation and suffix evidence."""
import argparse
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path

from audit_retrieval_suffix import verify_suffix, require

IDS = ['H', 'I1', 'I2', 'I3', 'I4', 'I5', 'I6', 'I7', 'I8', 'S1']


def sha(data): return hashlib.sha256(data).hexdigest()


def raw(root, rel):
    path = root / rel
    return path.read_bytes() if path.is_file() else gzip.decompress(path.with_suffix(path.suffix + '.gz').read_bytes())


def load(root, rel): return json.loads(raw(root, rel))


def lines(root, rel): return [json.loads(s) for s in raw(root, rel).splitlines()]


def timestamp(value): return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))


def verify_control(control, selection):
    require(len(control) == 3, 'missing routing control')
    paths = []
    for i, row in enumerate(control):
        require(row['write']['status'] == 201 and row['read']['status'] == 200 and row['gatewayAttempts'] == 0, 'control actual API absent')
        items = row['read']['response']['items']
        require(len(items) == 1 and items[0]['content'] == row['write']['request']['content'], 'control returned content')
        cue = json.loads(items[0]['content'].split(' ', 1)[1])
        selected = selection['unusable' if i == 2 else 'usable']
        route = row['route']
        require(cue['caseId'] == 'control' and cue['taskId'] == selected['taskId'] and cue['codeSha256'] == selected['codeSha256'], 'control cue')
        require(route['program']['code'] == selected['code'] and route['memoryContentSha256'] == sha(items[0]['content'].encode()), 'control dataflow')
        require(cue['requestedAct'] == ('celebrate' if i == 1 else 'comfort'), 'control act')
        require(row['execution']['ok'] is (i != 2) and row['mappedAct'] == ['comfort', 'celebrate', 'inform'][i], 'control executable or mapped result')
        if i:
            require(row['deletePrevious']['status'] == 200 and row['deletePrevious']['path'].endswith(control[i-1]['read']['response']['items'][0]['id']), 'owned previous cue not deleted')
        paths.append(row['read']['path'])
    require(len(set(paths)) == 1, 'control query changed')


def verify(root, repo):
    receipt = load(root, 'receipt.json')
    identity = load(root, 'input-identities.json')
    selection = load(root, 'selection.json')
    for rel, expected in selection['sources'].items():
        require(sha((repo / rel).read_bytes()) == expected, 'fixed input drift: ' + rel)
    require(receipt['status'] == 'PASS_RETRIEVAL_LED_DEVELOPMENT_ONLY' and receipt['codeCommit'] == identity['codeCommit'], 'run status/identity')
    require(receipt['completedCases'] == 10 and receipt['heldOutCases'] == 0 and receipt['modelRequests'] == 0 and receipt['formalHardwareQualification'] is False, 'scope/denominator')
    rows = load(root, 'cases.json')
    require([r['caseId'] for r in rows] == IDS, 'missing/reordered case')
    journal = lines(root, 'journal.jsonl')
    require([j['sequence'] for j in journal] == list(range(1, len(journal)+1)), 'journal sequence')
    require(all(b['monotonicTicks'] > a['monotonicTicks'] and timestamp(b['utc']) >= timestamp(a['utc']) for a, b in zip(journal, journal[1:])), 'journal time reversal')
    require(len({j['frequency'] for j in journal}) == 1 and journal[0]['frequency'] > 0, 'clock frequency')

    def phase(case, name):
        found = [j for j in journal if j['caseId'] == case and j['phase'] == name]
        require(len(found) == 1, 'missing/duplicate phase ' + case + ':' + name)
        return found[0]

    ready = phase('batch', 'renderer.ready')
    closed = phase('batch', 'renderer.closed')
    prefix_done = phase('batch', 'prefixes.complete')
    require(prefix_done['sequence'] < ready['sequence'] < closed['sequence'], 'batch stage order')
    require(timestamp(receipt['phases']['renderer']['startedAt']) > timestamp(prefix_done['utc']), 'renderer started before retrieval/execution prefixes')
    require(timestamp(receipt['phases']['renderer']['endedAt']) <= timestamp(closed['utc']), 'suffix before actual client exit')
    prepared = load(root, 'prepared.json')
    require(sha(raw(root, 'prepared.json')) == load(root, 'renderer-request.json')['preparedSha256'], 'prefix handoff hash')
    require([r['caseId'] for r in prepared] == IDS, 'prefix handoff incomplete')
    state = raw(root, 'client/aijade-render-state.jsonl')
    state_lines = state.splitlines(keepends=True)
    header = json.loads(state_lines[0]); end = json.loads(state_lines[-1])
    require(end['complete'] is True and end['lines'] == len(state_lines)-1 and end['sha256'] == sha(b''.join(state_lines[:-1])), 'render file not sealed')
    require(header['presented_frame_observed'] is False and header['pmx_sha256'] == identity['modelSha256'], 'renderer scope/asset')
    require(load(root, 'renderer-closed.json')['stateSha256'] == sha(state) == load(root, 'manifest.json')['file_sha256'], 'closed file identity')
    registry = lines(root, 'registry.jsonl')
    require(registry[0]['session_id'] == header['session_id'] and registry[0]['renderer_context_id'] == header['renderer_context_id'], 'registry identity')
    require([v['intent_id'] for v in registry[1:]] == [r['prepared']['intentId'] for r in rows], 'registration order')
    pre = {f"{header['renderer_context_id']}:{r['seq']}": r for r in map(json.loads, state_lines[1:-1]) if r.get('packet_type') == 'RenderStatePacket'}
    databases = []
    for row in rows:
        case = row['caseId']; p = row['prepared']
        names = ['database.open', 'memory.write.begin', 'memory.write.end', 'memory.read.begin', 'memory.read.end', 'route.selected',
                 'execution.begin', 'execution.end', 'intent.mapped', 'intent.registered', 'intent.sent', 'database.resumed',
                 'import.begin', 'import.end', 'admission.begin', 'admission.end', 'commit.begin', 'commit.end',
                 'delivery.begin', 'delivery.end', 'round2.begin', 'round2.end', 'case.complete', 'database.disposed']
        events = [phase(case, n) for n in names]
        require(all(b['sequence'] > a['sequence'] for a, b in zip(events, events[1:])), 'case phase order: ' + case)
        require(phase(case, 'intent.mapped')['sequence'] < prefix_done['sequence'] and ready['sequence'] < phase(case, 'intent.registered')['sequence'] < phase(case, 'intent.sent')['sequence'] < closed['sequence'] < phase(case, 'database.resumed')['sequence'], 'prefix/renderer/suffix order: ' + case)
        require(phase(case, 'database.open')['detail'] == row['databaseBefore'] == row['databaseAfter'] == p['databaseBefore'] == phase(case, 'database.resumed')['detail'], 'database identity changed')
        databases.append(row['databaseBefore']['database'])
        require(len(row['databaseBefore']['token']) == 32, 'database continuity token missing')
        require(phase(case, 'memory.read.end')['detail'] == row['initialRead'] and phase(case, 'memory.write.end')['detail'] == row['initialWrite'], 'initial raw API journal binding')
        content = row['initialRead']['response']['items'][0]['content']
        require(content == row['initialWrite']['request']['content'] and content.startswith('ch7_route_' + case + ' '), 'route content not from returned memory')
        cue = json.loads(content.split(' ', 1)[1]); route = p['route']
        require(cue['caseId'] == case and cue['taskId'] == p['taskId'] and cue['codeSha256'] == p['codeSha256'], 'retrieved route/code mismatch')
        require(route['program']['code'] == p['code'] and route['program']['codeSha256'] == p['codeSha256'] and route['memoryContentSha256'] == sha(content.encode()), 'returned content hash/catalogue binding')
        require(cue['requestedAct'] == p['requestedAct'] == 'comfort', 'retrieved act not used')
        require(p['mapperInputAct'] == ('celebrate' if case == 'S1' else cue['requestedAct']), 'unrecorded semantic override')
        require(p['dispatchedAct'] == ('inform' if case in ['I4', 'I5'] else p['mapperInputAct']), 'execution fallback missing')
        require(phase(case, 'route.selected')['detail'] == route and phase(case, 'execution.end')['detail'] == p['execution'], 'route/execution journal binding')
        require(phase(case, 'intent.sent')['detail'] == p and phase(case, 'case.complete')['detail'] == row, 'sent/final raw journal binding')
        require(len(p['packets']) == 2 and all(v['trace_id'] == p['intentId'] for v in p['packets']), 'actual packet identity')
    require(len(set(databases)) == 10, 'case database isolation')
    verify_suffix(rows, selection, pre, header)
    require(all(r['qualified'] for r in rows), 'failed .NET observer')
    cleanup = load(root, 'database-cleanup.json')
    require({r['database'] for r in cleanup} == set(databases) and all(r['remaining'] == 0 for r in cleanup), 'owned database cleanup incomplete')
    telemetry = lines(root, 'telemetry.jsonl')
    require(bool(telemetry) and receipt['wallSeconds'] <= 1200, 'resource record missing')
    require(max(t['rssBytes'] for t in telemetry) == receipt['peak']['rssBytes'] and min(t['availableBytes'] for t in telemetry) == receipt['peak']['minAvailableBytes'], 'telemetry extrema differ')
    timers = {}
    for t in telemetry:
        for key, crossed in [('rss', t['rssBytes'] > 2*1024**3), ('available', t['availableBytes'] < 3*1024**3), ('swap', t['swapIncreaseBytes'] > 1024**3)]:
            if not crossed: timers.pop(key, None)
            else:
                timers.setdefault(key, t['elapsedSeconds'])
                require(t['elapsedSeconds']-timers[key] < 30, 'unreported sustained resource stop')
    return dict(status='PASS', retrievalLedDevelopmentCases=10, promotions=sum(r['final']['specs'] for r in rows),
                secondRoundSandboxExecutions=sum(r['round2']['executed'] for r in rows), databasesContinued=10,
                heldOutCases=0, C1Comparisons=0, modelRequests=0, semanticCounterexamplesAdmitted=1,
                interpretation='Known-case operational dataflow qualification; no causal effect estimate, independent human review or formal hardware qualification.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.root, args.repo), indent=2))
