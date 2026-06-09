import type { AccessTokenDto } from '~/types/accessToken'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AccessTokenForm from '~/components/accessTokens/AccessTokenForm.vue'
import AccessTokenListTable from '~/components/accessTokens/AccessTokenListTable.vue'
import AccessTokenRevealDialog from '~/components/accessTokens/AccessTokenRevealDialog.vue'
import AccessTokenSettings from '~/components/accessTokens/AccessTokenSettings.vue'

// ============================================================================
// Mocks：store + toast/errorHandler（隔离 vue-sonner 与网络）
// ============================================================================

const fetchTokensMock = vi.fn().mockResolvedValue([])
const createTokenMock = vi.fn()
const revokeTokenMock = vi.fn()

vi.mock('~/stores/accessTokens', () => ({
  useAccessTokenStore: () => ({
    tokens: [] as AccessTokenDto[],
    loading: false,
    fetchTokens: fetchTokensMock,
    createToken: createTokenMock,
    revokeToken: revokeTokenMock,
  }),
}))

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))

vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))

// Dialog / AlertDialog 原语透传 stub，使内嵌内容始终渲染便于断言
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
    template: '<button class="confirm-revoke" @click="$emit(\'click\')"><slot /></button>',
  },
}

// 06-03 将向 AccessTokenDto 补充 token_suffix / note 只读字段。
type SettingsToken = AccessTokenDto & { token_suffix?: string, note?: string }

function makeToken(overrides: Partial<SettingsToken> = {}): SettingsToken {
  return {
    id: overrides.id ?? 'tok-1',
    name: overrides.name ?? 'test',
    token_prefix: overrides.token_prefix ?? 'friday_pat_',
    token_suffix: overrides.token_suffix ?? '',
    note: overrides.note ?? '',
    created_at: overrides.created_at ?? '2026-06-04T00:00:00Z',
    expires_at: overrides.expires_at ?? null,
    revoked_at: overrides.revoked_at ?? null,
    last_used_at: overrides.last_used_at ?? null,
    is_valid: overrides.is_valid ?? true,
  }
}

// Select 原语透传 stub：暴露一个按钮以确定性地把过期策略切到 'never'，
// 规避 reka-ui Select 在 happy-dom 下的弹层交互不确定性。
const selectStubs = {
  Select: {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: `<div><button class="set-never" type="button" @click="$emit('update:modelValue', 'never')"></button><button class="set-custom" type="button" @click="$emit('update:modelValue', 'custom')"></button><slot /></div>`,
  },
  SelectTrigger: { template: '<div><slot /></div>' },
  SelectContent: { template: '<div><slot /></div>' },
  SelectItem: { template: '<div><slot /></div>' },
  SelectValue: { template: '<div><slot /></div>' },
}

describe('accessTokenSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchTokensMock.mockResolvedValue([])
  })

  it('create_flow_opens_reveal_with_plaintext', async () => {
    createTokenMock.mockResolvedValueOnce('friday_pat_NEWPLAIN')
    const wrapper = mount(AccessTokenSettings, { global: { stubs } })

    wrapper.findComponent(AccessTokenForm).vm.$emit('submit', { name: 'ci' })
    await flushPromises()

    const reveal = wrapper.findComponent(AccessTokenRevealDialog)
    expect(reveal.props('open')).toBe(true)
    expect(reveal.props('token')).toBe('friday_pat_NEWPLAIN')
  })

  it('closing_reveal_clears_plaintext', async () => {
    createTokenMock.mockResolvedValueOnce('friday_pat_TOCLEAR')
    const wrapper = mount(AccessTokenSettings, { global: { stubs } })

    wrapper.findComponent(AccessTokenForm).vm.$emit('submit', { name: 'ci' })
    await flushPromises()
    const reveal = wrapper.findComponent(AccessTokenRevealDialog)
    expect(reveal.props('token')).toBe('friday_pat_TOCLEAR')

    // 关闭 reveal → 明文内存 ref 归 null
    reveal.vm.$emit('update:open', false)
    await flushPromises()
    expect(reveal.props('token')).toBeNull()
  })

  it('revoke_confirm_calls_store', async () => {
    revokeTokenMock.mockResolvedValueOnce(makeToken({ revoked_at: '2026-06-04T10:00:00Z' }))
    const wrapper = mount(AccessTokenSettings, { global: { stubs } })

    wrapper.findComponent(AccessTokenListTable).vm.$emit('revoke', makeToken({ id: 'r-9' }))
    await flushPromises()

    await wrapper.find('.confirm-revoke').trigger('click')
    await flushPromises()

    expect(revokeTokenMock).toHaveBeenCalledWith('r-9')
  })

  // ==========================================================================
  // Nyquist Wave 0 契约（RED until 06-03）：永不过期非阻塞警告 + 备注流入 payload
  // ==========================================================================

  it('never_expiry_shows_nonblocking_warning_and_still_creates', async () => {
    createTokenMock.mockResolvedValueOnce('friday_pat_NEVER')
    const wrapper = mount(AccessTokenSettings, {
      global: { stubs: { ...stubs, ...selectStubs } },
    })

    // 名称为必填，先填好以便后续提交可通过校验。
    await wrapper.find('input').setValue('ci-never')
    // 切换到「永不过期」。
    await wrapper.find('.set-never').trigger('click')
    await flushPromises()

    // 非阻塞 amber 风险提示出现（「风险」字样区别于 Select 选项标签「永不过期」）—— RED until 06-03。
    expect(wrapper.text()).toContain('风险')

    // 非阻塞：仍可提交，createToken 照常被调用。
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(createTokenMock).toHaveBeenCalled()
  })

  it('note_value_flows_into_createToken_payload', async () => {
    createTokenMock.mockResolvedValueOnce('friday_pat_NOTE')
    const wrapper = mount(AccessTokenSettings, {
      global: { stubs: { ...stubs, ...selectStubs } },
    })

    // 备注输入框（06-03 新增 name="note"）—— RED until 实现落地。
    const noteInput = wrapper.find('input[name="note"]')
    expect(noteInput.exists()).toBe(true)

    await wrapper.find('input[name="name"]').setValue('ci')
    await noteInput.setValue('pipeline note')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    // 备注随 payload 流入 store.createToken。
    expect(createTokenMock).toHaveBeenCalledWith(
      expect.objectContaining({ note: 'pipeline note' }),
    )
  })

  // WR-02：自定义过期日期按「本地当天结束」构造，避免被解析为 UTC 午夜导致提前过期。
  it('custom_expiry_uses_end_of_local_day', async () => {
    createTokenMock.mockResolvedValueOnce('friday_pat_CUSTOM')
    const wrapper = mount(AccessTokenSettings, {
      global: { stubs: { ...stubs, ...selectStubs } },
    })

    await wrapper.find('input[name="name"]').setValue('ci-custom')
    // 切换到「自定义日期」，日期输入框随之出现。
    await wrapper.find('.set-custom').trigger('click')
    await flushPromises()

    await wrapper.find('input[type="date"]').setValue('2026-12-31')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    // 期望值与组件一致地按本地当天结束构造，确保不会回退成 UTC 午夜（提前过期）。
    const expected = new Date('2026-12-31T23:59:59.999').toISOString()
    expect(createTokenMock).toHaveBeenCalledWith(
      expect.objectContaining({ expires_at: expected }),
    )
    // 防回归：UTC 午夜解析（旧 bug）必须与期望值不同。
    expect(expected).not.toBe(new Date('2026-12-31').toISOString())
  })
})
