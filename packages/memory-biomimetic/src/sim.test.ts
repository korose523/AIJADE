import { describe, expect, it } from 'vitest'

import { buildLexicalIndex, cosine, tokenF1, tokenize } from './sim'

describe('tokenize', () => {
  it('lowercases and drops stopwords', () => {
    expect(tokenize('The Quick brown FOX!')).toEqual(['quick', 'brown', 'fox'])
  })
  it('drops single-char tokens', () => {
    expect(tokenize('a b cat')).toEqual(['cat'])
  })
})

describe('tokenF1', () => {
  it('identical => 1', () => expect(tokenF1('a b c', 'a b c')).toBe(1))
  it('disjoint => 0', () => expect(tokenF1('cat dog', 'fox hat')).toBe(0))
  it('partial overlap => harmonic mean', () => {
    const f = tokenF1('cat sat', 'cat sat mat')
    // prec 2/2, rec 2/3 -> F1 = 2*(1)*(2/3)/(1+2/3) = 4/5 = 0.8
    expect(f).toBeCloseTo(0.8, 5)
  })
})

describe('buildLexicalIndex', () => {
  const idx = buildLexicalIndex([
    { id: 'a', text: 'caroline went to the support group' },
    { id: 'b', text: 'melanie painted a sunrise by the lake' },
  ])
  it('cosine of identical doc is 1', () => {
    const q = idx.querySparse('caroline went to the support group')
    expect(idx.cosine(q, 'a')).toBeCloseTo(1, 5)
  })
  it('cosine of different doc < 1', () => {
    const q = idx.querySparse('caroline went to the support group')
    expect(idx.cosine(q, 'b')).toBeLessThan(1)
  })
  it('dense cosine helper agrees on direction', () => {
    const a = idx.denseVec('a')
    const b = idx.denseVec('b')
    expect(cosine(a, a)).toBeCloseTo(1, 5)
    expect(cosine(a, b)).toBeLessThan(1)
  })
})
