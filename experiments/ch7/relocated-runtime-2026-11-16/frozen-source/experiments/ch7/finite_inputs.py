#!/usr/bin/env python3
"""Prospective deterministic construction. No new cases are made by the bank/qualification modes."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess

from comparison_manifest import CONDITIONS, REGISTRY_SHA256, window_registry, require

ROOT = Path(__file__).resolve().parents[2]
PLAN = 'experiments/plans/2026-11-12-ch7-confirmed-finite-heldout.md'
BANK = 'experiments/ch7/finite-heldout/candidate-bank.json'
FAMILIES = ['none', 'execution_receipt_intent', 'asset_admission', 'duplicate_invocation_2',
            'execution_unknown', 'execution_failed', 'claimed_receipt_stage',
            'revocation_before_round2', 'post_promotion_authority_write', 'wrong_allowed_act_in_round1']
REPLAY = ['before_delivery', 'after_delivery', 'after_first_reuse', 'after_duplicate_reuse']
REVOKE = ['before_delivery', 'after_delivery', 'after_memory_probe', 'after_authority_probe']
FAILURE = ['authority_before', 'authority_after', 'outcome_before', 'outbox_before']
ACTS = ['inform', 'comfort', 'celebrate']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def write_new(path, value):
    require(not path.exists(), 'never overwrite a constructed input: '+str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))


def bank(repo):
    old = json.loads((repo/'experiments/ch7/2026-11-12/selection.json').read_text())
    for p, digest in old['sources'].items():
        require(sha((repo/p).read_bytes()) == digest, 'archived candidate/test source changed')
    base = repo/'experiments/rq-c/redo/rq-c-s42-ollama-t30-r5'
    candidates = [json.loads(l) for l in (base/'candidates.jsonl').read_text().splitlines()]
    trials = [json.loads(l) for l in (base/'trials.jsonl').read_text().splitlines()]
    require(len(candidates) == len(trials), 'candidate/trial source alignment')
    excluded = {'arr-sum', 'parse-query-string', 'str-to-camel', 'math-round-to', 'parse-csv-line'}
    eligible = []
    for i, (c,t) in enumerate(zip(candidates,trials),1):
        if t['condition'] != 'sv1-ef0' or t['reused'] or t['round'] != 0 or t['attempt'] != 0 or t['taskId'] in excluded:
            continue
        require(c['skillId'] == t['skillId'] and not c['reused'] and c['execOk'] == t['execOk'], 'selected source row join')
        require(type(t['execOk']) is bool and t['selfVerdict'] in ['pass','fail'], 'original label type')
        eligible.append(dict(taskId=t['taskId'], line=i, candidate=c, trial=t, code=c['code'], codeSha256=sha(c['code'].encode())))
    selected = []
    for label in [True,False]:
        tasks = sorted({p['taskId'] for p in eligible if p['trial']['execOk'] is label})[:4]
        require(len(tasks) == 4, 'insufficient declared candidate stratum; do not replace')
        selected += [next(p for p in eligible if p['taskId']==task and p['trial']['execOk'] is label) for task in tasks]
    return dict(schema='aijade.ch7.archived-candidate-bank.v1', programs=selected, sources=old['sources'],
                selectionRule='First eligible archived line for each of the lexicographically first four distinct tasks per original execution-label stratum; original sv1-ef0/nonreused/round0/attempt0 only; exclusions fixed in prior plan.',
                excludedTasks=sorted(excluded), newModelJudgments=0, newHeldoutCases=0,
                interpretation='Original labels unchanged; suitability/replay is AI-assisted, not independent human semantic review.')


def qualify(repo, commit, output):
    old = json.loads((repo/'experiments/ch7/live-manifest-known-input-v1.json').read_text())
    selection = json.loads((repo/'experiments/ch7/2026-11-12/selection.json').read_text())
    pool = dict(schema='aijade.ch7.archived-candidate-bank.v1', programs=[selection['usable'],selection['unusable']],
                sources=selection['sources'], newModelJudgments=0, newHeldoutCases=0,
                interpretation='The same two programmes as the old development inputs, not the new candidate pool.')
    write_new(output/'selection.json', pool)
    cases = [dict(input=copy.deepcopy(c), replayAt='before_delivery' if c['operations']['repeatOutcome'] else 'none',
                  revokeAt='after_delivery' if c['operations']['revokeBeforeReuse'] else 'none',
                  failurePoint='authority_before' if c['operations']['failStateWrite'] else 'none') for c in old['cases']]
    runtime = dict(schema='aijade.ch7.live-case-manifest.v2', purpose='qualification_only',
                   protocolPlanSha256=sha((repo/PLAN).read_bytes()), constructionFreezeCommit=commit,
                   selectionSha256=sha((output/'selection.json').read_bytes()), blockIndex=0, cases=cases)
    template = json.loads((repo/'experiments/ch7/manifest-preparation-2026-11-12/comparison-manifest.json').read_text())
    write_new(output/'runtime-manifest.json', runtime)
    write_new(output/'scoring-manifest.json', scoring(runtime,template['cases'],sha(encoded(runtime))))


def scoring(runtime, rules, runtime_sha):
    return dict(schema='aijade.ch7.finite-scoring-manifest.v1', purpose=runtime['purpose'],
                constructionFreezeCommit=runtime['constructionFreezeCommit'], blockIndex=runtime['blockIndex'],
                runtimeManifestSha256=runtime_sha, selectionSha256=runtime['selectionSha256'],
                conditions=copy.deepcopy(CONDITIONS), windowRegistrySha256=REGISTRY_SHA256,
                cases=copy.deepcopy(rules), scheduledInvalidPromotionOpportunitiesPerCondition=sum(r['promotionOpportunity'] for r in rules),
                scheduledInvalidReuseOpportunitiesPerCondition=sum(r['reuseOpportunity'] for r in rules),
                round2SemanticActCorrectness='NOT_MEASURED')


def derive_suite(repo, freeze, model_sha):
    """Pure rule derivation; invoked for fresh inputs only after the public qualification freeze."""
    files = {}
    pool = json.loads((repo/BANK).read_text()); require(pool == bank(repo), 'candidate selection changed')
    require(len(model_sha)==64 and all(c in '0123456789abcdef' for c in model_sha), 'actual model SHA-256')
    seed = sha(('aijade-ch7-confirmed-40-v1:'+freeze).encode())
    registry = window_registry(); blocks=[]; suitability=[]
    for b in range(4):
        ids = {f:'h_'+sha((seed+':'+str(b)+':'+f).encode())[:24] for f in FAMILIES}
        ordered = sorted(FAMILIES, key=lambda f: sha((seed+':order:'+str(b)+':'+f).encode()))
        cases=[]; rules=[]
        for i,f in enumerate(ordered):
            family_index=FAMILIES.index(f); candidate=pool['programs'][b+(4 if f=='execution_failed' else 0)]
            act=ACTS[(b+family_index)%3]; override=ACTS[(b+family_index+1)%3] if f=='wrong_allowed_act_in_round1' else None
            asset=None
            if f=='asset_admission':
                position=[0,15,31,63][b]; asset=model_sha[:position]+format((int(model_sha[position],16)+1)%16,'x')+model_sha[position+1:]
            foreign=FAMILIES[[0,9,5,7][b]]
            op=dict(execution='omit' if f=='execution_unknown' else 'run', mapperActOverride=override,
                    receiptCaseId=ids[foreign] if f=='execution_receipt_intent' else ids[f], assetVersionOverride=asset,
                    claimedStage='pixels_observed' if f=='claimed_receipt_stage' else 'behavior_overlay_pre_solve',
                    repeatOutcome=f=='duplicate_invocation_2', revokeBeforeReuse=f=='revocation_before_round2',
                    failStateWrite=f=='post_promotion_authority_write')
            item=dict(input=dict(caseId=ids[f],conditions=['C1','C2'] if i<5 else ['C2','C1'],taskId=candidate['taskId'],
                                 codeSha256=candidate['codeSha256'],requestedAct=act,operations=op),
                      replayAt=REPLAY[b] if op['repeatOutcome'] else 'none',revokeAt=REVOKE[b] if op['revokeBeforeReuse'] else 'none',
                      failurePoint=FAILURE[b] if op['failStateWrite'] else 'none')
            cases.append(item); rules.append(dict(caseId=ids[f],**registry[f]))
            suitability.append(dict(blockIndex=b,caseId=ids[f],family=f,taskId=candidate['taskId'],codeSha256=candidate['codeSha256'],
                                    originalCandidateLine=candidate['line'],originalExecutionOk=candidate['trial']['execOk'],
                                    novelty='Programme/task binding differs from both prior selected development programmes; operational placements and receipt relationships separately declared.'))
        runtime=dict(schema='aijade.ch7.live-case-manifest.v2',purpose='confirmed_finite_heldout',
                     protocolPlanSha256=sha((repo/PLAN).read_bytes()),constructionFreezeCommit=freeze,
                     selectionSha256=sha((repo/BANK).read_bytes()),blockIndex=b,cases=cases)
        directory=Path('block-'+str(b+1));files[str(directory/'runtime-manifest.json')]=runtime
        score_manifest=scoring(runtime,rules,sha(encoded(runtime)));files[str(directory/'scoring-manifest.json')]=score_manifest
        blocks.append(dict(blockIndex=b,directory=directory.name,runtimeManifestSha256=sha(encoded(runtime)),
                           scoringManifestSha256=sha(encoded(score_manifest))))
    files['construction.json']=dict(schema='aijade.ch7.finite-construction.v1',constructionFreezeCommit=freeze,seed=seed,
        seedDerivation='sha256(aijade-ch7-confirmed-40-v1: + full freeze commit)',planSha256=sha((repo/PLAN).read_bytes()),
        candidateBankSha256=sha((repo/BANK).read_bytes()),modelSha256=model_sha,blocks=blocks,casePairs=40,conditionRows=80,
        invalidPromotionOpportunitiesPerArm=28,invalidReuseOpportunitiesPerArm=32,
        independentHumanReview=False,investigatorBlinding=False,newModelJudgments=0)
    files['suitability.json']=dict(status='CONSTRUCTED_FOR_PREMEASUREMENT_SUITABILITY_CHECK',cases=suitability,
        independentHumanReview=False,interpretation='Finite combinations of previously declared fault families; four variants are not independent fault families.')
    return files


def construct(repo, freeze, model_sha, output):
    require(not output.exists(), 'case construction is single use')
    require(subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True)=='', 'dirty construction checkout')
    require(subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==freeze, 'construction freeze is not current source')
    receipt=json.loads((repo/'experiments/ch7/finite-heldout/qualification-acceptance.json').read_text())
    require(receipt['status']=='QUALIFIED_BEFORE_FRESH_CASE_CONSTRUCTION', 'qualification not accepted')
    for relative,value in derive_suite(repo,freeze,model_sha).items():write_new(output/relative,value)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['bank','qualification','construct'])
    p.add_argument('--repo',type=Path,default=ROOT);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--freeze');p.add_argument('--model-sha256');a=p.parse_args()
    if a.mode=='bank': write_new(a.output,bank(a.repo))
    elif a.mode=='qualification': qualify(a.repo,a.freeze,a.output)
    else: construct(a.repo,a.freeze,a.model_sha256,a.output)
