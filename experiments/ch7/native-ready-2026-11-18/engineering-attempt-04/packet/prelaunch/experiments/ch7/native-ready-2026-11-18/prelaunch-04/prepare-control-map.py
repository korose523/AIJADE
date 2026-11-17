"""Explicit, reviewable E6 preparation inventory; never launches an observer."""
from pathlib import Path
import hashlib
import json

B = Path('/Volumes/Untitled/AIJADE')
C = Path(__file__).resolve().parent
E5 = B / '.research/runs/ch7-owned-state-20261118'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    selected = {}

    def add(path, name):
        path = Path(path)
        assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(B)
        assert name not in selected and str(path) not in (str(p) for p in selected.values())
        assert path.stat().st_size <= 32 * 1024 ** 2
        selected[name] = path

    # Only immediate recorded inputs/results, never recursive runtime fixture trees.
    root_names = [
        'baseline-source.json', 'compile-01.json', 'compile-01.stdout', 'compile-01.stderr',
        'component-handoff-01.json', 'component-plan-01-before-runtime-enforcement.json',
        'component-plan-02.json', 'component-population-refusal-checkpoint.json',
        'component-pre-query-filesystem-checkpoint.json', 'component_probe.py',
        'component-01.log', 'component-first-actual-invocation.log',
        'first-native-phase-analysis.json', 'first-execution-position-decision.json',
        'first-execution-position-decision.before-exact-scalar-read.json',
        'source-review-01.json', 'native-launch-exact.diff', 'original-launch.py.txt',
        'native-launch.py.txt', 'native-controls-01.log', 'native-controls-02.log',
        'test_component_capture.py', 'component-capture-controls-01.log',
        'prepare-integration.py', 'integration-preparation-01.log',
        'production-application-01.json', 'actual-policy-source-check-01.json',
        'portable-tests-application-01.json', 'launcher-source-application-01.json',
        'native-audit-application-01.json',
        'prospective-native-ready-engineering.before-component-position.md',
        'prospective-native-ready-engineering.draft.md',
        'actual-w5-integration-45-01.log', 'actual-w5-integration-45-02.log',
        'actual-w5-listener-65-01.log', 'actual-w5-listener-65-02.log',
        'actual-w5-native-20-01.log', 'actual-w5-native-20-02.log',
        'actual-w5-launcher-81-01.log', 'actual-w5-launcher-81-02.log',
        'actual-w5-native-audit-30-01.log', 'final-source-review-01.json',
        'actual-w5-controls-summary-01.json',
        'review-wording-precision-note-01.json',
        'ci-source-application-01.json',
        'source-freeze-qe6-attempt-01.json', 'source-qe6-publication-attempt-01.json',
        'source-qe6-ci-attempt-01.json', 'source-qe6-ci-failed-01.log',
        'source-qe6-ci-watch-attempt-01.log', 'ci-module-inventory-fix-01.json',
        'project-scope-controls-01.log', 'project-scope-result-01.json',
        'control-evidence-map-before-ci-module-fix-01.json',
    ]
    for name in root_names:
        add(C / name, 'controls/' + name)
    folders = ('integration-tests', 'audit-controls', 'listener-evidence',
               'launcher-preparation', 'portable-tests', 'ci-preparation')
    for folder in folders:
        directory = C / folder
        assert directory.is_dir(), str(directory)
        for path in sorted(directory.iterdir()):
            if path.is_file():
                add(path, 'controls/' + folder + '/' + path.name)
    add(C / 'launcher-preparation/testdata/nested-engineering-protocol.fixture.json',
        'controls/launcher-preparation/testdata/nested-engineering-protocol.fixture.json')
    add(C / 'integration/preparation-01.json', 'controls/integration/preparation-01.json')
    # Follow only explicit, hash-verified handoff rows. This includes retained
    # superseded sources without sweeping generated runtime fixture trees.
    for folder in ('integration-tests', 'audit-controls', 'listener-evidence',
                   'portable-tests', 'ci-preparation'):
        manifest = json.loads((C / folder / 'HANDOFF.json').read_bytes())
        for row in manifest['files']:
            path = Path(row['path'])
            if not path.is_absolute():
                path = C / folder / path
            assert digest(path) == row['sha256'], 'explicit handoff row changed: ' + str(path)
            if path not in selected.values():
                add(path, 'controls/' + path.relative_to(C).as_posix())
    for relative, row in json.loads((C / 'component-handoff-01.json').read_bytes())['files'].items():
        path = C / relative
        assert digest(path) == row['sha256'], 'component handoff row changed: ' + relative
        if path not in selected.values():
            add(path, 'controls/' + relative)
    # The frozen component's complete output, including both clearly synthetic
    # prior histories, is retained. Lock files contain no measurements.
    component = B / '.runtime/posix/runs/ch7-native-ready-20261118/component-01'
    for path in sorted(component.iterdir()):
        if path.is_file():
            add(path, 'component/' + path.name)
    for mode in ('legacy', 'native'):
        for name in ('lifecycle-journal.jsonl', 'process-policy.json'):
            add(component / mode / name, 'component/' + mode + '/' + name)
    history = {
        'e5-refusal-publication.json': E5 / 'e5-refusal-publication.json',
        'e5-independent-negative-audit-01.json': E5 / 'audit/e5-independent-negative-audit-01.json',
        'listener-cause-precision-correction-01.json': E5 / 'audit/listener-cause-precision-correction-01.json',
        'e6-auditor-readonly-review-01.json': E5 / 'papers/e5-final-staging/e6-auditor-readonly-review-01.json',
    }
    for name, path in history.items():
        add(path, 'retained-history/' + name)
    names = list(selected)
    categories = {
        'cursorControls': [n for n in names if n.startswith('controls/') and
            not n.startswith('controls/launcher-preparation/')],
        'pairedBootstrapProbe': [n for n in names if n.startswith('component/') or
            'component' in n or 'first-' in n or 'owned13' in n or
            n in ('controls/integration-tests/CONTROL-RESULT.json',
                  'controls/actual-w5-integration-45-02.log')],
        'launcherControls': [n for n in names if n.startswith('controls/launcher-preparation/')],
        'retainedHistory': [n for n in names if n.startswith('retained-history/')],
    }
    assert all(categories.values())
    data = dict(schema='aijade.ch7.native-ready-control-evidence.v1',
        categories=categories, files=[dict(path=str(p), name=n, sha256=digest(p))
                                    for n, p in selected.items()],
        scope='Actual preparation and retained adverse component; unit controls are not load acceptance.')
    target = C / 'control-evidence-map.json'
    with target.open('x') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(path=str(target), sha256=digest(target), files=len(selected),
        bytes=sum(p.stat().st_size for p in selected.values())), indent=2))


if __name__ == '__main__':
    main()
