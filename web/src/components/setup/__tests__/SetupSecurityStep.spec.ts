import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

const getSecurityCheckMock = vi.fn()
vi.mock('~/api/setup', () => ({
  getSecurityCheck: () => getSecurityCheckMock(),
}))

const SetupSecurityStep = (await import('~/components/setup/SetupSecurityStep.vue')).default

beforeEach(() => {
  getSecurityCheckMock.mockReset()
})

describe('setupSecurityStep', () => {
  it('shows all-clear and a non-disabled continue button when secure', async () => {
    getSecurityCheckMock.mockResolvedValueOnce({
      secure: true,
      secret_key_secure: true,
      encryption_key_set: true,
      keys_independent: true,
      risks: [],
    })
    const wrapper = mount(SetupSecurityStep)
    await flushPromises()

    expect(wrapper.text()).toContain('setup.security.allClear')
    const btn = wrapper.find('button')
    expect(btn.attributes('disabled')).toBeUndefined()
  })

  it('renders risk items but keeps continue clickable (non-blocking)', async () => {
    getSecurityCheckMock.mockResolvedValueOnce({
      secure: false,
      secret_key_secure: false,
      encryption_key_set: false,
      keys_independent: false,
      risks: [
        { code: 'secret_key_default', level: 'warning' },
        { code: 'encryption_key_unset', level: 'warning' },
      ],
    })
    const wrapper = mount(SetupSecurityStep)
    await flushPromises()

    expect(wrapper.text()).toContain('setup.security.riskTitle')
    expect(wrapper.text()).toContain('setup.security.risk.secretKeyDefault')
    expect(wrapper.text()).toContain('setup.security.risk.encryptionKeyUnset')

    const btn = wrapper.find('button')
    expect(btn.attributes('disabled')).toBeUndefined()
    await btn.trigger('click')
    expect(wrapper.emitted('continue')).toBeTruthy()
  })

  it('falls back to unavailable note and still allows continue on fetch error', async () => {
    getSecurityCheckMock.mockRejectedValueOnce(new Error('500'))
    const wrapper = mount(SetupSecurityStep)
    await flushPromises()

    expect(wrapper.text()).toContain('setup.security.unavailable')
    const btn = wrapper.find('button')
    await btn.trigger('click')
    expect(wrapper.emitted('continue')).toBeTruthy()
  })
})
