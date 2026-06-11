/**
 * components/space/SpaceProvidersModal.vue 集成测试
 * （原 pages/spaces/[id]/providers.vue 集成测试，页面降级为弹窗后迁移至此）
 *
 * 覆盖场景：
 *   1. props.spaceId 透传给 ProviderSettings（scope='project' + embedded）
 *   2. 不同 spaceId 透传正确
 *   3. open=false 时不渲染 ProviderSettings（v-if 惰性加载）
 *
 * ProviderSettings 用 stub 替换，仅验证 props 注入；
 * 实际容器行为由 /admin/providers 的 spec 覆盖。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SpaceProvidersModal from '../SpaceProvidersModal.vue'

// ============================================================================
// Mock：API + toast（避免 ProviderSettings 真正 mount 时拉数据）
// ============================================================================

vi.mock('~/api/providerCredentials', () => ({
  providerCredentialsApi: {
    list: vi.fn().mockResolvedValue([]),
    retrieve: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    toggleActive: vi.fn(),
    testConnection: vi.fn(),
    refreshModels: vi.fn(),
    listProviderTypes: vi.fn().mockResolvedValue([]),
  },
}))

vi.mock('vue-sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  }),
}))

// ProviderSettings stub：只暴露 props，不做实际渲染逻辑
// （vi.mock factory 会被 hoist，stub 定义必须放在 factory 内部）
vi.mock('~/components/providers/ProviderSettings.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      name: 'ProviderSettings',
      props: {
        scope: { type: String, required: true },
        spaceId: { type: String, default: '' },
        embedded: { type: Boolean, default: false },
      },
      setup(props) {
        return () =>
          h('div', {
            'class': 'stub-provider-settings',
            'data-scope': props.scope,
            'data-space-id': props.spaceId,
            'data-embedded': String(props.embedded),
          })
      },
    }),
  }
})

// Dialog 全家桶 passthrough stub，绕开 reka-ui Teleport
function PassthroughStub(name: string) {
  return {
    name,
    template: `<div data-stub="${name}"><slot /></div>`,
  }
}

function mountModal(spaceId: string, open = true) {
  return mount(SpaceProvidersModal, {
    props: { spaceId, open },
    global: {
      stubs: {
        Dialog: PassthroughStub('Dialog'),
        DialogContent: PassthroughStub('DialogContent'),
        DialogHeader: PassthroughStub('DialogHeader'),
        DialogTitle: PassthroughStub('DialogTitle'),
        DialogDescription: PassthroughStub('DialogDescription'),
      },
    },
  })
}

// ============================================================================
// Tests
// ============================================================================

describe('components/space/SpaceProvidersModal.vue', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('props.spaceId 透传给 ProviderSettings scope=project + embedded（后端 ProviderCredential.scope enum 仍是 project）', async () => {
    const wrapper = mountModal('p-123')
    await flushPromises()

    const stub = wrapper.find('.stub-provider-settings')
    expect(stub.exists()).toBe(true)
    expect(stub.attributes('data-scope')).toBe('project')
    expect(stub.attributes('data-space-id')).toBe('p-123')
    expect(stub.attributes('data-embedded')).toBe('true')
  })

  it('极端 spaceId（含连字符 / 数字）不被破坏，原值透传', async () => {
    const wrapper = mountModal('x-y-z-0001')
    await flushPromises()

    const stub = wrapper.find('.stub-provider-settings')
    expect(stub.attributes('data-space-id')).toBe('x-y-z-0001')
  })

  it('open=false 时不渲染 ProviderSettings（v-if 惰性加载）', async () => {
    const wrapper = mountModal('p-123', false)
    await flushPromises()

    expect(wrapper.find('.stub-provider-settings').exists()).toBe(false)
  })
})
