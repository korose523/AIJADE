"""Select only already-verified E6 prelaunch evidence. No runtime dispatch."""
from pathlib import Path
import json
import hashlib

C = Path(__file__).resolve().parent


def main():
    mapping = json.loads((C / 'control-evidence-map.json').read_bytes())
    rows = [dict(path=r['path'], name=r['name']) for r in mapping['files']]
    for name in ('engineering-04-passport.json', 'source-qe6-ci.json',
                 'source-qe6-ci.log', 'source-qe6-publication.json',
                 'source-qe6-ci-download-receipt.json', 'source-qe6-ci-log.stderr',
                 'source-qe6-ci-watch.log',
                 'source-freeze-qe6.json', 'control-evidence-map.json',
                 'prepare-engineering-passport.py', 'publish-engineering-freeze.py',
                 'verify-qe6-publication.py', 'prepare-control-map.py',
                 'prepare-prelaunch-selection.py'):
        path = C / name
        assert path.is_file() and not path.is_symlink()
        rows.append(dict(path=str(path), name=name))
    target = C / 'prelaunch-artifacts.json'
    rows.append(dict(path=str(target), name=target.name))
    assert len({r['name'] for r in rows}) == len({r['path'] for r in rows}) == len(rows)
    result = dict(schema='aijade.ch7.native-ready-explicit-prelaunch-selection.v1', files=rows,
                  runtimeDispatch=False, componentResult='NOT_ALL_PASS_RETAINED',
                  engineeringAcceptance=False, backendQualification=False)
    with target.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(path=str(target), sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                         files=len(rows)), indent=2))


if __name__ == '__main__':
    main()
