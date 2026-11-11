#!/usr/bin/env python3
"""Stage the exact, completed second-corpus packet outside the running checkout.

This never starts measurement or edits the public checkout. Numerical/figure gates
must already be met. Existing output is never silently replaced.
"""
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

CACHE = Path('/Users/mac/.cache/aijade-p3-longmem-20261111')
REPO = Path('/Volumes/Untitled/AIJADE/AIJADE-next')
SOURCE = '9d17f8235508afa1cfba9e6da758f1738adfe8ea'
PLAN = 'a7961cf8cde1de659c2272a664d4c936a50484c4'
OUT = CACHE/'public-packet'


def read(p):
    return json.loads(p.read_text())


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024**2), b''):
            h.update(chunk)
    return h.hexdigest()


def copy_file(src, relative):
    assert src.is_file(), str(src)
    dst = OUT/relative
    assert not dst.exists(), str(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    assert sha(src) == sha(dst)


def copy_tree(src, relative):
    assert src.is_dir(), str(src)
    for p in sorted(src.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts:
            copy_file(p, Path(relative)/p.relative_to(src))


def main():
    acceptance = read(CACHE/'analysis-acceptance.json')
    assert acceptance['kernel'] == acceptance['product'] == 'PASS'
    assert acceptance['measurementCodeCommit'] == SOURCE and acceptance['planCommit'] == PLAN
    assert read(CACHE/'figure-visual-review.json')['status'] == 'PASS'
    assert read(CACHE/'postprocess-status.json')['status'] == 'NUMERICAL_AND_AUTOMATED_FIGURE_QA_COMPLETE_PENDING_VISUAL_REVIEW'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip() == SOURCE
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO, text=True).strip()
    for entry in read(CACHE/'frozen-binaries.json'):
        assert sha(Path(entry['path'])) == entry['sha256']
    final_input=read(CACHE/'input-source-final-state.json')
    assert final_input['status']=='PASS' and final_input['corpusSha256']=='d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442'
    protected=read(REPO/'experiments/p3-longmemeval/2026-11-11/historical-input-hashes.json')
    assert len(protected)==5 and all(sha(REPO/path)==value for path,value in protected.items())
    assert not OUT.exists(), 'An earlier stage exists; preserve and inspect it before choosing a new output.'
    OUT.mkdir()
    copy_tree(REPO/'experiments/p3-longmemeval/2026-11-11', '.')
    development=read(OUT/'development-checks.json')
    for run in development['runs']:
        original=CACHE/'qualification-development'/run['file']
        assert sha(original)==run['sha256']
        copy_file(original, 'qualification/development/'+run['file'])
    copy_tree(CACHE/'measurements/inputs', 'inputs')
    copy_file(CACHE/'session-overlap-diagnostic.json', 'inputs/session-overlap-diagnostic.json')
    copy_file(CACHE/'gold-content-collision.json', 'inputs/gold-content-collision.json')
    phases = ['build', 'input', 'qualification', 'kernel', 'product-text',
              'kernel-independent-audit', 'product-independent-analysis',
              'delivery-figure', 'figure-text-audit', 'figure-collision-audit']
    for phase in phases:
        receipt = read(CACHE/'bounded'/phase/'receipt.json')
        assert receipt['status'] == 'PASS' and receipt['exitCode'] == 0 and receipt['sourceUnchanged']
        assert receipt['codeCommit'] == SOURCE
        copy_tree(CACHE/'bounded'/phase, 'execution/'+phase)
    copy_tree(CACHE/'measurements/qualification', 'qualification')
    for p in sorted((CACHE/'measurements/kernel').rglob('*')):
        if not p.is_file():
            continue
        relative = Path('results/kernel')/p.relative_to(CACHE/'measurements/kernel')
        if p.name != 'kernel-cases.jsonl':
            copy_file(p, relative)
            continue
        target = OUT/relative.with_suffix('.jsonl.gz')
        target.parent.mkdir(parents=True, exist_ok=True)
        with p.open('rb') as source, target.open('xb') as raw:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=6) as compressed:
                shutil.copyfileobj(source, compressed, length=1024**2)
        h = hashlib.sha256()
        with gzip.open(target, 'rb') as f:
            for block in iter(lambda: f.read(1024**2), b''):
                h.update(block)
        assert h.hexdigest() == sha(p)
    copy_tree(CACHE/'measurements/product', 'results/product')
    copy_tree(CACHE/'measurements/product-analysis', 'audit/product')
    copy_file(CACHE/'measurements/product-analysis/product-summary.json', 'results/product-summary.json')
    copy_tree(CACHE/'measurements/kernel-audit', 'audit/kernel')
    copy_file(CACHE/'analysis-acceptance.json', 'results/acceptance.json')
    copy_file(CACHE/'independent-qualification.json', 'audit/independent-qualification.json')
    copy_file(CACHE/'qualification-reaudit.json', 'audit/qualification-reaudit.json')
    copy_file(CACHE/'frozen-binaries.json', 'execution/frozen-binaries.json')
    copy_file(CACHE/'input-source-final-state.json', 'execution/input-source-final-state.json')
    (OUT/'execution/historical-files-final-check.json').write_text(json.dumps(dict(
        status='PASS',checkedAt=dt.datetime.now(dt.timezone.utc).isoformat(),files=protected,
        scope='All five original historical files remain byte-identical to source-freeze identities.'),indent=2)+'\n')
    copy_file(CACHE/'kernel-swap-excursion-audit.json', 'execution/kernel-swap-excursion-audit.json')
    copy_file(CACHE/'kernel-journal-integrity.json', 'audit/kernel-journal-integrity.json')
    copy_file(CACHE/'figure-visual-review.json', 'figures/visual-review.json')
    copy_file(CACHE/'figure-contract.json', 'figures/design-contract.json')
    copy_tree(CACHE/'measurements/figures', 'figures')
    for name in ['audit_kernel.py', 'verify_archive.py', 'plot_longmem_delivery.py',
                 'verify_qualification.py', 'prepare_public_packet.py', 'test_archive_rejections.py']:
        copy_file(CACHE/name, name)
    copy_file(CACHE/'DOTNET-MIT-LICENSE.txt', 'DOTNET-MIT-LICENSE.txt')
    for p in CACHE.glob('*-analysis-identity.json'):
        copy_file(p, 'execution/'+p.name)
    summary=read(OUT/'results/product-summary.json')
    kernel=read(OUT/'results/kernel/kernel-receipt.json')
    assert kernel['markedCases']==479 and kernel['primaryCases']==470
    note=['\n\n## Completed execution and numerical acceptance\n',
          'This section postdates the source-freeze status above. The measurement source remains `'+SOURCE+'`; the later archive adds records and hash-identified audit programs, rather than claiming those programs were in the measurement commit.\n',
          'All 500 source questions remain in the ledger. The fresh kernel journal has 479 marked cases and the corrected primary frame has 470 non-abstention cases. All five historical numerical families passed the declared 1e-9 reconstruction gate. The product phase made 246,738 real perception-API writes and captured all 2,000 actual outgoing request bodies. It used no live answer/embedding model, and did not test answer quality.\n',
          '| Fixed text policy | Pool fraction | Complete-prompt fraction L–U | Pool-to-prompt loss L–U | Unknown / truncated primary cases |',
          '|---|---:|---:|---:|---:|']
    for policy in ['6-newest','6-server','60-newest','60-server']:
        cell=summary['policies'][policy]
        note.append('| '+policy+' | '+format(cell['stages']['pool']['mean'],'.6f')+' | '+
                    format(cell['promptLower']['mean'],'.6f')+'–'+format(cell['promptUpper']['mean'],'.6f')+' | '+
                    format(cell['candidateToPromptLossLower']['mean'],'.6f')+'–'+format(cell['candidateToPromptLossUpper']['mean'],'.6f')+' | '+
                    str(cell['unknown'])+' / '+str(cell['truncated'])+' |')
    note += ['\nL–U are identification bounds, not confidence intervals. Fractions average the source-marked turn fractions over all 470 primary cases. A partial turn can still contain useful information; complete-turn loss is not measured answer loss. All three prespecified product contrasts and all four predicted-gating contrasts, including adverse and non-identified outcomes, remain in the records.\n',
             'The 470 primary histories share 3,556 source-session IDs and form one overlap component. This is not an effective-N or user-identity estimate. Case bootstrap/sign-flip results are conditional reweighting sensitivities, not independent-user replication or dependence-robust population inference. All 30 official abstentions remain in execution; the 21 evidence-free cases retain null denominators. Exact-content input diagnostics do not establish semantic annotation completeness.\n',
             'Layout: `inputs/` contains eligibility, separate answers, session overlap and input-only diagnostics; `execution/` contains bounded receipts, telemetry and program/binary identities; `qualification/` retains actual synthetic requests and the failed/passing development TRX files; `results/` contains the complete kernel/product records; `audit/` retains independent numerical reconstructions and case ledgers; `figures/` retains editable exports, source CSV and AI-assisted QA. `manifest.json` lists every other physical file by size and SHA-256. The raw kernel journal is losslessly gzip-compressed; its uncompressed SHA matches the measurement receipt. Canonical corpus files are not vendored.\n',
             'Run the stdlib archive/point-estimate check from the repository root:\n\n```sh\npython3 experiments/p3-longmemeval/2026-11-11/verify_archive.py\n```\n',
             'The separate `test_archive_rejections.py --out /tmp/aijade-lme-refusals.json` command checks a missing final capture, a changed primary denominator and a contradictory unknown-attribution flag in temporary linked copies; it preserves the source archive and starts no service. Use a new report path on repeats.\n',
             'For complete numerical reconstruction, use Python with NumPy (the execution records identify exact versions). Run `audit_kernel.py --kernel results/kernel --inputs inputs --out UNIQUE_NEW_OUTPUT` from this directory. From the repository root, run `tools/p3_longmemeval/analyze_product.py --product experiments/p3-longmemeval/2026-11-11/results/product --inputs experiments/p3-longmemeval/2026-11-11/inputs --out UNIQUE_NEW_OUTPUT`. `verify_qualification.py --qualification qualification` checks the eight saved qualification requests. These audits start no database or model service. Preserve existing outputs rather than reusing an old destination.\n',
             'The existing Docker database is a shared service outside the owned process-family accounting; host-memory/swap limits still applied. This numerical acceptance and AI-assisted visual QA do not establish formal Mac model qualification, independent human adjudication, dense/external-system second-corpus results, evolving Web/QQ behavior, CAS journal eligibility, author approval or submission readiness. No P2 retry, deployment, release, DOI deposition or message sending was performed.\n']
    readme=OUT/'README.md'
    prior=readme.read_text();heading,separator,rest=prior.partition('\n')
    banner=('\n\n> Current archived status: all 500 histories executed, 246,738 product writes and 2,000 actual request captures; '
            'kernel/product numerical reconstructions and AI-assisted figure QA passed. The source-freeze statuses below '
            'are retained historical records, not the final execution status. Scientific scope and remaining gates are stated '
            'in the completed-execution section.\n\n')
    readme.write_text(heading+banner+rest+'\n'.join(note)+'\n')
    rows = []
    for p in sorted(OUT.rglob('*')):
        if p.is_file():
            assert p.stat().st_size < 95*1024**2, 'Review GitHub physical file size: '+str(p)
            rows.append(dict(path=p.relative_to(OUT).as_posix(), bytes=p.stat().st_size, sha256=sha(p)))
    manifest = dict(schema='aijade.p3.longmemeval.archive.v1', planCommit=PLAN,
                    measurementCodeCommit=SOURCE, createdAt=dt.datetime.now(dt.timezone.utc).isoformat(),
                    independentHumanReview=False, files=rows)
    (OUT/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps(dict(status='STAGED_PENDING_ARCHIVE_VALIDATION', files=len(rows),
                         bytes=sum(r['bytes'] for r in rows), manifestSha256=sha(OUT/'manifest.json'))))


if __name__ == '__main__':
    main()
