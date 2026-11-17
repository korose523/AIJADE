"""Read-only post-stop costs; never import or call an observer, helper or API."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter, defaultdict
import base64
import hashlib
import json
import math
import statistics
import psutil

BASE = Path('/Volumes/Untitled/AIJADE')
C = BASE / '.research/runs/ch7-lifecycle-20261117'
R = BASE / '.runtime/posix/runs/ch7-mac-lifecycle-20261117/qualification-01'
W = BASE / '.runtime/posix/research/ch7-lifecycle-20261117/worktree'
Q = '0c42cc29c64730131466af6b079a900005713cba'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def stats(values):
    values = sorted(values)
    if not values:
        return {'n': 0, 'minimum': None, 'median': None, 'p95': None, 'maximum': None, 'mean': None}
    def percentile(p):
        index = (len(values) - 1) * p
        low = math.floor(index)
        return values[low] + (values[math.ceil(index)] - values[low]) * (index - low)
    return dict(n=len(values), minimum=values[0], median=percentile(.5), p95=percentile(.95),
                maximum=values[-1], mean=statistics.fmean(values))


def correlation(x, y):
    if len(x) != len(y) or len(x) < 2:
        return None
    a, b = statistics.fmean(x), statistics.fmean(y)
    numerator = sum((v - a) * (w - b) for v, w in zip(x, y))
    denominator = math.sqrt(sum((v - a) ** 2 for v in x) * sum((w - b) ** 2 for w in y))
    return numerator / denominator if denominator else None


receipt = json.loads((R / 'receipt.json').read_text())
phase = json.loads((R / 'preflight-continuity.json').read_text())
assert receipt['implementationCommit'] == Q and receipt['status'] == 'STOPPED_PRE_BLOCK'
raw_journal = (R / 'lifecycle-journal.jsonl').read_bytes()
events = [json.loads(line) for line in raw_journal.splitlines()]
previous = '0' * 64
leases = {}
for index, event in enumerate(events, 1):
    assert event['seq'] == index and event['previousSha256'] == previous
    assert event['sourceCommit'] == Q
    assert hashlib.sha256(canonical({k: v for k, v in event.items() if k != 'sha256'})).hexdigest() == event['sha256']
    previous = event['sha256']
    if event['event'] in ('FINITE_REGISTER', 'CONTROLLER_REGISTER'):
        leases[event['data']['leaseId']] = {'register': event}
    elif event['event'] in ('RELEASE', 'WAIT'):
        leases[event['data']['leaseId']][event['event'].lower()] = event
assert sha(R / 'lifecycle-journal.jsonl') == receipt['lifecycleJournalSha256']
phase_events = [json.loads(line) for line in (R / 'phase-events.jsonl').read_bytes().splitlines()]
written = {e['sampleId']: e for e in phase_events if e['event'] == 'sample-written'}
origin = phase['schedule']['originMonotonic']
deadline = origin + 600
lsof_command = ['/usr/sbin/lsof', '-nP', '-iTCP:11434', '-sTCP:LISTEN', '-FpfPtTn']
lsof_sha = hashlib.sha256(canonical(lsof_command)).hexdigest()
finite = [v for v in leases.values() if v['register']['event'] == 'FINITE_REGISTER']
for lease in finite:
    assert lease['release']['data']['leaseId'] == lease['register']['data']['leaseId']
    assert lease['wait']['data']['identity'] == lease['register']['data']['identity']
    assert lease['wait']['data']['waitSource'] == 'Popen.wait'
    assert lease['wait']['data']['exitCode'] == 0

rows = []
with (R / 'settling/telemetry.jsonl').open() as stream:
    for raw_index, line in enumerate(stream):
        raw = json.loads(line)
        observation = raw['processObservation']
        event = written[raw['sampleId']]
        assert raw['globalIndex'] == raw_index
        assert event['globalIndex'] == raw_index
        assert raw['sampleId'] == observation['sampleId']
        start, completed = raw['monotonicSeconds'], raw['observationCompletedMonotonic']
        before, after = [observation['evidence'][p] for p in ('before', 'after')]
        native = [frame['processGraph']['nativeCensus'] for frame in (before, after)]
        native_payloads = []
        for item in native:
            body = base64.b64decode(item['stdoutBase64'], validate=True)
            assert hashlib.sha256(body).hexdigest() == item['stdoutSha256']
            assert len(body) == item['stdoutBytes']
            native_payloads.append(json.loads(body))
        workers = [lease for lease in finite if observation['startedMonotonic'] <=
                   lease['register']['data']['readyMonotonic'] <= observation['finishedMonotonic']]
        natives = [v for v in workers if v['register']['data']['stageId'] == 'observer-native-census']
        lsofs = [v for v in workers if v['register']['data']['commandSha256'] == lsof_sha]
        assert len(workers) == 4 and len(natives) == len(lsofs) == 2
        assert {v['register']['data']['leaseId'] for v in natives} == {v['managedLeaseId'] for v in native}
        cost = dict(
            captureSeconds=completed - start,
            guardWholeSeconds=observation['finishedMonotonic'] - observation['startedMonotonic'],
            captureLockHeldSeconds=observation['coordinationLock']['releasedMonotonic'] - observation['coordinationLock']['acquiredMonotonic'],
            captureLockWaitSeconds=observation['coordinationLock']['waitSeconds'],
            guardAfterLockSeconds=observation['finishedMonotonic'] - observation['coordinationLock']['releasedMonotonic'],
            streamValidatorSeconds=raw['validatorCompletedMonotonic'] - raw['validatorStartedMonotonic'],
            rawWriterSeconds=event['writerCompletedMonotonic'] - event['writerStartedMonotonic'],
            serviceThroughRawWriteSeconds=event['writerCompletedMonotonic'] - start,
            startLatenessSeconds=start - raw['globalScheduledMonotonic'],
            nativeWrapperSumSeconds=sum(n['durationSeconds'] for n in native),
            nativeKernelInternalSumSeconds=sum((p['finishedMonotonicNs'] - p['startedMonotonicNs']) / 1e9 for p in native_payloads),
            apiSeconds=observation['evidence']['api']['durationSeconds'],
            beforeGraphSeconds=before['graphCompletedMonotonic'] - before['graphStartedMonotonic'],
            afterGraphSeconds=after['graphCompletedMonotonic'] - after['graphStartedMonotonic'],
            betweenGraphsExcludingApiSeconds=after['graphStartedMonotonic'] - before['graphCompletedMonotonic'] - observation['evidence']['api']['durationSeconds'],
            afterGraphToUnlockSeconds=observation['coordinationLock']['releasedMonotonic'] - after['graphCompletedMonotonic'],
            allWorkersReadyToRegisterSumSeconds=sum(v['register']['monotonicSeconds'] - v['register']['data']['readyMonotonic'] for v in workers),
            allWorkersRegisterToReleaseSumSeconds=sum(v['release']['monotonicSeconds'] - v['register']['monotonicSeconds'] for v in workers),
            allWorkersReapToWaitEventSumSeconds=sum(v['wait']['monotonicSeconds'] - v['wait']['data']['reapedMonotonic'] for v in workers),
            nativeReadyToReapedSumSeconds=sum(v['wait']['data']['reapedMonotonic'] - v['register']['data']['readyMonotonic'] for v in natives),
            lsofReadyToReapedSumSeconds=sum(v['wait']['data']['reapedMonotonic'] - v['register']['data']['readyMonotonic'] for v in lsofs),
        )
        cost['nativeWrapperMinusKernelSumSeconds'] = cost['nativeWrapperSumSeconds'] - cost['nativeKernelInternalSumSeconds']
        rows.append(dict(index=raw_index, sampleId=raw['sampleId'], actualStartSeconds=start - origin,
            nominalStartSeconds=raw['scheduledSeconds'], completedSeconds=completed - origin,
            processGuardRecordedStatus=observation['status'], processBlockers=observation.get('blockers'),
            streamStatus=raw['streamValidationStatus'], streamError=raw.get('streamValidationError'),
            journalBytes=observation['lifecycle']['journalBytes'], journalEvents=observation['lifecycle']['lastSequence'],
            rawLineBytes=len(line.encode()), eventWriterCompletedMonotonic=event['writerCompletedMonotonic'],
            cost=cost, nativeLeaseIds=[v['managedLeaseId'] for v in native]))

assert len(rows) == 294
for first, second in zip(rows, rows[1:]):
    first['cost']['startToNextStartSeconds'] = second['actualStartSeconds'] - first['actualStartSeconds']
    first['cost']['eventCallbackAndTailToNextStartUpperBoundSeconds'] = origin + second['actualStartSeconds'] - first['eventWriterCompletedMonotonic']
rows[-1]['cost']['lastEventCallbackAndTailToRefusalSeconds'] = phase['refusedAtMonotonic'] - rows[-1]['eventWriterCompletedMonotonic']
metrics = sorted(set().union(*(row['cost'] for row in rows)))
summaries = {name: stats([row['cost'][name] for row in rows if name in row['cost']]) for name in metrics}
accepted = [row for row in rows if row['streamStatus'] == 'PASS']
validator_accepted = stats([row['cost']['streamValidatorSeconds'] for row in accepted])
quarters = []
for i in range(4):
    group = rows[len(rows) * i // 4:len(rows) * (i + 1) // 4]
    quarters.append(dict(quarter=i + 1, firstIndex=group[0]['index'], lastIndex=group[-1]['index'],
        journalBytesFirst=group[0]['journalBytes'], journalBytesLast=group[-1]['journalBytes'],
        metrics={name: stats([row['cost'][name] for row in group if name in row['cost']]) for name in metrics}))

identities = [lease['register']['data']['identity'] for lease in leases.values()]
identity_checks = []
for identity in identities:
    check = dict(identity=identity)
    try:
        process = psutil.Process(identity['pid'])
        birth = round(process.create_time() * 1000000)
        if birth != identity['createTimeMicros']:
            check.update(status='OLD_IDENTITY_ABSENT_PID_REUSED', observedCreateTimeMicros=birth)
        else:
            status = process.status()
            birth_after = round(process.create_time() * 1000000)
            check.update(status='OLD_IDENTITY_PRESENT' if birth_after == birth else 'IDENTITY_CHANGED_DURING_QUERY',
                         observedCreateTimeMicros=birth_after, kernelStatus=status)
    except psutil.NoSuchProcess:
        check['status'] = 'OLD_IDENTITY_ABSENT_NO_SUCH_PROCESS'
    except (psutil.AccessDenied, OSError) as error:
        check.update(status='UNKNOWN', errorClass=type(error).__name__)
    identity_checks.append(check)

source_paths = sorted(p for p in R.rglob('*') if p.is_file())
source_paths += [C / n for n in ('qualification-single-launch.json', 'qualification-single-launch.terminal.json')]
source_paths += [W / n for n in receipt['observerSources']]
assert all(sha(W / name) == digest for name, digest in receipt['observerSources'].items())
sources = [dict(path=str(p), bytes=p.stat().st_size, sha256=sha(p)) for p in source_paths]
trace_path = C / 'post-stop-lifecycle-cost-samples.jsonl'
assert not trace_path.exists()
trace_path.write_bytes(b''.join(canonical(row) + b'\n' for row in rows))
missing = list(range(len(rows), 300))
report = dict(
    schema='aijade.lifecycle.post-stop-cost-analysis.v1', checkedAt=datetime.now(timezone.utc).isoformat(),
    status='TERMINAL_REFUSAL_DESCRIBED_NO_RETRY', implementationCommit=Q,
    buildFreezeCommit=receipt['buildFreezeCommit'], sourceFiles=sources,
    sampleMetricTrace=dict(path=str(trace_path), sha256=sha(trace_path), rows=len(rows)),
    population=dict(rawSamples=len(rows), streamAcceptedSamples=len(accepted),
        recordedProcessGuardStatuses=dict(Counter(row['processGuardRecordedStatus'] for row in rows)),
        streamStatuses=dict(Counter(row['streamStatus'] for row in rows)),
        lifecycleEvents=len(events), eventKinds=dict(Counter(e['event'] for e in events)),
        registeredFinite=len(finite), registeredNative=588, registeredLsofInsideSamples=588,
        otherPreflightFinite=30, allFiniteHaveActualWaitZero=True),
    schedule=dict(originMonotonic=origin, fixedDeadlineMonotonic=deadline, expectedSamples=300,
        actualContiguousIndices=list(range(len(rows))), unvisitedRequiredIndices=missing,
        unvisitedNominalSeconds=[2 * i for i in missing],
        firstActualSeconds=rows[0]['actualStartSeconds'], lastActualSeconds=rows[-1]['actualStartSeconds'],
        lastNominalSeconds=rows[-1]['nominalStartSeconds'], lastLatenessSeconds=rows[-1]['cost']['startLatenessSeconds'],
        lastRawCompletedSeconds=rows[-1]['completedSeconds'], lastDeadlineOvershootSeconds=rows[-1]['completedSeconds'] - 600,
        maximumStartGapSeconds=max(b['actualStartSeconds'] - a['actualStartSeconds'] for a, b in zip(rows, rows[1:])),
        serviceThroughRawWriteAboveTwoSeconds=sum(row['cost']['serviceThroughRawWriteSeconds'] > 2 for row in rows),
        explanation='No index-skipping branch: source loops all 300 local indices with absolute origin+index*2 targets. Actual starts accumulated lateness. It stopped while writing index293 after its raw completion exceeded the fixed600 deadline; indices294..299 were never invoked, not selectively dropped.'),
    refusal=dict(processGuard='All294 recorded inner process guard statuses are PASS; cost analysis does not rerun guard or independently certify their evidence.',
        phase='Last raw completed600.336714976s; phase source tests completion against600s before calling stream validator. Last stream REFUSED therefore represents phase deadline, not a process guard failure.',
        guardWholeOver2_5Seconds=sum(row['cost']['guardWholeSeconds'] > 2.5 for row in rows),
        admissionStarted=False, completedBlocks=0, completedConditionRows=0,
        unattemptedConditionRows=len(receipt['unattemptedCaseIds']), modelRequests=receipt['modelRequests'],
        heldoutComparisonRun=False, formalQualification=False),
    costDistributions=summaries, acceptedStreamValidatorSeconds=validator_accepted, quarters=quarters,
    descriptiveCorrelationsWithJournalBytes={name:correlation([r['journalBytes'] for r in rows],
        [r['cost'][name] for r in rows]) for name in metrics if all(name in r['cost'] for r in rows)},
    journalGrowth=dict(firstPrefixBytes=rows[0]['journalBytes'], lastPrefixBytes=rows[-1]['journalBytes'],
        archiveBytes=len(raw_journal), firstPrefixEvents=rows[0]['journalEvents'], lastPrefixEvents=rows[-1]['journalEvents'],
        perSampleAddedEvents=stats([b['journalEvents'] - a['journalEvents'] for a,b in zip(rows,rows[1:])])),
    exactIdentityPostStopCheck=dict(checkedAt=datetime.now(timezone.utc).isoformat(),
        scope='Only receipt/controller and registered finite PID+creation-time identities; no census, command/environment reads, signals or service interactions.',
        summary=dict(Counter(c['status'] for c in identity_checks)), identities=identity_checks),
    measurementLimits=[
        'Single stopped observational run; correlations with monotonically growing journal cannot establish causal cost attribution or general performance.',
        'No event callback completion timestamp is recorded for each accepted event. The next-start tail is an upper bound including event write, bookkeeping and any sleep; not event-write latency.',
        'Ready-to-register/release/reap gaps are recorded, but no successful-launch attempt-start event exists. Pre-ready spawn/shim overhead cannot be isolated.',
        'Native wrapper minus C internal duration includes multiple launch/gate/journal/transport/cleanup costs; it is not a direct measurement of ready-shim overhead.',
        'C clock is used only for its own duration, never compared by absolute origin with Python monotonic.',
        'Between-graph and graph-to-unlock residuals mix daemon identity/hash, lsof, journal projection and parsing/bookkeeping; no individual uninstrumented component is assigned causal cost.',
        'Post-stop PID identity queries only describe the exact query time; no claims about unregistered descendants or unknown process histories.',
    ],
    futureWorkNotRun=[
        'Before another separately approved qualification, benchmark complete360tick-equivalent service costs including raw/event writes and both online validators, against unchanged fixed phase and sample bounds.',
        'Version and freeze a bounded incremental online validation path with exact prefix mutation/truncation/rewind controls, while retaining full independent offline replay. This is a prospective design, not applied here.',
        'Add explicit launch-attempt-start and event-callback-completed timing receipts to separate pre-ready and event durability costs without changing original recorded timestamps.',
        'Measure remaining identity/hash/listener and journal-projection costs before choosing optimizations; require source-bound negative controls for every proposed cache.',
        'Keep absolute schedule, population, coverage and phase deadline as separate gates; never rescue this terminal run by extending600s, dropping six indices, relabeling process PASS as admission, or constructing heldout cases.',
    ],
    operations=dict(modifiedWorktree=False, newObserverCalls=0, newNativeCalls=0, newApiCalls=0,
        newModelCalls=0, newRendererCalls=0, newCases=0, newWindowAttempts=0, signalsSent=0))
out = C / 'post-stop-lifecycle-cost-analysis.json'
assert not out.exists()
out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps(dict(path=str(out),sha256=sha(out),population=report['population'],schedule=report['schedule'],
    identitySummary=report['exactIdentityPostStopCheck']['summary'],costDistributions=summaries,
    firstAndLastQuarter=[quarters[0],quarters[-1]]), indent=2))
