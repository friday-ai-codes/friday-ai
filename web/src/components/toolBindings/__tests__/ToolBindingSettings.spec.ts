import type { AccessTokenDto } from '~/types/accessToken'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// 工具令牌绑定管理界面（10-04 将创建）。导入路径与 10-04 产物完全一致：
// 组件未实现时 import 失败即 RED（符合 Wave 0 预期）。
import ToolBindDialog from '~/components/toolBindings/ToolBindDialog.vue'
import ToolBindingSettings from '~/components/toolBindings/ToolBindingSettings.vue'
import ToolBindingTable from '~/components/toolBindings/ToolBindingTable.vue'

// ============================================================================
// Mocks：toolBindings store + accessTokens store + toast/errorHandler（隔离网络）
// ============================================================================

const fetchBindingsMock = vi.fn().mockResolvedValue([])
const fetchBindableMock = vi.fn().mockResolvedValue([])
const upsertBindingMock = vi.fn()
const unbindBindingMock = vi.fn()

// 可绑定工具：仅 mcp / skill（builtin 不入列）。
const bindableTools = [
  { id: 1, name: 'mcp_search', description: 'MCP 搜索', source: 'mcp' },
  { id: 2, name: 'skill_review', description: 'Skill 评审', source: 'skill' },
]

vi.mock('~/stores/toolBindings', () => ({
  useToolBindingStore: () => ({
    bindings: [] as unknown[],
    bindableTools,
    loading: false,
    fetchBindings: fetchBindingsMock,
    fetchBindable: fetchBindableMock,
    upsertBinding: upsertBindingMock,
    unbindBinding: unbindBindingMock,
  }),
}))

// 一个 is_valid:true + 一个 is_valid:false 令牌，验证下拉只列有效令牌。
const validToken: AccessTokenDto = {
  id: 'tok-valid',
  name: 'valid-token',
  note: '',
  token_prefix: 'friday_pat_',
  token_suffix: 'abcd',
  created_at: '2026-06-04T00:00:00Z',
  expires_at: null,
  revoked_at: null,
  last_used_at: null,
  is_valid: true,
}
const invalidToken: AccessTokenDto = {
  id: 'tok-invalid',
  name: 'revoked-token',
  note: '',
  token_prefix: 'friday_pat_',
  token_suffix: 'wxyz',
  created_at: '2026-06-04T00:00:00Z',
  expires_at: null,
  revoked_at: '2026-06-05T00:00:00Z',
  last_used_at: null,
  is_valid: false,
}

vi.mock('~/stores/accessTokens', () => ({
  useAccessTokenStore: () => ({
    tokens: [validToken, invalidToken],
    loading: false,
    fetchTokens: vi.fn().mockResolvedValue([]),
  }),
}))

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))

vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))

// Dialog / AlertDialog / Select 原语透传 stub，使内嵌内容始终渲染便于断言。
const stubs = {
  Dialog: { template: '<div><slot /></div>' },
  DialogContent: { template: '<div><slot /></div>' },
  DialogHeader: { template: '<div><slot /></div>' },
  DialogTitle: { template: '<div><slot /></div>' },
  DialogDescription: { template: '<div><slot /></div>' },
  AlertDialog: { template: '<div><slot /></div>' },
  AlertDialogContent: { template: '<div><slot /></div>' },
  AlertDialogHeader: { template: '<div><slot /></div>' },
  AlertDialogTitle: { template: '<div><slot /></div>' },
  AlertDialogDescription: { template: '<div><slot /></div>' },
  AlertDialogFooter: { template: '<div><slot /></div>' },
  AlertDialogCancel: { template: '<button><slot /></button>' },
  AlertDialogAction: {
    template: '<button class="confirm-unbind" @click="$emit(\'click\')"><slot /></button>',
  },
  Select: {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<div><slot /></div>',
  },
  SelectTrigger: { template: '<div><slot /></div>' },
  SelectContent: { template: '<div><slot /></div>' },
  SelectItem: { template: '<div><slot /></div>' },
  SelectValue: { template: '<div><slot /></div>' },
}

describe('toolBindingSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchBindingsMock.mockResolvedValue([])
    fetchBindableMock.mockResolvedValue([])
  })

  it('lists_bindable_mcp_skill_tools', async () => {
    const wrapper = mount(ToolBindingSettings, { global: { stubs } })
    await flushPromises()

    // 渲染可绑定的 mcp/skill 工具行（每行展示工具名）。
    const text = wrapper.text()
    expect(text).toContain('mcp_search')
    expect(text).toContain('skill_review')
  })

  it('bind_dropdown_only_lists_valid_tokens', async () => {
    const wrapper = mount(ToolBindingSettings, { global: { stubs } })
    await flushPromises()

    const text = wrapper.text()
    // 下拉只列 is_valid===true 的令牌：有效令牌名出现、吊销令牌名不出现。
    expect(text).toContain('valid-token')
    expect(text).not.toContain('revoked-token')
  })

  it('bind_calls_store_upsert_with_tool_and_token', async () => {
    upsertBindingMock.mockResolvedValueOnce({ id: 10 })
    const wrapper = mount(ToolBindingSettings, { global: { stubs } })
    await flushPromises()

    // 选工具 + 选令牌 + 确认 → upsertBinding 被调用且参数含 { remote_tool, access_token }。
    wrapper.findComponent(ToolBindDialog).vm.$emit('submit', {
      remote_tool: 1,
      access_token: 'tok-valid',
    })
    await flushPromises()

    expect(upsertBindingMock).toHaveBeenCalledWith(
      expect.objectContaining({ remote_tool: 1, access_token: 'tok-valid' }),
    )
  })

  it('unbind_calls_store_unbind', async () => {
    unbindBindingMock.mockResolvedValueOnce(undefined)
    const wrapper = mount(ToolBindingSettings, { global: { stubs } })
    await flushPromises()

    // 对已有绑定点解绑 → 二次确认 → unbindBinding 被调用且传该绑定 id。
    wrapper.findComponent(ToolBindingTable).vm.$emit('unbind', { id: 42 })
    await flushPromises()
    await wrapper.find('.confirm-unbind').trigger('click')
    await flushPromises()

    expect(unbindBindingMock).toHaveBeenCalledWith(42)
  })

  it('never_renders_token_plaintext', async () => {
    const wrapper = mount(ToolBindingSettings, { global: { stubs } })
    await flushPromises()

    // 组件文本只含 prefix/suffix 指纹，绝不渲染任何完整 friday_pat_ 明文。
    // store 不暴露明文 → 组件无来源；以正则捕捉「friday_pat_ + 长随机段」形态。
    const text = wrapper.text()
    expect(text).not.toMatch(/friday_pat_[A-Za-z0-9_-]{8,}/)
  })
})
