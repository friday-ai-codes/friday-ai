/**
 * SpecTransitionActions 守护测试（Phase 50-05，D-50-3/D-50-5）。
 *
 * 覆盖：state × 权限矩阵显隐 + transition 派发 invalidate + 真实 zh-CN 文案。
 */

import type { SddSpecDetail, SddSpecStatus } from '~/api/specs'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import SpecTransitionActions from '~/components/spec/SpecTransitionActions.vue'
import zhCN from '~/locales/zh-CN.json'

const mocks = vi.hoisted(() => ({
  isAdmin: { value: false },
  confirmMock: vi.fn<(opts: unknown) => Promise<boolean>>(),
  successMock: vi.fn(),
  handleErrorMock: vi.fn(),
}))

vi.mock('~/composables/usePermission', () => ({
  usePermission: () => ({ isSystemAdmin: mocks.isAdmin }),
}))
vi.mock('~/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({ confirm: mocks.confirmMock }),
}))
vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: mocks.successMock }),
}))
vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: mocks.handleErrorMock }),
}))
vi.mock('~/api/specs', () => ({
  specsApi: { transition: vi.fn() },
}))

const { specsApi } = await import('~/api/specs')

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN as any },
})

function makeSpec(status: SddSpecStatus): SddSpecDetail {
  return {
    id: 'spec-1',
    status,
    change_kind: 'proposal',
    repository_id: 'repo-1',
    repository_name: 'demo-repo',
    updated_at: '2026-06-17T00:00:00Z',
    body: null,
    reviews: [],
    relations: {},
  }
}

function mountActions(spec: SddSpecDetail) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const spy = vi.spyOn(queryClient, 'invalidateQueries')
  const wrapper = mount(SpecTransitionActions, {
    props: { spec },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
  return { wrapper, spy }
}

function findButton(wrapper: ReturnType<typeof mountActions>['wrapper'], text: string) {
  return wrapper.findAll('button').find(b => b.text().includes(text))
}

describe('specTransitionActions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.isAdmin.value = false
    mocks.confirmMock.mockResolvedValue(true)
  })

  it('draft + authenticated user → shows 提交评审, hides approve/reject/archive', () => {
    const { wrapper } = mountActions(makeSpec('draft'))
    expect(findButton(wrapper, zhCN.specs.actions.submit)).toBeTruthy()
    expect(findButton(wrapper, zhCN.specs.actions.approve)).toBeFalsy()
    expect(findButton(wrapper, zhCN.specs.actions.reject)).toBeFalsy()
    expect(findButton(wrapper, zhCN.specs.actions.archive)).toBeFalsy()
  })

  it('in_review + non-superuser → only awaitingReview hint, no restricted buttons', () => {
    const { wrapper } = mountActions(makeSpec('in_review'))
    expect(wrapper.text()).toContain(zhCN.specs.actions.awaitingReview)
    expect(findButton(wrapper, zhCN.specs.actions.approve)).toBeFalsy()
    expect(findButton(wrapper, zhCN.specs.actions.reject)).toBeFalsy()
    expect(findButton(wrapper, zhCN.specs.actions.archive)).toBeFalsy()
  })

  it('in_review + superuser → shows approve/reject/archive', () => {
    mocks.isAdmin.value = true
    const { wrapper } = mountActions(makeSpec('in_review'))
    expect(wrapper.text()).not.toContain(zhCN.specs.actions.awaitingReview)
    expect(findButton(wrapper, zhCN.specs.actions.approve)).toBeTruthy()
    expect(findButton(wrapper, zhCN.specs.actions.reject)).toBeTruthy()
    expect(findButton(wrapper, zhCN.specs.actions.archive)).toBeTruthy()
  })

  it('click 提交评审 → calls transition + invalidates [specs] and [spec, id]', async () => {
    vi.mocked(specsApi.transition).mockResolvedValue(makeSpec('in_review'))
    const { wrapper, spy } = mountActions(makeSpec('draft'))

    await findButton(wrapper, zhCN.specs.actions.submit)!.trigger('click')
    await flushPromises()

    expect(specsApi.transition).toHaveBeenCalledWith('spec-1', {
      action: 'submit_for_review',
      comment: undefined,
    })
    const invalidatedKeys = spy.mock.calls.map(c => (c[0] as { queryKey: unknown[] }).queryKey)
    expect(invalidatedKeys).toContainEqual(['specs'])
    expect(invalidatedKeys).toContainEqual(['spec', 'spec-1'])
    expect(mocks.successMock).toHaveBeenCalledWith(zhCN.specs.toast.submitted)
  })
})
