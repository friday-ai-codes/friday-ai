import type { ProviderCredentialDto } from '~/types/providerCredential'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listMock = vi.fn()
const listProviderTypesMock = vi.fn()
const getClaudeCodeConfigMock = vi.fn()
const updateClaudeCodeConfigMock = vi.fn()

vi.mock('~/api/providerCredentials', () => ({
  providerCredentialsApi: {
    list: (...args: unknown[]) => listMock(...args),
    listProviderTypes: (...args: unknown[]) => listProviderTypesMock(...args),
    getClaudeCodeConfig: (...args: unknown[]) => getClaudeCodeConfigMock(...args),
    updateClaudeCodeConfig: (...args: unknown[]) => updateClaudeCodeConfigMock(...args),
  },
}))

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))

vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))

const ClaudeCodeConfigPanel = (
  await import('~/components/providers/ClaudeCodeConfigPanel.vue')
).default

function makeCred(overrides: Partial<ProviderCredentialDto> = {}): ProviderCredentialDto {
  return {
    id: overrides.id ?? 'cred-anth',
    provider_type: overrides.provider_type ?? 'anthropic',
    name: overrides.name ?? 'anthropic-prod',
    scope: overrides.scope ?? 'system',
    scope_id: overrides.scope_id ?? null,
    is_active: overrides.is_active ?? true,
    is_default: overrides.is_default ?? false,
    last_health_check_at: overrides.last_health_check_at ?? null,
    last_health_check_status: overrides.last_health_check_status ?? '',
    last_health_check_error: overrides.last_health_check_error ?? '',
    available_models: overrides.available_models ?? [
      { id: 'claude-sonnet-4', display_name: 'Claude Sonnet 4' },
    ],
    api_key_last4: overrides.api_key_last4 ?? '...abcd',
    has_api_key: overrides.has_api_key ?? true,
    config: overrides.config ?? {},
    default_model: overrides.default_model ?? 'claude-sonnet-4',
    max_concurrency: overrides.max_concurrency ?? 50,
    created_at: overrides.created_at ?? '2026-06-01T00:00:00Z',
    updated_at: overrides.updated_at ?? '2026-06-01T00:00:00Z',
  }
}

const selectStubs = {
  Select: { template: '<div><slot /></div>' },
  SelectTrigger: { template: '<button type="button"><slot /></button>' },
  SelectValue: { props: ['placeholder'], template: '<span>{{ placeholder }}</span>' },
  SelectContent: { template: '<div><slot /></div>' },
  SelectItem: { props: ['value'], template: '<div><slot /></div>' },
}

describe('claudeCodeConfigPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    vi.clearAllMocks()
    listProviderTypesMock.mockResolvedValue([])
    getClaudeCodeConfigMock.mockResolvedValue({
      credential_id: 'cred-anth',
      model_mapping: { opus: '', sonnet: 'claude-sonnet-4', haiku: '' },
      credential: null,
    })
  })

  it('凭证候选只渲染 anthropic provider', async () => {
    listMock.mockResolvedValue([
      makeCred({ id: 'cred-anth', name: 'anthropic-prod', provider_type: 'anthropic' }),
      makeCred({
        id: 'cred-openai',
        name: 'openai-prod',
        provider_type: 'openai_chat',
        available_models: [{ id: 'gpt-4o', display_name: 'GPT-4o' }],
        default_model: 'gpt-4o',
      }),
    ])

    const wrapper = mount(ClaudeCodeConfigPanel, {
      global: { stubs: selectStubs },
    })
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('anthropic-prod · anthropic')
    expect(text).not.toContain('openai-prod · openai_chat')
  })

  it('回显时剥 [1m] 后缀还原勾选态，保存时重新拼后缀', async () => {
    listMock.mockResolvedValue([
      makeCred({
        id: 'cred-anth',
        available_models: [
          { id: 'deepseek-v4-pro', display_name: 'DeepSeek V4 Pro' },
          { id: 'deepseek-v4-flash', display_name: 'DeepSeek V4 Flash' },
        ],
        default_model: 'deepseek-v4-pro',
      }),
    ])
    getClaudeCodeConfigMock.mockResolvedValue({
      credential_id: 'cred-anth',
      model_mapping: {
        opus: 'deepseek-v4-pro[1m]',
        sonnet: 'deepseek-v4-pro[1m]',
        haiku: 'deepseek-v4-flash',
      },
      credential: null,
    })
    updateClaudeCodeConfigMock.mockResolvedValue({})

    const wrapper = mount(ClaudeCodeConfigPanel, {
      global: { stubs: selectStubs },
    })
    await flushPromises()

    // 回显：mapping 存基础模型 ID，1M 勾选态从后缀还原
    const vm = wrapper.vm as any
    expect(vm.mapping).toEqual({
      opus: 'deepseek-v4-pro',
      sonnet: 'deepseek-v4-pro',
      haiku: 'deepseek-v4-flash',
    })
    expect(vm.contextFlags).toEqual({ opus: true, sonnet: true, haiku: false })

    // 保存：勾选档重新拼 [1m] 后缀
    const saveButton = wrapper.findAll('button').find(b => b.text().includes('保存配置'))
    expect(saveButton).toBeTruthy()
    await saveButton!.trigger('click')
    await flushPromises()
    expect(updateClaudeCodeConfigMock).toHaveBeenCalledWith({
      credential_id: 'cred-anth',
      model_mapping: {
        opus: 'deepseek-v4-pro[1m]',
        sonnet: 'deepseek-v4-pro[1m]',
        haiku: 'deepseek-v4-flash',
      },
    })
  })

  it('所选 anthropic 凭证无模型列表时不渲染手动输入框', async () => {
    listMock.mockResolvedValue([
      makeCred({
        id: 'cred-empty',
        name: 'empty-anthropic',
        provider_type: 'anthropic',
        available_models: [],
        default_model: '',
      }),
    ])
    getClaudeCodeConfigMock.mockResolvedValue({
      credential_id: 'cred-empty',
      model_mapping: { opus: '', sonnet: '', haiku: '' },
      credential: null,
    })

    const wrapper = mount(ClaudeCodeConfigPanel, {
      global: { stubs: selectStubs },
    })
    await flushPromises()

    expect(wrapper.find('input').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('手动输入模型名')
    expect(wrapper.text()).toContain('请先在 Provider 凭证中添加或刷新模型')
  })
})
