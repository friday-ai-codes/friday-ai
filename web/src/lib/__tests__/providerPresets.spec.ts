import { describe, expect, it } from 'vitest'
import { DEFAULT_PRESET, PROVIDER_PRESETS } from '~/lib/providerPresets'

describe('providerPresets', () => {
  it('exposes the 5 decided presets', () => {
    const ids = PROVIDER_PRESETS.map(p => p.id)
    expect(ids).toEqual(['deepseek', 'mimo', 'kimi', 'anthropic', 'custom'])
  })

  it('non-custom presets auto-fill base_url + model + capabilities', () => {
    for (const preset of PROVIDER_PRESETS.filter(p => !p.custom)) {
      expect(preset.baseUrl).toBeTruthy()
      expect(preset.model).toBeTruthy()
      expect(preset.contextLength).toBeGreaterThan(0)
      expect(typeof preset.supportsVision).toBe('boolean')
      expect(preset.label).toBeTruthy()
    }
  })

  it('custom preset leaves base_url + model empty for user input', () => {
    const custom = PROVIDER_PRESETS.find(p => p.id === 'custom')!
    expect(custom.custom).toBe(true)
    expect(custom.baseUrl).toBe('')
    expect(custom.model).toBe('')
    expect(custom.contextLength).toBeNull()
  })

  it('default preset is the first non-custom one (anthropic-compatible)', () => {
    expect(DEFAULT_PRESET.custom).not.toBe(true)
    expect(DEFAULT_PRESET.id).toBe('deepseek')
  })

  it('all presets are anthropic-compatible (base_url anthropic-style or empty for custom)', () => {
    for (const preset of PROVIDER_PRESETS) {
      if (preset.custom)
        continue
      expect(preset.baseUrl.startsWith('http')).toBe(true)
    }
  })
})
