/**
 * ChatInput model-selector 折叠重构vitest
 *
 * 验证 4 个核心契约：
 *   1. credentialModelOptions 列「凭证/模型」组合（基于 activeCredentials × available_models）
 *   2. 选不同组合 → 弹 PinConfirmDialog（pinDialogOpen=true）
 *   3. PinConfirmDialog confirm → emit('pin-confirmed', credentialId, model)
 *   4. activeCredentials 空时 → model-selector disabled + 「无可用 Provider」 渲染
 */
import type { ProviderCredentialDto } from '~/types/providerCredential'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import ChatInput from '~/components/chat/ChatInput.vue'
import { useChatStore } from '~/stores/chat'
import { useProviderCredentialStore } from '~/stores/providerCredential'

const toastSpies = vi.hoisted(() => ({
  error: vi.fn(),
  warning: vi.fn(),
  success: vi.fn(),
  info: vi.fn(),
}))

vi.mock('~/composables/useToast', () => ({
  useToast: () => toastSpies,
}))

vi.mock('~/composables/usePermission', () => ({
  usePermission: () => ({
    isSystemAdmin: { value: false },
    canEdit: { value: false },
    isAdmin: { value: false },
    isMember: { value: false },
    isViewer: { value: false },
    isAuthenticated: { value: true },
    spaceRole: { value: null },
  }),
}))

// 引入了 watch( => route.query.prefilled_query, ...) 自动填充逻辑，
// 旧测试默认走 happy-dom 没有 vue-router 上下文，需在此 mock 出 route。
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {}, path: '/', meta: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

function makeCredential(
  overrides: Partial<ProviderCredentialDto> = {},
): ProviderCredentialDto {
  return {
    id: 'cred-1',
    provider_type: 'anthropic',
    name: 'anthropic-prod',
    scope: 'system',
    scope_id: null,
    is_active: true,
    is_default: false,
    last_health_check_at: null,
    last_health_check_status: '',
    last_health_check_error: '',
    available_models: [
      { id: 'claude-sonnet-4', display_name: 'Claude Sonnet 4' },
    ],
    api_key_last4: 'xxxx',
    has_api_key: true,
    config: {},
    default_model: 'claude-3-5-sonnet-20241022',
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    ...overrides,
  }
}

const PinDialogStub = defineComponent({
  name: 'PinConfirmDialog',
  props: ['open', 'oldProviderName', 'oldModel', 'newProviderName', 'newModel', 'messageCount'],
  emits: ['update:open', 'confirm', 'cancel'],
  setup(props, { emit }) {
    return () =>
      h(
        'div',
        {
          'data-test': 'pin-dialog',
          'data-open': props.open ? 'true' : 'false',
          'data-new-provider': props.newProviderName,
          'data-new-model': props.newModel,
        },
        [
          h(
            'button',
            {
              'data-test': 'pin-confirm',
              'onClick': () => emit('confirm'),
            },
            'confirm',
          ),
        ],
      )
  },
})

describe('chatInput model-selector 折叠重构（260423-lum）', () => {
  beforeEach(() => {
    const storage = {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
    }
    Object.defineProperty(window, 'localStorage', {
      value: storage,
      configurable: true,
    })
    Object.defineProperty(globalThis, 'localStorage', {
      value: storage,
      configurable: true,
    })
    setActivePinia(createPinia())
    toastSpies.error.mockReset()
    toastSpies.warning.mockReset()
    toastSpies.success.mockReset()
    toastSpies.info.mockReset()
    const ps = useProviderCredentialStore()
    vi.spyOn(ps, 'fetchCredentials').mockResolvedValue([])
    vi.spyOn(ps, 'fetchProviderTypes').mockResolvedValue([])
  })

  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  function mountWithCredentials(
    creds: ProviderCredentialDto[],
    conversation: Record<string, unknown> | null = null,
  ) {
    const ps = useProviderCredentialStore()
    ps.credentials = creds
    const cs = useChatStore()
    if (conversation) {
      type StoreConversation = typeof cs.conversations[number]
      cs.conversations = [conversation as StoreConversation]
      cs.currentConversationId = conversation.id as string
    }
    // Tooltip 系列用 slot-rendering stub（true stub 会吞掉 default slot
    // 内容，导致 .model-selector--disabled button 不渲染）。
    const SlotStub = (name: string) =>
      defineComponent({
        name,
        setup(_, { slots }) {
          return () => h('div', { 'data-stub': name }, slots.default?.())
        },
      })
    return mount(ChatInput, {
      global: {
        stubs: {
          PinConfirmDialog: PinDialogStub,
          BranchCombobox: true,
          Tooltip: SlotStub('Tooltip'),
          TooltipProvider: SlotStub('TooltipProvider'),
          TooltipContent: SlotStub('TooltipContent'),
          TooltipTrigger: SlotStub('TooltipTrigger'),
          RouterLink: SlotStub('RouterLink'),
          Transition: false,
          // 模型弹层 Teleport 到 body；测试中原地渲染以便 wrapper 查询 .model-menu-item
          teleport: true,
        },
      },
    })
  }

  it('① credentialModelOptions 列出「凭证/模型」组合', async () => {
    const cred1 = makeCredential({
      id: 'c1',
      name: 'anthropic-prod',
      available_models: [
        { id: 'claude-sonnet-4', display_name: 'Sonnet 4' },
        { id: 'claude-opus-4', display_name: 'Opus 4' },
      ],
    })
    const cred2 = makeCredential({
      id: 'c2',
      name: 'anthropic-dev',
      scope: 'project',
      scope_id: 'proj-1',
      available_models: [{ id: 'claude-sonnet-4', display_name: 'Sonnet 4' }],
    })
    const conv = {
      id: 'conv-1',
      space_id: 'proj-1',
      title: 't',
      model: 'claude-sonnet-4',
      status: 'running',
      provider_credential_id: 'c1',
      created_at: '',
      updated_at: '',
    }
    const wrapper = mountWithCredentials([cred1, cred2], conv)
    await nextTick()
    await wrapper.find('.model-selector').trigger('click')
    await nextTick()
    // 菜单已重构为「按凭证分组」：每组 header 展示凭证名（.model-group__name），
    // 组内每行（.model-row）展示模型 id。3 行 = cred1(2 模型) + cred2(1 模型)。
    const items = wrapper.findAll('.model-row')
    expect(items.length).toBe(3)
    const menuText = wrapper.find('.model-menu').text()
    expect(menuText).toContain('anthropic-prod')
    expect(menuText).toContain('anthropic-dev')
    expect(menuText).toContain('claude-sonnet-4')
    expect(menuText).toContain('claude-opus-4')
    wrapper.unmount()
  })

  it('② 选不同组合 → 弹 PinConfirmDialog', async () => {
    const cred = makeCredential({ id: 'c1', name: 'anthropic-prod' })
    const conv = {
      id: 'conv-1',
      space_id: 'proj-1',
      title: 't',
      model: 'claude-old',
      status: 'running',
      provider_credential_id: 'c0',
      created_at: '',
      updated_at: '',
    }
    const wrapper = mountWithCredentials([cred], conv)
    await nextTick()
    await wrapper.find('.model-selector').trigger('click')
    await nextTick()
    await wrapper.find('.model-row').trigger('click')
    await nextTick()
    const dialog = wrapper.find('[data-test="pin-dialog"]')
    expect(dialog.exists()).toBe(true)
    expect(dialog.attributes('data-open')).toBe('true')
    expect(dialog.attributes('data-new-provider')).toBe('anthropic-prod')
    expect(dialog.attributes('data-new-model')).toBe('claude-sonnet-4')
    wrapper.unmount()
  })

  it('③ PinConfirmDialog confirm → emit pin-confirmed (credentialId, model)', async () => {
    const cred = makeCredential({ id: 'c1' })
    const conv = {
      id: 'conv-1',
      space_id: 'proj-1',
      title: 't',
      model: 'claude-old',
      status: 'running',
      provider_credential_id: 'c0',
      created_at: '',
      updated_at: '',
    }
    const wrapper = mountWithCredentials([cred], conv)
    await nextTick()
    await wrapper.find('.model-selector').trigger('click')
    await nextTick()
    await wrapper.find('.model-row').trigger('click')
    await nextTick()
    await wrapper.find('[data-test="pin-confirm"]').trigger('click')
    await nextTick()
    const emitted = wrapper.emitted('pin-confirmed')
    expect(emitted).toBeTruthy()
    expect(emitted![0]).toEqual(['c1', 'claude-sonnet-4'])
    wrapper.unmount()
  })

  it('④ activeCredentials 空时 model-selector disabled + 显示「无可用 Provider」', async () => {
    const wrapper = mountWithCredentials([])
    await nextTick()
    const disabled = wrapper.find('.model-selector--disabled')
    expect(disabled.exists()).toBe(true)
    expect(disabled.text()).toContain('无可用 Provider')
    expect(disabled.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('⑤ 当前模型不支持图片时，粘贴图片提示不支持且不加入预览', async () => {
    const cred = makeCredential({
      id: 'c-deepseek',
      name: 'deepseek-anthropic',
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
    const wrapper = mountWithCredentials([cred])
    await nextTick()

    const image = new File(['png'], 'shot.png', { type: 'image/png' })
    const event = new Event('paste', { bubbles: true, cancelable: true }) as ClipboardEvent
    Object.defineProperty(event, 'clipboardData', {
      value: { files: [image] },
    })
    wrapper.find('.input-card').element.dispatchEvent(event)
    await nextTick()

    expect(event.defaultPrevented).toBe(true)
    expect(toastSpies.error).toHaveBeenCalledWith(
      '当前模型不支持图片',
      '请切换支持图片的模型后再粘贴或上传',
    )
    expect(wrapper.find('.image-preview-chip').exists()).toBe(false)
    wrapper.unmount()
  })
})
