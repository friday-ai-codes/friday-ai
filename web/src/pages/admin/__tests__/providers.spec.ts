/**
 * - /admin/providers 页面集成测试
 *
 * 通过 mount ProviderSettings 直接验证容器行为（/admin/providers/index.vue 本身仅是
 * 1 行 <ProviderSettings scope="system" /> 挂载器，逻辑全在容器组件内）。
 *
 * 覆盖场景：
 * - 挂载后按 mock list 渲染 2 凭证（行数 / 内容）
 * - 点击"新建凭证" → Dialog 打开并渲染"新建 Provider 凭证"标题
 * - 空态（credentials=[]）渲染 key-round 图标 + 系统级文案 + CTA
 * - scope=project 空态切换为 folder-lock + "本项目暂未配置覆盖凭证"
 * - PageHeader 标题按 scope 切换
 *
 * 不覆盖（交由 E2E smoke test）：
 * - 表单内字段填写 → 提交后的完整 create 流程
 * - AlertDialog 确认后 store.deleteCredential 物理调用（涉及 teleport + reka-ui 异步渲染）
 */
import type { ProviderCredentialDto } from '~/types/providerCredential'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// ============================================================================
// Mock：API client + toast composable
// ============================================================================

const listMock = vi.fn()
const createMock = vi.fn()
const updateMock = vi.fn()
const removeMock = vi.fn()
const toggleActiveMock = vi.fn()
const testConnectionMock = vi.fn()
const refreshModelsMock = vi.fn()
const listProviderTypesMock = vi.fn().mockResolvedValue([])

vi.mock('~/api/providerCredentials', () => ({
  providerCredentialsApi: {
    list: (...a: unknown[]) => listMock(...a),
    retrieve: vi.fn(),
    create: (...a: unknown[]) => createMock(...a),
    update: (...a: unknown[]) => updateMock(...a),
    remove: (...a: unknown[]) => removeMock(...a),
    toggleActive: (...a: unknown[]) => toggleActiveMock(...a),
    testConnection: (...a: unknown[]) => testConnectionMock(...a),
    refreshModels: (...a: unknown[]) => refreshModelsMock(...a),
    listProviderTypes: (...a: unknown[]) => listProviderTypesMock(...a),
  },
}))

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  }),
}))

// ============================================================================
// Fixtures
// ============================================================================

function makeCred(overrides: Partial<ProviderCredentialDto> = {}): ProviderCredentialDto {
  return {
    id: overrides.id ?? 'c1',
    provider_type: overrides.provider_type ?? 'anthropic',
    name: overrides.name ?? 'anth-prod',
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
    default_model: overrides.default_model ?? 'claude-3-5-sonnet-20241022',
    max_concurrency: overrides.max_concurrency ?? 50,
    created_at: overrides.created_at ?? '2026-04-20T00:00:00Z',
    updated_at: overrides.updated_at ?? '2026-04-20T00:00:00Z',
  }
}

// dynamic import：确保 vi.mock hoist 完成后再加载组件（与 prompts.test.ts 同风格）
const ProviderSettings = (
  await import('~/components/providers/ProviderSettings.vue')
).default

// ============================================================================
// Tests
// ============================================================================

describe('/admin/providers ProviderSettings 集成', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    vi.clearAllMocks()
    listProviderTypesMock.mockResolvedValue([])
  })

  it('mount 后按 mock list 渲染 2 条凭证，表格内含 name', async () => {
    listMock.mockResolvedValue([
      makeCred({ id: 'c1', name: 'anth-prod' }),
      makeCred({ id: 'c2', name: 'oai-prod', provider_type: 'openai_chat' }),
    ])
    const wrapper = mount(ProviderSettings, {
      props: { scope: 'system' },
      attachTo: document.body,
      global: { stubs: { RouterLink: true } },
    })
    await flushPromises()

    expect(listMock).toHaveBeenCalledTimes(1)
    const text = wrapper.text()
    expect(text).toContain('anth-prod')
    expect(text).toContain('oai-prod')
  })

  it('点击"新建凭证"按钮后 Dialog 渲染"新建 Provider 凭证"标题', async () => {
    listMock.mockResolvedValue([makeCred({ name: 'first' })])
    const wrapper = mount(ProviderSettings, {
      props: { scope: 'system' },
      attachTo: document.body,
      global: { stubs: { RouterLink: true } },
    })
    await flushPromises()

    const buttons = wrapper.findAll('button')
    const newBtn = buttons.find(b => b.text().includes('新建凭证'))
    expect(newBtn).toBeDefined()

    await newBtn!.trigger('click')
    await flushPromises()

    // Dialog 打开后 DialogTitle 渲染至 document.body（reka-ui Teleport）
    expect(document.body.innerHTML).toContain('新建 Provider 凭证')
    wrapper.unmount()
  })

  it('空态（credentials=[] + scope=system）渲染 key-round 图标 + 文案 + CTA', async () => {
    listMock.mockResolvedValue([])
    const wrapper = mount(ProviderSettings, {
      props: { scope: 'system' },
      attachTo: document.body,
      global: { stubs: { RouterLink: true } },
    })
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('尚未配置任何 Provider 凭证')
    expect(text).toContain('新建凭证')
    expect(wrapper.html()).toContain('icon-[lucide--key-round]')
  })

  it('scope=project 空态切换为 folder-lock + "本空间暂未配置覆盖凭证" + "新建空间凭证"', async () => {
    listMock.mockResolvedValue([])
    const wrapper = mount(ProviderSettings, {
      props: { scope: 'project', projectId: 'p-1' },
      attachTo: document.body,
      global: { stubs: { RouterLink: true } },
    })
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('本空间暂未配置覆盖凭证')
    expect(text).toContain('新建空间凭证')
    expect(wrapper.html()).toContain('icon-[lucide--folder-lock]')
  })

  it('pageHeader 标题按 scope 切换：system=Provider 凭证管理，project=Provider 凭证', async () => {
    listMock.mockResolvedValue([makeCred({ name: 'c-sys' })])
    const sysWrapper = mount(ProviderSettings, {
      props: { scope: 'system' },
      attachTo: document.body,
      global: { stubs: { RouterLink: true } },
    })
    await flushPromises()
    expect(sysWrapper.text()).toContain('Provider 凭证管理')

    // 重置 mock 以避免跨 wrapper 干扰
    listMock.mockResolvedValue([makeCred({ name: 'c-proj' })])
    setActivePinia(createPinia())
    sessionStorage.clear()

    const projWrapper = mount(ProviderSettings, {
      props: { scope: 'project', projectId: 'p-2' },
      attachTo: document.body,
      global: { stubs: { RouterLink: true } },
    })
    await flushPromises()
    const projText = projWrapper.text()
    expect(projText).toContain('Provider 凭证')
    // 项目级不含完整"Provider 凭证管理"长标题
    expect(projText).not.toContain('Provider 凭证管理')
  })

  it('listTable emits delete 后打开 AlertDialog 并显示凭证名与"永久删除"按钮', async () => {
    listMock.mockResolvedValue([makeCred({ id: 'c-del', name: 'to-delete' })])
    const wrapper = mount(ProviderSettings, {
      props: { scope: 'system' },
      attachTo: document.body,
      global: { stubs: { RouterLink: true } },
    })
    await flushPromises()

    // 通过子组件 emit 触发容器 onDelete（模拟 ListTable 的删除菜单点击）
    const listTable = wrapper.findComponent({ name: 'ProviderCredentialListTable' })
    expect(listTable.exists()).toBe(true)
    listTable.vm.$emit('delete', makeCred({ id: 'c-del', name: 'to-delete' }))
    await flushPromises()

    // AlertDialog 内容被 reka-ui Teleport 到 document.body
    const bodyHtml = document.body.innerHTML
    expect(bodyHtml).toContain('删除此凭证？')
    expect(bodyHtml).toContain('to-delete')
    expect(bodyHtml).toContain('永久删除')
    wrapper.unmount()
  })
})
