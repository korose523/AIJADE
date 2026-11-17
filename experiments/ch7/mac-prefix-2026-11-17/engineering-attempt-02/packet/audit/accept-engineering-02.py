"""Bind completed engineering evidence without granting scientific qualification."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, subprocess

B = Path('/Volumes/Untitled/AIJADE')
C = Path(__file__).parent
W = B/'.runtime/posix/research/ch7-prefix-20261117/worktree'
R = B/'.runtime/posix/runs/ch7-prefix-20261117/engineering-02'
sha = lambda raw: hashlib.sha256(raw).hexdigest()
read = lambda path: json.loads(Path(path).read_bytes())
file_sha = lambda path: sha(Path(path).read_bytes())

def bind(path):
    path = Path(path)
    return dict(path=str(path), sha256=file_sha(path), sizeBytes=path.stat().st_size)

target = C/'analysis/engineering02-acceptance.json'
assert not target.exists()
audit_path = C/'analysis/independent-equal-load-audit-02.json'
assert file_sha(audit_path) == 'c81eb6e288b0b92745b3dacbe20df53651b86629382c4458a550b9c1cc21df01'
audit = read(audit_path)
assert audit['status'] == 'ENGINEERING_EQUAL_LOAD_RAW_AUDIT_PASS_NOT_QUALIFIED'
assert audit['rawReplay'] == dict(samples=362, guardDecisions={'PASS':362}, nativeCaptures=724,
                                scopes=1, fullReplayErrors=[])
assert audit['managedTasks'] == dict(git=30,native=724,listener=724,finite=1478,actualParentWaitZero=1478)
assert audit['continuity']['status'] == 'CONTINUITY_RAW_AUDIT_PASS'
assert audit['continuity']['samples'] == 360
assert audit['tailRuntimeEvidenceAudit']['status'] == 'LIFECYCLE_RAW_AUDIT_PASS'
assert audit['tailRuntimeEvidenceAudit']['events'] == 4437
assert audit['tailRuntimeEvidenceAudit']['cleanupAccepted'] is True
assert audit['lifecycleJournalStable'] is True
for name, item in audit['inputFiles'].items():
    path = R/name
    assert file_sha(path) == item['sha256'] and path.stat().st_size == item['sizeBytes']
for item in audit['sourceFiles']:
    path = W/item['path']
    assert file_sha(path) == item['sha256']

passport_path = C/'engineering-02-passport.json'
assert file_sha(passport_path) == '9475830e6973bbb1e81c508505898c3cc24e340816dfdaa83dac2c44d73c0f22'
passport = read(passport_path)
publication = read(C/'engineering02-freeze-publication.json')
assert publication['engineeringFreezeCommit'] == '8cc46d5202f183dfab0d0edb2f523e637d705bc2'
assert publication['passportSha256'] == file_sha(passport_path)
assert passport_path.read_bytes() == (R/'engineering-passport.json').read_bytes()
assert audit['sourceCommit'] == passport['sourceCommit'] == '51cf34be49a6ac955481d89e2a2691f3c7c981c5'

launch_path, terminal_path = C/'engineering-02-launch.json', C/'engineering-02-launch.terminal.json'
launch, terminal = read(launch_path), read(terminal_path)
assert terminal['status'] == 'ENGINEERING_CONTROLLER_REPORTED_PASS_PENDING_INDEPENDENT_REPLAY'
assert terminal['launchRecordSha256'] == file_sha(launch_path)
assert terminal['logSha256'] == file_sha(C/'engineering-02-launch.log')
assert terminal['sourceCommit'] == launch['sourceCommit'] == passport['sourceCommit']
assert terminal['passportSha256'] == launch['passportSha256'] == file_sha(passport_path)
assert terminal['launcherSha256'] == launch['launcherSha256'] == passport['launcherSha256'] == file_sha(C/'launch_equal_load_02.py')
assert terminal['controllerProcess'] == launch['controllerProcess']
assert terminal['parentProcess'] == launch['parentProcess']
controller = terminal['controllerProcess']
assert controller['parentPid'] == terminal['parentProcess']['pid']
assert {k:controller[k] for k in audit['controllerIdentity']} == audit['controllerIdentity']
assert launch['controllerPidFromPopen'] == terminal['controllerPidFromPopen'] == controller['pid']
assert terminal['actualParentWaitSource'] == 'Popen.wait' and len(terminal['actualParentWaits']) == 1
wait = terminal['actualParentWaits'][0]
assert wait['source'] == 'Popen.wait' and type(wait['exitCode']) is int and wait['exitCode'] == 0
assert wait['timedOut'] is False and wait['timeoutSeconds'] == 850
assert terminal['controllerExitCode'] == 0 and terminal['watchdogTimedOut'] is False
assert terminal['watchdogActions'] == terminal['errors'] == [] and terminal['automaticRetries'] == 0
assert terminal['runnerReport']['sha256'] == file_sha(R/'receipt.json')
assert terminal['runnerReport']['sizeBytes'] == (R/'receipt.json').stat().st_size
assert terminal['runnerReport']['tailThreadJoined'] is True and terminal['runnerReport']['lifecycleJournalStable'] is True
for key in ('scientificAcceptance','qualificationStarted','backendQualified','scientificAdmission',
            'formalHardwareQualification','independentHumanReview','authorApproval','heldoutComparisonComplete',
            'currentProductInheritsResearchQualification','seedConstructed','qualificationInvokedByLauncher',
            'rendererInvokedByLauncher','modelInvokedByLauncher'):
    assert launch[key] is False and terminal[key] is False
assert terminal['independentEngineeringReplayAccepted'] is False # immutable original, not rewritten

review_path = C/'analysis/engineering02-parent-and-cost-review.json'
review = read(review_path)
assert file_sha(review_path) == '05ff16b3c4bb7bbd179a125289a42f3119541dabc9feda89a621aaef1ce07569'
assert review['status'] == 'PARENT_BINDING_AND_RECORDED_BUDGET_REVIEW_PASS_ENGINEERING_ONLY'
assert review['parentBindingAccepted'] is True
activity_path = C/'papers/readiness-classification-review.json'
activity = read(activity_path)
start, end, stamp = (datetime.fromisoformat(s.replace('Z','+00:00')) for s in
                    (launch['startedAt'], terminal['finishedAt'], activity['checkedAt']))
assert start < stamp < end

value = dict(schema='aijade.ch7.equal-load-engineering-acceptance.v1',
    status='FULL_EQUAL_LOAD_ENGINEERING_ACCEPTED_NOT_BACKEND_QUALIFIED',
    acceptedAt=datetime.now(timezone.utc).isoformat(), sourceCommit=passport['sourceCommit'],
    prospectiveEngineeringFreezeCommit=publication['engineeringFreezeCommit'],
    passportSha256=file_sha(passport_path), independentEngineeringReplayAccepted=True,
    evidence=dict(rawAudit=bind(audit_path), fullRawReplay=bind(Path(audit['fullRawReplayCheckpoint']['path'])),
        parentLaunch=bind(launch_path), parentTerminal=bind(terminal_path), parentIndependentReview=bind(review_path),
        parentLog=bind(C/'engineering-02-launch.log'), runnerReport=bind(R/'receipt.json'),
        sourceBoundControls=bind(C/'all-python-controls-serial-05.json'), ci=bind(C/'engineering02-source-ci.json')),
    inputFiles=audit['inputFiles'], numbers=audit['numbers'], managedTasks=audit['managedTasks'],
    lifecycle=audit['tailRuntimeEvidenceAudit'], continuity=audit['continuity'],
    parentWaitSeconds=wait['completedMonotonic']-wait['startedMonotonic'],
    parentElapsedSeconds=terminal['elapsedSeconds'],
    incidentalActivity=dict(kind='CONCURRENT_SMALL_READ_ONLY_REVIEW_AND_REPORT_WRITE',
        report=bind(activity_path), checkedAt=activity['checkedAt'],
        liesInsideParentRun=True, relativeToParentStartSeconds=(stamp-start).total_seconds(),
        noFullyIdleHostClaim=True, causalPerformanceAttribution=False,
        frozenRestriction='No build, test, PDF, compression or extra polling worker runs during the timed window.',
        interpretation='Retained incidental read/write overlap; does not amend any budget or discard a row. '
            'No prohibited workflow was launched by this task. The whole-host activity history is not independently known.'),
    preservedRefusal=dict(sourceCommit='b5af85f7a1b5f1da3ceeda0a9c1a64393a0e3efb',
        auditSha256='04f724d851349d2c9ae608effa87aebcc5c46531cc79b8ea6445d4cfe8746098', accepted=False),
    auditScriptSha256=file_sha(Path(__file__)),
    nextScientificPlanPermitted=True, qualificationStarted=False, backendQualified=False,
    scientificAdmission=False, formalHardwareQualification=False, independentHumanReview=False,
    authorApproval=False, currentProductInheritsResearchQualification=False,
    flowBlocks=0, modelRequests=0, rendererRequests=0, freshHeldoutCases=0, seedConstructed=False,
    heldoutComparisonComplete=False, table7_3='NOT_RUN', automaticRetries=0,
    interpretation='Engineering acceptance of the complete frozen equivalent load only. '
        'A separately published prospective scientific decision is still required, then clean Q/B and '
        'one fully audited known-input qualification before any fresh seed or forty-pair comparison.')
target.write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(dict(status=value['status'],path=str(target),sha256=file_sha(target))))
