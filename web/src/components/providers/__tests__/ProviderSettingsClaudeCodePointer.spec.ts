import type { ProviderCredentialDto } from '~/types/providerCredential'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Claude Code 凭证指针在凭证管理页的可见性。
 *
 * 背景（真实事故）：用户把新 API Key 填进 A 凭证，以为编码容器立刻换了钥匙；
 * 实际 claude_code_config 指针还指着 B 凭证，容器继续用旧账号跑，连着两轮失败，
 * 而界面上没有任何线索能看出「你改的不是它在用的那把钥匙」。
 */

const listMock = vi.fn()
const listProviderTypesMock = vi.fn()
const getClaudeCodeConfigMock = vi.fn()

vi.mock('~/api/providerCredentials', () => ({
  providerCredentialsApi: {
    list: (...args: unknown[]) => listMock(...args),
    listProviderTypes: (...args: unknown[]) => listProviderTypesMock(...args),
    getClaudeCodeConfig: (...args: unknown[]) => getClaudeCodeConfigMock(...args),
  },
}))

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))

vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))

const ProviderSettings = (await import('~/components/providers/ProviderSettings.vue')).default
const ProviderCredentialListTable = (
  await import('~/components/providers/ProviderCredentialListTable.vue')
).default

function makeCred(overrides: Partial<ProviderCredentialDto> = {}): ProviderCredentialDto {
  return {
    id: overrides.id ?? 'cred-a',
    provider_type: overrides.provider_type ?? 'anthropic',
    name: overrides.name ?? 'anthropic-a',
    scope: overrides.scope ?? 'system',
    scope_id: overrides.scope_id ?? null,
    is_active: overrides.is_active ?? true,
    is_default: overrides.is_default ?? false,
    last_health_check_at: overrides.last_health_check_at ?? null,
    last_health_check_status: overrides.last_health_check_status ?? '',
    last_health_check_error: overrides.last_health_check_error ?? '',
    available_models: overrides.available_models ?? [],
    api_key_last4: overrides.api_key_last4 ?? '...abcd',
    has_api_key: overrides.has_api_key ?? true,
    config: overrides.config ?? {},
    default_model: overrides.default_model ?? '',
    max_concurrency: overrides.max_concurrency ?? 50,
    created_at: overrides.created_at ?? '2026-06-01T00:00:00Z',
    updated_at: overrides.updated_at ?? '2026-06-01T00:00:00Z',
  }
}

function mountSettings() {
  return mount(ProviderSettings, {
    props: { scope: 'system' as const },
    global: {
      stubs: {
        Select: { template: '<div><slot /></div>' },
        SelectTrigger: { template: '<button type="button"><slot /></button>' },
        SelectValue: { props: ['placeholder'], template: '<span>{{ placeholder }}</span>' },
        SelectContent: { template: '<div><slot /></div>' },
        SelectItem: { props: ['value'], template: '<div><slot /></div>' },
      },
    },
  })
}

describe('providerSettings — Claude Code 凭证指针提示', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    document.body.innerHTML = ''
    vi.clearAllMocks()
    listProviderTypesMock.mockResolvedValue([])
    listMock.mockResolvedValue([
      makeCred({ id: 'cred-a', name: 'anthropic-a' }),
      makeCred({ id: 'cred-b', name: 'anthropic-b' }),
    ])
    getClaudeCodeConfigMock.mockResolvedValue({
      credential_id: 'cred-b',
      model_mapping: { opus: '', sonnet: '', haiku: '' },
      credential: null,
    })
  })

  it('指针指向的凭证行带「Claude Code 使用中」徽标，其他行没有', async () => {
    const wrapper = mountSettings()
    await flushPromises()

    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).not.toContain('Claude Code 使用中')
    expect(rows[1].text()).toContain('Claude Code 使用中')
  })

  it('取不到指针时不渲染徽标，也不影响列表', async () => {
    getClaudeCodeConfigMock.mockRejectedValue(new Error('boom'))

    const wrapper = mountSettings()
    await flushPromises()

    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(wrapper.text()).not.toContain('Claude Code 使用中')
  })

  it('编辑非当前凭证时明示不会影响 Claude Code 编码容器', async () => {
    const wrapper = mountSettings()
    await flushPromises()
    const table = wrapper.findComponent(ProviderCredentialListTable)

    table.vm.$emit('edit', makeCred({ id: 'cred-a', name: 'anthropic-a' }))
    await flushPromises()

    expect(document.body.textContent).toContain('Claude Code 编码容器当前使用的是')
    expect(document.body.textContent).toContain('anthropic-b')
    expect(document.body.textContent).toContain('改这里不会影响编码容器')
  })
})
