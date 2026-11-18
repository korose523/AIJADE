"""Exact public A/CF bindings for prefix-v4; never derives a seed or a case.

The publishing workflow verifies remote bytes separately. Here immutable Git
objects, complete typed audit records and the construction source closure are
checked again, including during the observed block preflight.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from finite_runtime import git_bytes, require, safe_relative

DECISION = 'mac-prefix-v4'
PREFIX = 'experiments/ch7/mac-prefix-v4-2026-11-17/'
POLICY = 'configs/research/ch7-mac-prefix-v4-process-policy.json'
PLAN = 'experiments/plans/2026-11-17-ch7-mac-prefix-v4-qualification.md'
PLAN_SHA = '7aa91508eee3e728cadd8d25f8cdd122deb9a35d06a09901e8143d1e028d9d36'
BUILD = PREFIX+'frozen-build.json'
ACCEPTANCE = PREFIX+'qualification-acceptance.json'
FREEZE = PREFIX+'construction-freeze.json'
SIDECAR = 'construction-binding.json'
KNOWN_REPEAT_SOURCE = 'experiments/ch7/known_repeat_acceptance.py'
KNOWN_REPEAT_DECISION = 'experiments/ch7/mac-known-repeats-qualification/decision.json'
KNOWN_REPEAT_BINDING_SCHEMA = 'aijade.ch7.known-repeat-construction-binding.v1'
KNOWN_REPEAT_FREEZE_SCHEMA = 'aijade.ch7.known-repeat-construction-freeze.v1'
BACKEND_FIELDS = ('modelSha256','realGodotSha256','godotWrapperSha256','sandboxProfileSha256',
    'rendererSources','preparedRenderer','binaries','buildManifestSha256','benchSha256',
    'earlierSourceFreezeSha256','databaseContainer','explicitDockerPath')
CONTROL_NAMES = ('missing-arm','duplicate-arm','retrieved-code','database-token','time-reversal','render-seal',
    'hidden-durable-rows-coherent','changed-window-rebound','changed-denominator-rebound','failure-witness-coherent',
    'replay-observation-coherent','unplanned-probe-coherent','embedded-build-revision','runtime-rebound',
    'missing-owned-lease','provider-attempt-coherent','unknown-cleanup-coherent','unknown-process-cleanup','build-hashes-rebound')
EXTRA_SOURCES = ('experiments/ch7/comparison_manifest.py','experiments/ch7/run_finite_block.py',
    'experiments/ch7/run_finite_sequence.py','experiments/ch7/launch_frozen_sequence.py',
    'experiments/ch7/finite-heldout/candidate-bank.json',
    'experiments/ch7/2026-11-12/selection.json',
    'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json',
    'experiments/plans/2026-11-12-ch7-confirmed-finite-heldout.md', PLAN, POLICY)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def unique(pairs):
        out={}
        for key,value in pairs:
            require(key not in out,'duplicate JSON key')
            out[key]=value
        return out
    return json.loads(raw,object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def exact_int(value, expected, name):
    require(type(value) is int and value==expected,'wrong typed '+name)


def full_commit(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{40}',value) is not None,'full public commit required')
    return value


def full_sha(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None,'full SHA256 required')
    return value


def typed_equal(left,right):
    """JSON identity includes types; booleans/floats cannot stand in for integers."""
    return json.dumps(left,sort_keys=True,separators=(',',':'),allow_nan=False)==json.dumps(
        right,sort_keys=True,separators=(',',':'),allow_nan=False)


def qualified_backend(identity,*,closed=False):
    """Extract only backend fields already validated by the real block auditor.

    Candidate selection is intentionally excluded: known uses the original two
    programmes, whereas the declared fresh comparison uses the eight-programme bank.
    """
    require(type(identity) is dict and all(key in identity for key in BACKEND_FIELDS),
            'complete qualified backend identity required')
    if closed:require(set(identity)==set(BACKEND_FIELDS),'closed qualified backend tuple required')
    result={key:identity[key] for key in BACKEND_FIELDS}
    for key in ('modelSha256','realGodotSha256','godotWrapperSha256','sandboxProfileSha256',
                'buildManifestSha256','benchSha256','earlierSourceFreezeSha256'):
        full_sha(result[key])
    for key in ('rendererSources','binaries'):
        values=result[key]
        require(type(values) is dict and values,'qualified backend file population missing: '+key)
        for path,value in values.items():safe_relative(path);full_sha(value)
    prepared=result['preparedRenderer']
    require(type(prepared) is dict and prepared.get('status')=='PREBUILT_NO_RUNTIME_REBUILD'
            and type(prepared.get('files')) is dict and prepared['files'],'qualified prepared renderer missing')
    for path,value in prepared['files'].items():safe_relative(path);full_sha(value)
    require(type(result['databaseContainer']) is str
            and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]*',result['databaseContainer']),
            'qualified database container identity missing')
    docker=result['explicitDockerPath']
    require(type(docker) is str and Path(docker).is_absolute() and '..' not in Path(docker).parts
            and not any(ord(c)<32 for c in docker),'qualified docker path identity missing')
    # Reject nonfinite numbers anywhere in additional prepared-renderer metadata.
    typed_equal(result,result)
    return result


def control_attempt_binding(controls,sequence_sha,block_sha):
    """Associate the unchanged nineteen-control producer with this actual attempt."""
    values=controls.get('ancestryContextFiles')
    require(type(values) is dict and values,'controls original ancestry context hashes missing')
    for path,value in values.items():
        require(type(path) is str and Path(path).is_absolute() and '..' not in Path(path).parts,
                'controls ancestry context path unsafe')
        full_sha(value)
    mothers=[Path(path) for path,value in values.items()
             if Path(path).name=='receipt.json' and value==full_sha(sequence_sha)]
    blocks=[Path(path) for path,value in values.items()
            if Path(path).name=='receipt.json' and Path(path).parent.name=='block-1'
            and value==full_sha(block_sha)]
    require(len(mothers)==len(blocks)==1 and blocks[0].parent.parent==mothers[0].parent,
            'controls belong to a different sequence/block attempt')


def public_bytes(repo,commit,path):
    return git_bytes(repo,'show',full_commit(commit)+':'+safe_relative(path))


def known_repeat_required(repo,q):
    """Recognize the successor in Q even if its decision file is missing."""
    return bool(git_bytes(repo,'--no-replace-objects','ls-tree','--name-only',full_commit(q),
                          '--',KNOWN_REPEAT_SOURCE,KNOWN_REPEAT_DECISION))


def new_decision_required(repo,q):
    """Current Q cannot evade the new gate by omitting its sidecar/arguments."""
    names=git_bytes(repo,'ls-tree','-r','--name-only',full_commit(q)).decode().splitlines()
    if POLICY not in names:
        return False
    policy=decode(public_bytes(repo,q,POLICY))
    require(policy.get('kind')=='mac-lifecycle-observed-idle-daemon-v3'
        and policy.get('executionDecision')==DECISION,'prefix policy decision changed')
    require(public_bytes(repo,q,POLICY)==(Path(repo)/POLICY).read_bytes(),'working prefix policy differs from Q')
    require(digest(public_bytes(repo,q,PLAN))==PLAN_SHA,'new construction plan is not frozen P4')
    return True


def source_paths(repo,q):
    from finite_runtime import MAC_LIFECYCLE_SOURCES
    names=git_bytes(repo,'ls-tree','-r','--name-only',full_commit(q),'--','experiments/ch7').decode().splitlines()
    finite={p for p in names if p.startswith('experiments/ch7/finite_') and '/' not in p[len('experiments/ch7/'):] and p.endswith('.py')}
    require({'experiments/ch7/finite_inputs.py','experiments/ch7/finite_validate.py',
             'experiments/ch7/finite_construction_binding.py'}<=finite,'construction dependency missing in Q')
    return set(EXTRA_SOURCES)|set(MAC_LIFECYCLE_SOURCES)|finite


def reference(repo,commit,ref):
    require(type(ref) is dict and set(ref)=={'path','sha256','sizeBytes'},'closed audit reference required')
    path=safe_relative(ref['path'])
    require(path.startswith(PREFIX),'audit reference outside the new decision prefix')
    require(type(ref['sizeBytes']) is int and ref['sizeBytes']>=0,'audit reference size type')
    raw=public_bytes(repo,commit,path)
    require(digest(raw)==full_sha(ref['sha256']) and len(raw)==ref['sizeBytes'],'public audit reference bytes differ')
    return decode(raw)


def accepted_qualification(repo,q,commit,path,expected_sha):
    require(path==ACCEPTANCE,'new acceptance canonical path required')
    raw=public_bytes(repo,commit,path)
    require(digest(raw)==full_sha(expected_sha),'qualification acceptance SHA differs')
    value=decode(raw)
    require(value.get('schema')=='aijade.ch7.prefix-qualification-acceptance.v1'
        and value.get('status')=='QUALIFIED_BEFORE_FRESH_CASE_CONSTRUCTION'
        and value.get('executionDecision')==DECISION,'complete prefix qualification acceptance required')
    require(value.get('implementationCommit')==q and value.get('executionPlanSha256')==PLAN_SHA
        and value.get('buildFreezePath')==BUILD,'acceptance Q/P4/build identity changed')
    build_raw=public_bytes(repo,value.get('buildFreezeCommit'),BUILD)
    require(digest(build_raw)==full_sha(value.get('buildManifestSha256')),'accepted build publication differs')
    build=decode(build_raw)
    require(build.get('status')=='CLEAN_COMMITTED_BUILD_FROZEN_BEFORE_QUALIFICATION'
        and build.get('commit')==q and build.get('assemblyInformationalVersion')=='0.1.0+'+q,
        'accepted build is not the actual qualified Q')
    from finite_runtime import MAC_LIFECYCLE_SOURCES
    observers={path:digest(public_bytes(repo,q,path)) for path in MAC_LIFECYCLE_SOURCES}
    require(build.get('observerSources')==observers,'accepted build has an incomplete or changed observer closure')
    for key in ('formalHardwareQualification','independentHumanReview','authorApproval',
                'heldoutComparisonComplete','seedConstructed'):
        require(value.get(key) is False,'acceptance scope inflated: '+key)
    refs=value.get('evidence')
    require(type(refs) is dict and set(refs)=={'sequenceReceipt','sequenceAudit','blockAudit','blockInputIdentities','corruptionControls'},
        'complete qualification evidence references required')
    records={key:reference(repo,commit,ref) for key,ref in refs.items()}
    sequence, audit, block, controls=(records[key] for key in ('sequenceReceipt','sequenceAudit','blockAudit','corruptionControls'))
    input_identity=records['blockInputIdentities']
    require(sequence.get('schema')=='aijade.ch7.finite-sequence-receipt.v1'
        and sequence.get('status')=='COMPLETE_FINITE_SEQUENCE_OBSERVATIONS','actual complete known sequence required')
    require(audit.get('schema')=='aijade.ch7.finite-sequence-audit.v1'
        and audit.get('status')=='FINITE_SEQUENCE_RAW_AUDIT_PASS' and audit.get('strictAccepted') is True,
        'whole-sequence raw acceptance required')
    require(block.get('status')=='FINITE_DATAFLOW_AUDIT_PASS','actual block dataflow acceptance required')
    for record in (sequence,audit,block):
        require(record.get('implementationCommit')==q and record.get('buildFreezeCommit')==value['buildFreezeCommit']
            and record.get('buildFreezePath')==BUILD,'mixed qualified Q/B in audit records')
        require(record.get('observerSources')==observers,'mixed observer source generation in qualification audits')
        exact_int(record.get('modelRequests'),0,'known model requests')
    require(input_identity.get('implementationCommit')==input_identity.get('codeCommit')==q
        and input_identity.get('repositoryCommit')==q and input_identity.get('purpose')=='qualification_only'
        and input_identity.get('buildFreezeCommit')==value['buildFreezeCommit']
        and input_identity.get('buildFreezePath')==BUILD
        and input_identity.get('executionPlanSha256')==PLAN_SHA
        and input_identity.get('observerSources')==observers,'qualified input identity Q/B/P4/sources changed')
    policy_sha=digest(public_bytes(repo,q,POLICY))
    for record in (sequence,audit,block,input_identity):
        require(record.get('processPolicyPath')==POLICY and record.get('processPolicySha256')==policy_sha
            and record.get('observerModuleSha256')==observers['experiments/ch7/mac_process_guard_v3.py'],
            'qualified record policy/source generation differs')
    require(block.get('inputIdentitiesSha256')==refs['blockInputIdentities']['sha256'],
            'block audit does not bind the actual input-identities bytes')
    backend=qualified_backend(input_identity)
    require(type(block.get('qualifiedBackend')) is dict
            and typed_equal(qualified_backend(block['qualifiedBackend'],closed=True),backend),
            'block audit qualified backend differs from actual input identity')
    require(typed_equal(backend['binaries'],build.get('files'))
            and backend['buildManifestSha256']==digest(build_raw),'qualified backend does not use the published B files')
    if 'qualifiedBackend' in value:
        require(typed_equal(qualified_backend(value['qualifiedBackend'],closed=True),backend),
                'acceptance backend differs from the audited actual input identity')
    require(sequence.get('executionPlanSha256')==PLAN_SHA and block.get('executionPlanSha256')==PLAN_SHA,
        'known raw records use a different prospective decision')
    for record in (sequence,audit):
        require(record.get('purpose')=='qualification_only' and record.get('repositoryCommit')==q,
            'qualification confused with formal I')
        require(record.get('formalHardwareQualification') is False and record.get('independentHumanReview') is False,
            'unsupported scientific approval')
    for key,count in (('plannedBlocks',1),('completedBlocks',1),('plannedPairs',10),
                      ('plannedConditionRows',20),('completedConditionRows',20)):
        exact_int(sequence.get(key),count,key)
    for key in ('inFlightCaseIds','unknownCaseIds','unattemptedCaseIds'):
        require(sequence.get(key)==[],'incomplete qualification disposition')
    # The unchanged producer adds this diagnostic only on an adverse path.
    # Match the original whole-audit predicate: absent is valid, explicit
    # unknown/nonempty values remain adverse.
    require(sequence.get('dispositionErrors',[])==[],'incomplete qualification disposition errors')
    require(sequence.get('reason') is None,'qualification still has a stop reason')
    for record in (audit,block):
        exact_int(record.get('casePairs'),10,'known case pairs')
        exact_int(record.get('measuredConditionRows'),20,'known condition rows')
        exact_int(record.get('freshFiniteHeldoutPairs'),0,'known fresh pairs')
    exact_int(audit.get('blocks'),1,'known audited blocks')
    require(audit.get('receiptSha256')==refs['sequenceReceipt']['sha256'],'audit does not bind actual sequence receipt')
    require(type(audit.get('blocksFromRaw')) is list and len(audit['blocksFromRaw'])==1,
        'missing actual audited block')
    control_attempt_binding(controls,refs['sequenceReceipt']['sha256'],audit['blocksFromRaw'][0].get('receiptSha256'))
    require(block.get('processLifecycle',{}).get('cleanupAccepted') is True,'block owned cleanup unknown')
    require(audit.get('processOwnership',{}).get('cleanupAccepted') is True,'sequence owned cleanup unknown')
    require(controls.get('status')=='PASS' and controls.get('primaryUnchanged') is True
        and controls.get('ancestryContextPrimaryUnchanged') is True,'actual controls or primary/context preservation incomplete')
    exact_int(controls.get('rejectedCorruptions'),19,'rejected corruption population')
    exact_int(controls.get('completeBaselineChecks'),20,'valid primary/copied baselines')
    rows=controls.get('controls')
    require(type(rows) is list and len(rows)==19 and
        {r.get('control') for r in rows if type(r) is dict}==set(CONTROL_NAMES)
        and all(r.get('rejected') is True and type(r.get('reason')) is str and r['reason'] for r in rows),
        'original nineteen meaningful control identities required')
    # Derived from the exact referenced input bytes, never an unvalidated top-level claim.
    return dict(value,qualifiedBackend=backend)


def verify_binding(repo,q,binding,model_sha=None):
    if known_repeat_required(repo,q) or (type(binding) is dict and binding.get('schema')==KNOWN_REPEAT_BINDING_SCHEMA):
        from known_repeat_acceptance import verify_binding as verify_known_repeats
        return verify_known_repeats(repo,q,binding,model_sha)
    require(new_decision_required(repo,q),'prefix construction requires its qualified decision')
    require(type(binding) is dict and set(binding)=={'schema','executionDecision','implementationCommit',
        'acceptancePublicationCommit','acceptanceRepositoryPath','acceptanceSha256',
        'constructionFreezePublicationCommit','constructionFreezeRepositoryPath','constructionFreezeSha256'},
        'closed published construction binding required')
    require(binding['schema']=='aijade.ch7.published-construction-binding.v1'
        and binding['executionDecision']==DECISION and binding['implementationCommit']==q,'construction binding decision/Q differs')
    acceptance=accepted_qualification(repo,q,binding['acceptancePublicationCommit'],
        binding['acceptanceRepositoryPath'],binding['acceptanceSha256'])
    require(binding['constructionFreezeRepositoryPath']==FREEZE,'new construction-freeze canonical path required')
    raw=public_bytes(repo,binding['constructionFreezePublicationCommit'],FREEZE)
    require(digest(raw)==full_sha(binding['constructionFreezeSha256']),'published construction freeze differs')
    freeze=decode(raw)
    require(freeze.get('schema')=='aijade.ch7.prefix-construction-freeze.v1'
        and freeze.get('executionDecision')==DECISION and freeze.get('constructionFreezeCommit')==q
        and freeze.get('executionPlanSha256')==PLAN_SHA
        and freeze.get('buildFreezeCommit')==acceptance['buildFreezeCommit']
        and freeze.get('buildFreezePath')==BUILD,'construction freeze Q/B/P4 identity changed')
    expected={key:binding[key] for key in ('acceptancePublicationCommit','acceptanceRepositoryPath','acceptanceSha256')}
    require(freeze.get('qualificationAcceptance')==expected,'freeze not bound to the accepted public qualification')
    earlier=datetime.fromisoformat(acceptance['acceptedAt'].replace('Z','+00:00'))
    later=datetime.fromisoformat(freeze['frozenAt'].replace('Z','+00:00'))
    require(earlier.tzinfo is not None and later.tzinfo is not None and earlier<=later,
        'construction freeze predates qualification acceptance')
    backend=qualified_backend(freeze.get('qualifiedBackend'),closed=True)
    require(typed_equal(backend,acceptance['qualifiedBackend']),
            'construction freeze changed the qualified actual backend or asset')
    require(freeze.get('modelSha256')==backend['modelSha256'],'frozen asset differs from qualified backend')
    if model_sha is not None:
        require(backend['modelSha256']==full_sha(model_sha),'frozen actual asset/model changed')
    sources=freeze.get('sources')
    require(type(sources) is dict and set(sources)==source_paths(repo,q),'complete construction/execution source closure required')
    for relative,expected_sha in sources.items():
        require(digest(public_bytes(repo,q,relative))==full_sha(expected_sha)
            and digest((Path(repo)/relative).read_bytes())==expected_sha,'construction source differs from Q: '+relative)
    bank='experiments/ch7/finite-heldout/candidate-bank.json'
    require(freeze.get('candidateBankSha256')==sources[bank],'candidate bank is not frozen')
    return freeze


def load_construction_freeze(repo,q,inputs,model_sha=None):
    """Legacy fallback is allowed only for Q that has no new decision policy."""
    path=Path(inputs)/SIDECAR
    if path.exists() or path.is_symlink():
        require(not path.is_symlink() and path.is_file(),'construction binding must be a regular file')
        return verify_binding(repo,q,decode(path.read_bytes()),model_sha)
    require(not known_repeat_required(repo,q) and not new_decision_required(repo,q),
            'new decision is missing its published construction binding')
    return decode((Path(repo)/'experiments/ch7/finite-heldout/construction-freeze.json').read_bytes())


def current_backend_before_measurement(repo, args, build, model_sha):
    import hashlib
    import json
    import os
    from pathlib import Path, PurePosixPath
    import re
    import stat

    fields = ('modelSha256','realGodotSha256','godotWrapperSha256','sandboxProfileSha256',
        'rendererSources','preparedRenderer','binaries','buildManifestSha256','benchSha256',
        'earlierSourceFreezeSha256','databaseContainer','explicitDockerPath')
    copy_ignored = {'.git', '.svn', '__pycache__'}
    source_ignored = copy_ignored | {'.godot', 'bin', 'obj'}
    observed = {}

    def require(ok, message):
        if not ok:
            raise ValueError('current backend: ' + message)

    def full_sha(value):
        require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None,
                'full SHA256 required')
        return value

    def relative(value):
        require(type(value) is str and value and '\\' not in value and ':' not in value
                and not any(ord(c) < 32 for c in value), 'unsafe relative file path')
        path = PurePosixPath(value)
        require(not path.is_absolute() and all(x not in ('', '.', '..') for x in value.split('/'))
                and path.as_posix() == value, 'noncanonical relative file path')
        return value

    def data_path(value):
        path = Path(value)
        require(path.is_absolute() and '..' not in path.parts
                and not any(ord(c) < 32 for c in str(path)), 'absolute data path required')
        for part in (path, *path.parents):
            require(not part.is_symlink(), 'linked data path is not accepted')
        return path

    def identity(item):
        return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns

    def file(path, retain=False):
        path = data_path(path)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        digest, chunks = hashlib.sha256(), []
        try:
            stream = os.fdopen(descriptor, 'rb')
        except BaseException:
            try: os.close(descriptor)
            except OSError: pass
            raise
        retained = 0
        with stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode), 'data file must be regular')
            if retain: require(before.st_size <= 16 * 1024 ** 2, 'JSON input exceeds fixed cap')
            while True:
                block = stream.read(1024 * 1024)
                if not block: break
                digest.update(block)
                if retain:
                    retained += len(block)
                    require(retained <= 16 * 1024 ** 2, 'JSON input grew beyond fixed cap')
                    chunks.append(block)
            after = os.fstat(stream.fileno())
        current = os.stat(path, follow_symlinks=False)
        require(identity(before) == identity(after) == identity(current), 'file changed during read')
        observed[path] = identity(current)
        return digest.hexdigest(), before.st_size, b''.join(chunks) if retain else None

    def decode(raw):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                require(key not in result, 'duplicate JSON key')
                result[key] = value
            return result
        return json.loads(raw, object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('current backend: nonfinite JSON')))

    def typed(left, right):
        return json.dumps(left, sort_keys=True, separators=(',', ':'), allow_nan=False) == json.dumps(
            right, sort_keys=True, separators=(',', ':'), allow_nan=False)

    repo = data_path(repo); require(repo.is_dir(), 'repository directory missing')
    manifest_sha, _, raw_manifest = file(args.build_manifest, retain=True)
    actual_build = decode(raw_manifest)
    require(type(build) is dict and typed(actual_build, build), 'build object differs from actual manifest')
    declared = build.get('files')
    require(type(declared) is dict and declared, 'complete build.files population required')
    assembly = data_path(args.assembly); require(assembly.is_file(), 'assembly file missing')
    binary_root = assembly.resolve().parent
    require(assembly.name in declared, 'actual assembly absent from build.files')
    binaries = {}
    for name, expected in sorted(declared.items()):
        relative(name); full_sha(expected)
        actual, _, _ = file(binary_root / name)
        require(actual == expected, 'published binary bytes changed: ' + name)
        binaries[name] = actual

    freeze_path = repo / 'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json'
    freeze_sha, _, freeze_raw = file(freeze_path, retain=True)
    freeze = decode(freeze_raw)
    require(type(freeze) is dict and type(freeze.get('files')) is list and len(freeze['files']) == 331,
            'complete prior331 source population required')
    source_seen = set()
    for row in freeze['files']:
        require(type(row) is dict and set(row) == {'path', 'bytes', 'sha256', 'gitBlobSha1'},
                'prior source row incomplete')
        name = relative(row['path']); require(name not in source_seen, 'duplicate prior source path')
        source_seen.add(name); full_sha(row['sha256'])
        require(type(row['bytes']) is int and row['bytes'] >= 0
                and type(row['gitBlobSha1']) is str and re.fullmatch('[0-9a-f]{40}', row['gitBlobSha1']),
                'prior source size/Git identity type')
        actual, size, _ = file(repo / name)
        require(actual == row['sha256'] and size == row['bytes'], 'prior protected source changed: ' + name)

    client = data_path(args.client); require(client.is_dir(), 'prepared client directory missing')
    marker_path = client / 'aijade-prepared-renderer.json'
    _, _, marker_raw = file(marker_path, retain=True); prepared = decode(marker_raw)
    require(type(prepared) is dict and prepared.get('status') == 'PREBUILT_NO_RUNTIME_REBUILD'
            and type(prepared.get('files')) is dict and prepared['files'], 'prepared renderer marker incomplete')
    for name, expected in sorted(prepared['files'].items()):
        relative(name); full_sha(expected)
        require(not copy_ignored & set(PurePosixPath(name).parts), 'prepared file would be ignored by copytree')
        require(file(client / name)[0] == expected, 'prepared renderer file changed: ' + name)
    renderer_sources = {}
    for path in sorted(client.rglob('*')):
        name = path.relative_to(client).as_posix(); parts = set(PurePosixPath(name).parts)
        if copy_ignored & parts: continue
        require(not path.is_symlink(), 'copied renderer tree contains a link')
        if path.is_dir(): continue
        require(path.is_file(), 'copied renderer tree contains a special entry')
        if source_ignored & parts: continue
        renderer_sources[relative(name)] = file(path)[0]
    require(renderer_sources, 'renderer source population missing')

    actual_model, _, _ = file(args.model)
    require(actual_model == full_sha(model_sha), 'runner model SHA no longer matches actual asset')
    for name in ('AIJADE_REAL_GODOT', 'AIJADE_GODOT_SANDBOX_PROFILE'):
        require(type(os.environ.get(name)) is str and os.environ[name], 'actual environment file path missing: ' + name)
    values = dict(modelSha256=actual_model,
        realGodotSha256=file(os.environ['AIJADE_REAL_GODOT'])[0],
        godotWrapperSha256=file(args.godot)[0],
        sandboxProfileSha256=file(os.environ['AIJADE_GODOT_SANDBOX_PROFILE'])[0],
        rendererSources=renderer_sources, preparedRenderer=prepared, binaries=binaries,
        buildManifestSha256=manifest_sha,
        benchSha256=file(repo / 'src/Aijade.Research/SkillBench/bench-data.json')[0],
        earlierSourceFreezeSha256=freeze_sha, databaseContainer=args.db_container,
        explicitDockerPath=str(args.docker))
    require(type(values['databaseContainer']) is str and
            re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]*', values['databaseContainer']), 'database container identity missing')
    docker = values['explicitDockerPath']
    require(type(docker) is str and Path(docker).is_absolute() and '..' not in Path(docker).parts
            and not any(ord(c) < 32 for c in docker), 'explicit Docker path identity missing')
    # Docker is an identity string exactly as in the original actual block; its
    # installed link is neither resolved nor executed by this tuple collector.
    for path, expected in observed.items():
        require(not path.is_symlink() and identity(os.stat(path, follow_symlinks=False)) == expected,
                'file changed during complete backend preflight')
    require(set(values) == set(fields), 'closed backend12 tuple required')
    json.dumps(values, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return values


def load_measurement_construction_freeze(repo,q,inputs,model_sha,args,build):
    """Formal measurement needs current files, not only historical CF metadata."""
    freeze=load_construction_freeze(repo,q,inputs,model_sha)
    if freeze.get('schema') in ('aijade.ch7.prefix-construction-freeze.v1',KNOWN_REPEAT_FREEZE_SCHEMA):
        require(args is not None and type(build) is dict and model_sha is not None,
                'actual complete backend preflight is mandatory before measurement')
        actual=current_backend_before_measurement(repo,args,build,model_sha)
        require(typed_equal(qualified_backend(actual,closed=True),freeze['qualifiedBackend']),
                'actual backend before measurement differs from qualified construction freeze')
    return freeze
