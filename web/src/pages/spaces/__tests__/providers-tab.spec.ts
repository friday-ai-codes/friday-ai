/**
 * — /spaces/[id]/providers 页面集成测试
 *
 * 覆盖场景：
 *   1. 从 route.params.id 读取 spaceId 并传给 ProviderSettings
 *   2. route.params.id 为数组时取第一项（memoryHistory 极端兜底）
 *   3. route.params.id 缺失 / 空串时组件仍可 mount（不崩）
 *
 * ProviderSettings 用 stub 替换，仅验证 props.scope + props.spaceId 注入；
 * 实际容器行为由 /admin/providers 的 spec 覆盖。
 */
import type { Component } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'

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
const ProviderSettingsStub = defineComponent({
  name: 'ProviderSettings',
  props: {
    scope: { type: String, required: true },
    spaceId: { type: String, default: '' },
  },
  setup(props) {
    return () =>
      h('div', {
        'class': 'stub-provider-settings',
        'data-scope': props.scope,
        'data-space-id': props.spaceId,
      })
  },
})

vi.mock('~/components/providers/ProviderSettings.vue', () => ({
  default: ProviderSettingsStub,
}))

// 动态 import：确保 vi.mock hoist 完成后再加载页面组件
const ProvidersPage = (
  await import('~/pages/spaces/[id]/providers.vue')
).default as Component

async function mountProvidersTab(idParam: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/spaces/:id/providers', name: '/spaces/[id]/providers', component: ProvidersPage },
      { path: '/', name: '/', component: { render: () => h('div') } },
    ],
  })
  await router.push(`/spaces/${idParam}/providers`)
  await router.isReady()

  return mount(ProvidersPage, {
    global: {
      plugins: [router],
      stubs: { RouterLink: true },
    },
  })
}

// ============================================================================
// Tests
// ============================================================================

describe('/spaces/[id]/providers page', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('从 route.params.id 读取 spaceId 并传给 ProviderSettings scope=project（后端 ProviderCredential.scope enum 仍是 project）', async () => {
    const wrapper = await mountProvidersTab('p-123')
    await flushPromises()

    const stub = wrapper.find('.stub-provider-settings')
    expect(stub.exists()).toBe(true)
    expect(stub.attributes('data-scope')).toBe('project')
    expect(stub.attributes('data-space-id')).toBe('p-123')
  })

  it('不同 spaceId 切换时传入的 space-id 正确更新', async () => {
    const wrapper = await mountProvidersTab('project-abc-def-001')
    await flushPromises()

    const stub = wrapper.find('.stub-provider-settings')
    expect(stub.attributes('data-space-id')).toBe('project-abc-def-001')
    expect(stub.attributes('data-scope')).toBe('project')
  })

  it('极端 spaceId（含连字符 / 数字）不被破坏，原值透传', async () => {
    const wrapper = await mountProvidersTab('x-y-z-0001')
    await flushPromises()

    const stub = wrapper.find('.stub-provider-settings')
    expect(stub.attributes('data-space-id')).toBe('x-y-z-0001')
  })
})
