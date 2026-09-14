import { describe, expect, it } from 'vitest'

import {
  auc,
  buildCorpusIdf,
  fitSalienceLogistic,
  predictSalienceV2,
  PRIOR_SALIENCE_WEIGHTS,
  SALIENCE_FEATURES,
  salienceFeatureVector,
  scoreFeatures,
  standardizeFeatures,
} from './salience'

function ctx(texts: string[]) {
  const { idf, nDocs } = buildCorpusIdf(texts)
  return { priors: [] as string[], idf, nDocs }
}

describe('salience v2 — v4 §7.2 augmented predictor (A1)', () => {
  it('exposes exactly the 13 features the probe/LOCV agree on', () => {
    expect(SALIENCE_FEATURES).toHaveLength(13)
    expect(SALIENCE_FEATURES.map(f => f.name)).toContain('length')
    expect(SALIENCE_FEATURES.map(f => f.name)).toContain('noveltyIdf')
  })

  it('feature vector length matches the feature definition', () => {
    const c = ctx(['a b c', 'd e f'])
    expect(salienceFeatureVector('a b c', c)).toHaveLength(13)
  })

  it('ranks a long self-disclosing turn above a backchannel', () => {
    const c = ctx([
      'I went to Paris last March with my sister and saw the Eiffel Tower; it was unforgettable.',
      'haha yeah',
      'oh wow?',
    ])
    const long = predictSalienceV2(
      'I went to Paris last March with my sister and saw the Eiffel Tower; it was unforgettable.',
      c,
      { weights: PRIOR_SALIENCE_WEIGHTS },
    ).score
    const bc = predictSalienceV2('haha yeah', c, { weights: PRIOR_SALIENCE_WEIGHTS }).score
    const wow = predictSalienceV2('oh wow?', c, { weights: PRIOR_SALIENCE_WEIGHTS }).score
    expect(long).toBeGreaterThan(bc)
    expect(long).toBeGreaterThan(wow)
    // 问句与反馈语的负权重应让它们低于零或至少低于长陈述
    expect(wow).toBeLessThan(long)
  })

  it('is deterministic for identical inputs', () => {
    const c = ctx(['the cat sat on the mat', 'the dog ran fast'])
    const a = predictSalienceV2('the cat sat on the mat', c).score
    const b = predictSalienceV2('the cat sat on the mat', c).score
    expect(a).toBe(b)
  })

  it('reads no label: a feature vector depends only on text and priors', () => {
    const c = ctx(['alpha beta', 'gamma delta'])
    const withPrior = predictSalienceV2('alpha beta', { priors: ['alpha beta'], idf: c.idf, nDocs: c.nDocs }).score
    const without = predictSalienceV2('alpha beta', { priors: [], idf: c.idf, nDocs: c.nDocs }).score
    expect(withPrior).not.toBe(without)
  })
})

describe('fitSalienceLogistic', () => {
  it('separates a linearly separable toy problem (AUC ≈ 1)', () => {
    // 单一特征：正类值大，负类值小；逻辑回归应能完美分开
    const X = [
      [0.1],
      [0.2],
      [0.3],
      [0.9],
      [1.0],
      [0.95],
    ]
    const y = [0, 0, 0, 1, 1, 1]
    const w = fitSalienceLogistic(X, y, 0.5, 2000, 0.5)
    const sc = scoreFeatures(w, X)
    expect(auc(sc, y)).toBeGreaterThan(0.99)
  })

  it('standardizeFeatures yields ~zero-mean, ~unit-sd columns', () => {
    const rows = [
      [1, 10],
      [2, 20],
      [3, 30],
      [4, 40],
    ]
    const { data, mean, sd } = standardizeFeatures(rows)
    expect(mean[0]).toBeCloseTo(2.5, 6)
    expect(sd[0]).toBeCloseTo(Math.sqrt(1.25), 6)
    const colMean = data.reduce((s, r) => s + r[0], 0) / data.length
    expect(colMean).toBeCloseTo(0, 6)
  })
})
