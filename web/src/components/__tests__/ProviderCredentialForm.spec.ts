import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ProviderCredentialForm from '~/components/providers/ProviderCredentialForm.vue'

// ==== Mock store 模块（ 契约） ====
// 组件依赖 '~/stores/providerCredential' 与 '~/types/providerCredential'。
// 本 spec 走 mock 路径，不触 实际实现，也不触网络。
const mockProviderTypes = [
  {
    provider_type: 'anthropic',
    langchain_prefix: 'anthropic',
    supports_thinking: true,
    supports_reasoning: false,
    supports_vision: true,
    default_model: 'claude-opus-4-7',
    credential_schema_json_schema: {
      type: 'object',
      required: ['api_key'],
      properties: {
        api_key: {
          type: 'string',
          format: 'password',
          writeOnly: true,
          title: 'Api Key',
          description: 'Anthropic API Key',
          pattern: '^sk-ant-',
        },
        base_url: {
          type: 'string',
          format: 'uri',
          title: 'Base Url',
        },
      },
    },
  },
  {
    provider_type: 'openai_chat',
    langchain_prefix: 'openai',
    supports_thinking: false,
    supports_reasoning: true,
    supports_vision: true,
    default_model: 'gpt-4o',
    credential_schema_json_schema: {
      type: 'object',
      required: ['api_key'],
      properties: {
        api_key: { type: 'string', format: 'password', writeOnly: true, title: 'Api Key' },
        base_url: { type: 'string', title: 'Base Url' },
        organization_id: {
          anyOf: [{ type: 'string' }, { type: 'null' }],
          default: null,
          title: 'Organization Id',
        },
      },
    },
  },
  {
    provider_type: 'ollama',
    langchain_prefix: 'ollama',
    supports_thinking: false,
    supports_reasoning: false,
    supports_vision: false,
    default_model: null,
    credential_schema_json_schema: {
      type: 'object',
      required: ['base_url'],
      properties: {
        base_url: { type: 'string', format: 'uri', title: 'Base Url' },
        bearer_token: {
          anyOf: [
            { type: 'string', format: 'password', writeOnly: true },
            { type: 'null' },
          ],
          default: null,
          title: 'Bearer Token',
        },
      },
    },
  },
  {
    provider_type: 'gemini',
    langchain_prefix: 'google',
    supports_thinking: false,
    supports_reasoning: false,
    supports_vision: true,
    default_model: 'gemini-1.5-pro',
    credential_schema_json_schema: {
      type: 'object',
      required: ['api_key'],
      properties: {
        api_key: { type: 'string', format: 'password', writeOnly: true, title: 'Api Key' },
      },
    },
  },
  {
    provider_type: 'openai_responses',
    langchain_prefix: 'openai',
    supports_thinking: false,
    supports_reasoning: true,
    supports_vision: true,
    default_model: 'o1-mini',
    credential_schema_json_schema: {
      type: 'object',
      required: ['api_key'],
      properties: {
        api_key: { type: 'string', format: 'password', writeOnly: true, title: 'Api Key' },
        base_url: { type: 'string', title: 'Base Url' },
        organization_id: {
          anyOf: [{ type: 'string' }, { type: 'null' }],
          default: null,
          title: 'Organization Id',
        },
      },
    },
  },
]

vi.mock('~/stores/providerCredential', () => {
  return {
    useProviderCredentialStore: () => ({
      providerTypes: mockProviderTypes,
      fetchProviderTypes: vi.fn().mockResolvedValue(mockProviderTypes),
    }),
  }
})

// 由于 '~/types/providerCredential' 仅在 import type 处被使用（编译期擦除），
// 运行时无实际导入；mock 仍然无害，也避免解析警告。
vi.mock('~/types/providerCredential', () => ({}))

describe('providerCredentialForm', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('初始 provider_type=anthropic 渲染 Api Key + Base Url 2 个字段', async () => {
    const wrapper = mount(ProviderCredentialForm, { props: { mode: 'create' } })
    await flushPromises()
    const html = wrapper.html()
    expect(html).toContain('Api Key')
    expect(html).toContain('Base Url')
  })

  it('切换到 openai_chat 后渲染 Organization Id 字段', async () => {
    const wrapper = mount(ProviderCredentialForm, { props: { mode: 'create' } })
    await flushPromises()
    // defineExpose 暴露的 ref 在 wrapper.vm 上会被自动 unwrap 为字符串,直接赋值即可
    const exposed = wrapper.vm as unknown as { selectedType: string }
    exposed.selectedType = 'openai_chat'
    await flushPromises()
    expect(wrapper.html()).toContain('Organization Id')
  })

  it('切换到 ollama 渲染 Base Url + Bearer Token，Bearer 字段标注"(可选)"', async () => {
    const wrapper = mount(ProviderCredentialForm, { props: { mode: 'create' } })
    await flushPromises()
    const exposed = wrapper.vm as unknown as { selectedType: string }
    exposed.selectedType = 'ollama'
    await flushPromises()
    const html = wrapper.html()
    expect(html).toContain('Base Url')
    expect(html).toContain('Bearer Token')
    expect(html).toContain('(可选)')
  })

  it('敏感字段（api_key，writeOnly=true）默认渲染为 type=password', async () => {
    const wrapper = mount(ProviderCredentialForm, { props: { mode: 'create' } })
    await flushPromises()
    const passwordInputs = wrapper.findAll('input[type="password"]')
    expect(passwordInputs.length).toBeGreaterThanOrEqual(1)
  })

  it('edit 模式下敏感字段显示眼睛 toggle 按钮', async () => {
    const wrapper = mount(ProviderCredentialForm, {
      props: {
        mode: 'edit',
        initial: {
          id: 'e-1',
          provider_type: 'anthropic',
          name: 'existing',
          scope: 'system',
          scope_id: null,
          is_active: true,
          is_default: false,
          last_health_check_at: null,
          last_health_check_status: '',
          last_health_check_error: '',
          available_models: [],
          api_key_last4: '...abcd',
          has_api_key: true,
          config: {},
          default_model: 'claude-3-5-sonnet-20241022',
          max_concurrency: 50,
          created_at: '2026-04-20T00:00:00Z',
          updated_at: '2026-04-20T00:00:00Z',
        },
      },
    })
    await flushPromises()
    const html = wrapper.html()
    expect(html).toContain('icon-[lucide--eye]')
  })

  it('create 模式下敏感字段不显示眼睛 toggle（仅隐藏输入）', async () => {
    const wrapper = mount(ProviderCredentialForm, { props: { mode: 'create' } })
    await flushPromises()
    const html = wrapper.html()
    expect(html).not.toContain('icon-[lucide--eye]')
  })

  it('点击取消按钮触发 emit("cancel")', async () => {
    const wrapper = mount(ProviderCredentialForm, { props: { mode: 'create' } })
    await flushPromises()
    const cancelBtn = wrapper.findAll('button').find(b => b.text().includes('取消'))
    expect(cancelBtn).toBeDefined()
    await cancelBtn!.trigger('click')
    expect(wrapper.emitted('cancel')?.length).toBe(1)
  })

  it('create 模式手动输入模型时 submit payload 写入 available_models', async () => {
    const wrapper = mount(ProviderCredentialForm, { props: { mode: 'create' } })
    await flushPromises()

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('deepseek-anthropic')
    await inputs[1].setValue('sk-ant-validkey1234567890abcdef')
    await inputs[2].setValue('https://api.deepseek.com/anthropic')

    const manualBtn = wrapper.findAll('button').find(b => b.text().includes('手动输入模型名称'))
    expect(manualBtn).toBeDefined()
    await manualBtn!.trigger('click')
    await flushPromises()

    const modelInput = wrapper.findAll('input').at(-1)
    expect(modelInput).toBeDefined()
    await modelInput!.setValue('deepseek-v4-pro')

    await (wrapper.vm as unknown as { onSubmit: () => Promise<void> | void }).onSubmit()
    await flushPromises()

    const emitted = wrapper.emitted('submit')?.[0]?.[0] as Record<string, unknown>
    expect(emitted).toMatchObject({
      default_model: 'deepseek-v4-pro',
      available_models: [
        {
          id: 'deepseek-v4-pro',
          display_name: 'deepseek-v4-pro',
          input_modalities: ['text'],
          supports_vision: false,
        },
      ],
    })
  })

  it('常见模型自动带上下文预设（deepseek-v4 → 1M），并随 submit 写入 context_length', async () => {
    const wrapper = mount(ProviderCredentialForm, { props: { mode: 'create' } })
    await flushPromises()

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('deepseek-anthropic')
    await inputs[1].setValue('sk-ant-validkey1234567890abcdef')
    await inputs[2].setValue('https://api.deepseek.com/anthropic')

    const manualBtn = wrapper.findAll('button').find(b => b.text().includes('手动输入模型名称'))
    await manualBtn!.trigger('click')
    await flushPromises()
    const modelInput = wrapper.findAll('input').at(-1)
    await modelInput!.setValue('deepseek-v4-pro')

    await (wrapper.vm as unknown as { onSubmit: () => Promise<void> | void }).onSubmit()
    await flushPromises()

    const emitted = wrapper.emitted('submit')?.[0]?.[0] as Record<string, unknown>
    expect(emitted).toMatchObject({
      available_models: [
        { id: 'deepseek-v4-pro', context_length: 1_000_000 },
      ],
    })
  })

  it('所有 FormLabel 显式使用 font-normal 覆盖默认字重（UI-SPEC §Typography）', async () => {
    const wrapper = mount(ProviderCredentialForm, { props: { mode: 'create' } })
    await flushPromises()
    const labels = wrapper.findAll('label')
    // 至少 2 个固定 label（provider_type + name）+ 动态 config 字段应全部 font-normal
    expect(labels.length).toBeGreaterThanOrEqual(2)
    for (const l of labels)
      expect(l.classes()).toContain('font-normal')
  })
})
