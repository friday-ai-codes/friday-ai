/**
 * — providerBrandColors.ts 单测。
 *
 * 契约（UI-SPEC §Color L112-141 + D-12 锁定）：
 * - 5 ProviderType × 3 字段 {bg, text, hex}
 * - Anthropic orange / OpenAI emerald / Gemini blue / Ollama slate
 * - PROVIDER_BRAND_HEX_ORDERED 按字典序 5 项
 */
import { describe, expect, it } from 'vitest'
import {
  getProviderBrandColor,
  PROVIDER_BRAND_COLORS,
  PROVIDER_BRAND_HEX_ORDERED,
  UNKNOWN_PROVIDER_COLOR,
} from '~/lib/providerBrandColors'

describe('providerBrandColors', () => {
  it('a: Anthropic 品牌色为 orange-500 / #f97316', () => {
    expect(PROVIDER_BRAND_COLORS.anthropic.hex).toBe('#f97316')
    expect(PROVIDER_BRAND_COLORS.anthropic.bg).toBe('bg-orange-500/20')
    expect(PROVIDER_BRAND_COLORS.anthropic.text).toBe('text-orange-600')
  })

  it('b: Gemini 品牌色为 blue-500 / #3b82f6', () => {
    expect(PROVIDER_BRAND_COLORS.gemini.hex).toBe('#3b82f6')
    expect(PROVIDER_BRAND_COLORS.gemini.text).toBe('text-blue-600')
  })

  it('c: 导出 PROVIDER_BRAND_HEX_ORDERED，长度 5，字典序', () => {
    expect(PROVIDER_BRAND_HEX_ORDERED).toHaveLength(5)
    // 字典序：anthropic → gemini → ollama → openai_chat → openai_responses
    expect(PROVIDER_BRAND_HEX_ORDERED[0]).toBe('#f97316') // anthropic
    expect(PROVIDER_BRAND_HEX_ORDERED[1]).toBe('#3b82f6') // gemini
    expect(PROVIDER_BRAND_HEX_ORDERED[2]).toBe('#64748b') // ollama
  })

  it('d: 5 ProviderType × 3 字段全覆盖', () => {
    const providers = ['anthropic', 'openai_chat', 'openai_responses', 'gemini', 'ollama'] as const
    for (const p of providers) {
      const color = PROVIDER_BRAND_COLORS[p]
      expect(color.bg).toBeTruthy()
      expect(color.text).toBeTruthy()
      expect(color.hex).toMatch(/^#[0-9a-f]{6}$/i)
    }
  })

  it('e: getProviderBrandColor 未知 provider 回退到 UNKNOWN_PROVIDER_COLOR', () => {
    expect(getProviderBrandColor(null)).toBe(UNKNOWN_PROVIDER_COLOR)
    expect(getProviderBrandColor(undefined)).toBe(UNKNOWN_PROVIDER_COLOR)
    expect(getProviderBrandColor('nonexistent_provider')).toBe(UNKNOWN_PROVIDER_COLOR)
    // 已知 provider 返回对应色
    expect(getProviderBrandColor('anthropic')).toEqual(PROVIDER_BRAND_COLORS.anthropic)
  })
})
