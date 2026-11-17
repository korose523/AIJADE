"""Materialize and verify immutable E5 sources for unchanged historical tests.

Only source bytes are copied. The original refusal packet remains read-only;
synthetic test artifacts live in the isolated materialization's .runtime tree.
No Git, collector, binary or model command is launched by this helper.
"""
import argparse
import hashlib
import json
from pathlib import Path

E5_REL='experiments/ch7/owned-state-2026-11-18/engineering-attempt-03'
E5_Q='48299b12847c11d5a629b0292ea19d57fe771cd4'
E5_MANIFEST_SHA='0c0338bfa3b2b8862cf4e5aff4aae3baa28b1ede8a9ad0c5ab8e9a238a51b83e'
E5_SUMMARY_SHA='7b16c72c9f174eb695ff64c24457c99e57580f942029b6de1af5a90b034635ea'
E5_COMPANION_SHA='e8e2f4f040c6414900256dcf5519c6f49196d65784ab93e9bc0c516004757fc9'
E5_CRITICAL={
 'experiments/ch7/audit_nested_load.py':'88a3d165f1e47ed1fd533011f7858a58c519105f5f1caa3eb0bb384a3204cd11',
 'experiments/ch7/newowned_guard_cursor.py':'1d5013ce4e4ae7b00a560fa4c290ea82dfb4b04be112de322567854dac33b0a2',
 'experiments/ch7/mac_process_guard_v3.py':'e918de7431e3f27af2e03017a2f504bf00d85a6a08bf05d7ba5fcd3e14291035',
 'experiments/ch7/process_lifecycle.py':'93e12314fd66c4cde97323afcda7c6f7ba3e08a9a9fe078aba6b22845ea12c65',
 'experiments/ch7/full_state_clone_cursor.py':'0da9588655714d23db401b3424f45379689421898d85256b2506d674fee5e584',
 'tests/shell/test_nested_owned_initialization_audit.py':'8d75e89563445224cdaeebc2ed82bd30d44cd91747422d5a1656ef51467e9c47'}
E4_AUDIT_REL='experiments/ch7/nested-copy-2026-11-18/engineering-attempt-02/packet/source/experiments/ch7/audit_nested_load.py'
E4_AUDIT_SHA='11d5f3bce77ed0f7120d136dc734bc29acf45761877b03404cabc6a81cd7b5c7'
E4_TEST_SHA='285181a2e056c6854ee4883921dbe08c85fdfd85097d251367ebb708b690e441'
E4_INITIALIZATION_TEST_SHA='a261ea7c3e20f857b880cd6310d7452e1bc585464f273eae70996d888dff95a6'
E4_CURSOR_SHA='0da9588655714d23db401b3424f45379689421898d85256b2506d674fee5e584'
FIXTURE_POLICY_REL='configs/research/ch7-mac-nested-copy-engineering-process-policy.json'
FIXTURE_POLICY_SHA='66b5a54af64bf40bb341853cf230d6d969e951221001b57c5724cbb4383fa5e1'


def need(value,message):
    if not value:raise ValueError(message)


def digest(raw):return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    value={}
    for key,item in pairs:
        need(key not in value,'duplicate scope JSON key');value[key]=item
    return value


def read(path):
    return json.loads(Path(path).read_bytes(),object_pairs_hook=unique,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite scope JSON')))


def safe_name(value):
    need(type(value) is str and value and not value.startswith('/') and '\\' not in value
         and all(p not in ('','.','..') for p in value.split('/')),'unsafe source materialization path')
    return value


def checked_file(path,sha,size=None):
    path=Path(path)
    need(not path.is_symlink() and path.is_file(),'missing or symlink scope source')
    raw=path.read_bytes()
    need(digest(raw)==sha and (size is None or (type(size) is int and len(raw)==size)),
         'historical source bytes differ: '+str(path))
    return raw


def source_rows(repo):
    packet=Path(repo)/E5_REL/'packet'
    raw=checked_file(packet/'packet-manifest.json',E5_MANIFEST_SHA)
    manifest=json.loads(raw,object_pairs_hook=unique)
    checked_file(packet/'summary.json',E5_SUMMARY_SHA)
    need(manifest['sourceCommit']==E5_Q,'historical source commit differs')
    rows={}
    for item in manifest['files']:
        name=safe_name(item['path'])
        if name.startswith('source/'):
            relative=safe_name(name[len('source/'):]);need(relative not in rows,'duplicate historical source path')
            rows[relative]=(item['sha256'],item['sizeBytes'])
    need(len(rows)==48,'complete original E5 source population changed')
    actual={p.relative_to(packet/'source').as_posix() for p in (packet/'source').rglob('*') if p.is_file()}
    need(actual==set(rows),'historical packet source population differs')
    for name,(sha,size) in rows.items():checked_file(packet/'source'/name,sha,size)
    for name,sha in E5_CRITICAL.items():need(rows[name][0]==sha,'historical source identity differs')
    return packet,rows


def materialize_e5_source(repo):
    repo=Path(repo).resolve();packet,rows=source_rows(repo)
    root=repo/'.runtime/versioned-nested-scopes'/('e5-'+E5_Q)
    need(not root.is_symlink(),'historical source cache symlink')
    root.mkdir(parents=True,exist_ok=True)
    population={}
    for name,(sha,size) in rows.items():
        data=checked_file(packet/'source'/name,sha,size);path=root/name
        path.parent.mkdir(parents=True,exist_ok=True)
        need(not any(p.is_symlink() for p in (path,*path.parents)),'symlink in historical source cache')
        if path.exists():checked_file(path,sha,size)
        else:
            with path.open('xb') as stream:stream.write(data)
        population[name]=sha
    # This unchanged synthetic test fixture predates E5. Its original E4 bytes
    # are already in the retained archive; no new fetch or source substitution.
    origin=repo/'experiments/ch7/nested-copy-2026-11-18/engineering-attempt-02/packet/source'/FIXTURE_POLICY_REL
    raw=checked_file(origin,FIXTURE_POLICY_SHA);path=root/FIXTURE_POLICY_REL;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():checked_file(path,FIXTURE_POLICY_SHA)
    else:
        with path.open('xb') as stream:stream.write(raw)
    population[FIXTURE_POLICY_REL]=FIXTURE_POLICY_SHA
    marker=dict(schema='aijade.versioned-e5-test-source.v1',sourceCommit=E5_Q,
        originalSourceFiles=48,additionalOriginalFixtureFiles=1,files=population,
        packetManifestSha256=E5_MANIFEST_SHA,scope='Unchanged historical tests; not current native source or engineering acceptance.')
    encoded=(json.dumps(marker,sort_keys=True,indent=2)+'\n').encode();target=root/'scope-source-manifest.json'
    if target.exists():need(target.read_bytes()==encoded,'historical scope marker changed')
    else:
        with target.open('xb') as stream:stream.write(encoded)
    verify_materialized_e5(root)
    return root


def verify_materialized_e5(root):
    root=Path(root);marker=read(root/'scope-source-manifest.json')
    need(marker['sourceCommit']==E5_Q and marker['originalSourceFiles']==48
         and marker['additionalOriginalFixtureFiles']==1 and len(marker['files'])==49,'historical scope marker schema')
    for name,sha in marker['files'].items():checked_file(root/safe_name(name),sha)
    for name,sha in E5_CRITICAL.items():need(marker['files'][name]==sha,'historical source identity drift')
    return marker


def verify_companion_receipt(repo):
    packet,_=source_rows(repo);folder=packet.parent/'post-terminal-controls'
    value=read(folder/'packet-controls-final-15.json')
    checked_file(folder/'packet-controls-final-15.json',E5_COMPANION_SHA)
    need(value['actualPrimaryManifestSha256']==E5_MANIFEST_SHA
         and value['status']=='FIFTEEN_ADVERSARIAL_POST_TERMINAL_CONTROLS_PASS'
         and type(value['passed']) is int and value['passed']==15
         and type(value['failed']) is int and value['failed']==0
         and len(value['controls'])==15 and all(c['status']=='REJECTED_EXPECTED_PREDICATE' for c in value['controls'])
         and value['originalPrimaryUnchanged'] is True and value['backendQualified'] is False
         and value['independentHumanReview'] is False,'recorded original fifteen controls changed')
    for name,key in [('test_actual_e5_packet_controls.py','originalFourteenSourceSha256'),
        ('test_fictitious_outer_call.py','additionalControlSourceSha256'),('packet_common.py','commonSourceSha256'),
        ('verify_e5_packet.py','verifierSourceSha256'),('lossless_members.py','codecSourceSha256'),
        ('e5_refusal_semantics.py','semanticsSourceSha256')]:checked_file(folder/name,value[key])
    return dict(status='EXACT_RECORDED_FIFTEEN_CONTROLS_VERIFIED_NOT_RERUN',passed=15,
                primaryManifestSha256=E5_MANIFEST_SHA,receiptSha256=E5_COMPANION_SHA)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--verify-companions',action='store_true');args=parser.parse_args()
    result=verify_companion_receipt(args.repo) if args.verify_companions else dict(sourceRoot=str(materialize_e5_source(args.repo)))
    print(json.dumps(result,indent=2))
