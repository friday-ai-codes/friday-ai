/**
 * 澄清题工具函数单测（quick-260806-fy2）。
 */
import { describe, expect, it } from 'vitest'
import {
  extractFeaturePointIds,
  formatClarificationAnswers,
  isStructuredClarificationQuestions,
  normalizeClarificationQuestions,
} from '../clarificationQuestions'

describe('isStructuredClarificationQuestions', () => {
  it('结构化 {text, options} ⇒ true', () => {
    expect(isStructuredClarificationQuestions([
      { text: '弱网如何恢复？', options: ['续计', '重置'] },
    ])).toBe(true)
  })

  it('兼容 question 键', () => {
    expect(isStructuredClarificationQuestions([
      { question: '范围？', options: [] },
    ])).toBe(true)
  })

  it('扁平 {label,value} ⇒ false', () => {
    expect(isStructuredClarificationQuestions([
      { label: '方案 A', value: 'A' },
      { label: '方案 B', value: 'B' },
    ])).toBe(false)
  })

  it('空 / 非法 ⇒ false', () => {
    expect(isStructuredClarificationQuestions([])).toBe(false)
    expect(isStructuredClarificationQuestions(null)).toBe(false)
    expect(isStructuredClarificationQuestions([{ text: '   ' }])).toBe(false)
  })
})

describe('normalizeClarificationQuestions', () => {
  it('保留 recommended 与 related，丢非法 recommended', () => {
    const rows = normalizeClarificationQuestions([
      {
        text: 'q1',
        options: ['A', 'B'],
        recommended: 'A',
        related_feature_points: ['fp_1', '', 'fp_2'],
      },
      {
        question: 'q2',
        options: ['X'],
        recommended: 'Y',
      },
    ])
    expect(rows).toEqual([
      {
        text: 'q1',
        options: ['A', 'B'],
        recommended: 'A',
        related_feature_points: ['fp_1', 'fp_2'],
        citations: [],
      },
      {
        text: 'q2',
        options: ['X'],
        recommended: '',
        related_feature_points: [],
        citations: [],
      },
    ])
  })
})

describe('extractFeaturePointIds', () => {
  it('合并 related 与题面 fp_*，去重保序', () => {
    expect(extractFeaturePointIds(
      '关于 fp_27 与 fp_28，以及再次提到的 fp_27',
      ['fp_18', 'fp_27'],
    )).toEqual(['fp_18', 'fp_27', 'fp_28'])
  })
})

describe('formatClarificationAnswers', () => {
  it('打包为编号题 + 箭头答', () => {
    expect(formatClarificationAnswers([
      { question: '范围？', answer: '仅实验组' },
      { question: '恢复？', answer: '续计' },
    ])).toBe('1. 范围？\n→ 仅实验组\n\n2. 恢复？\n→ 续计')
  })
})
