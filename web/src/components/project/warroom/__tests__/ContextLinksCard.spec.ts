/**
 * ContextLinksCard 守护测试（「生成知识关联」面板）。
 *
 * 覆盖：空态与生成入口、候选分组渲染（仓库 + 知识/工件/MR）、接受/拒绝调用、
 * 已关联区（人工徽标 + 删除）、只读（canManage=false）不渲染操作按钮。
 */

import type { ContextLinksPayload } from '~/api/projectContextLinks'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() }),
}))
vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))
vi.mock('~/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({ confirm: vi.fn().mockResolvedValue(true) }),
}))

const listMock = vi.fn()
const generateMock = vi.fn()
const acceptMock = vi.fn()
const rejectMock = vi.fn()
const removeMock = vi.fn()
const repoDecisionMock = vi.fn()
const addManualMock = vi.fn()

vi.mock('~/api/projectContextLinks', () => ({
  contextLinksApi: {
    list: (...a: unknown[]) => listMock(...a),
    generate: (...a: unknown[]) => generateMock(...a),
    accept: (...a: unknown[]) => acceptMock(...a),
    reject: (...a: unknown[]) => rejectMock(...a),
    remove: (...a: unknown[]) => removeMock(...a),
    repoDecision: (...a: unknown[]) => repoDecisionMock(...a),
    addManual: (...a: unknown[]) => addManualMock(...a),
  },
}))

const Comp = (await import('../ContextLinksCard.vue')).default

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

function mountComp(canManage = true) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(Comp, {
    props: { projectId: 'p-1', canManage },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

function payload(): ContextLinksPayload {
  return {
    links: [
      {
        id: 'l-1',
        project_id: 'p-1',
        target_kind: 'knowledge',
        target_id: 'k-1',
        title: '登录方案',
        url: '',
        score: 0.9,
        reason: '语义检索命中 tech_plan（score 0.90）',
        origin: 'ai',
        status: 'proposed',
        created_by_id: null,
        created_at: '2026-07-03T00:00:00Z',
        updated_at: '2026-07-03T00:00:00Z',
      },
      {
        id: 'l-2',
        project_id: 'p-1',
        target_kind: 'external',
        target_id: null,
        title: '设计稿',
        url: 'https://figma/x',
        score: 0,
        reason: '',
        origin: 'manual',
        status: 'accepted',
        created_by_id: 'u-1',
        created_at: '2026-07-03T00:00:00Z',
        updated_at: '2026-07-03T00:00:00Z',
      },
    ],
    repos: [
      {
        association_id: 'a-1',
        repository_id: 'r-1',
        repository_name: 'repoA',
        git_url: 'https://git/repoA.git',
        status: 'proposed',
        score: 0.8,
        confidence: 'high',
        reason: '命中鉴权能力',
      },
      {
        association_id: 'a-2',
        repository_id: 'r-2',
        repository_name: 'repoB',
        git_url: 'https://git/repoB.git',
        status: 'verified',
        score: 0.7,
        confidence: 'medium',
        reason: '',
      },
    ],
  }
}

describe('contextLinksCard 知识关联面板', () => {
  beforeEach(() => vi.clearAllMocks())

  it('空态显示生成引导 + 生成按钮', async () => {
    listMock.mockResolvedValue({ links: [], repos: [] })
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.find('[data-testid="ctx-empty"]').text()).toContain(
      zhCN.projects.warroom.contextLinks.empty,
    )
    expect(wrapper.find('[data-testid="ctx-generate-btn"]').exists()).toBe(true)
  })

  it('渲染待确认候选（仓库 + 链接）与已关联区', async () => {
    listMock.mockResolvedValue(payload())
    const wrapper = mountComp()
    await flushPromises()

    const repoRows = wrapper.findAll('[data-testid="ctx-repo-row"]')
    expect(repoRows).toHaveLength(1)
    expect(repoRows[0].text()).toContain('repoA')
    expect(repoRows[0].text()).toContain('命中鉴权能力')

    const linkRows = wrapper.findAll('[data-testid="ctx-link-row"]')
    expect(linkRows).toHaveLength(1)
    expect(linkRows[0].text()).toContain('登录方案')

    // 已关联区：verified 仓库 + 人工 external（含人工徽标 + 删除按钮）
    expect(wrapper.find('[data-testid="ctx-linked-repo-row"]').text()).toContain('repoB')
    const acceptedRow = wrapper.find('[data-testid="ctx-accepted-row"]')
    expect(acceptedRow.text()).toContain('设计稿')
    expect(acceptedRow.text()).toContain(zhCN.projects.warroom.contextLinks.manualBadge)
    expect(acceptedRow.find('[data-testid="ctx-link-delete"]').exists()).toBe(true)

    // 待确认计数徽标 = 仓库候选 1 + 链接候选 1
    expect(wrapper.find('[data-testid="ctx-proposed-count"]').text()).toBe('2')
  })

  it('接受/拒绝候选调用对应 API', async () => {
    listMock.mockResolvedValue(payload())
    acceptMock.mockResolvedValue({})
    repoDecisionMock.mockResolvedValue({ applied: true, action: 'reject' })
    const wrapper = mountComp()
    await flushPromises()

    await wrapper.find('[data-testid="ctx-link-accept"]').trigger('click')
    await flushPromises()
    expect(acceptMock).toHaveBeenCalledWith('p-1', 'l-1')

    await wrapper.find('[data-testid="ctx-repo-reject"]').trigger('click')
    await flushPromises()
    expect(repoDecisionMock).toHaveBeenCalledWith('p-1', {
      repository_id: 'r-1',
      action: 'reject',
    })
  })

  it('生成按钮触发 generate', async () => {
    listMock.mockResolvedValue({ links: [], repos: [] })
    generateMock.mockResolvedValue({
      links: [],
      repos: [],
      summary: {
        repo_candidates: 0,
        knowledge_candidates: 0,
        artifact_candidates: 0,
        mr_candidates: 0,
        created: 0,
        refreshed: 0,
        skipped: 0,
      },
    })
    const wrapper = mountComp()
    await flushPromises()
    await wrapper.find('[data-testid="ctx-generate-btn"]').trigger('click')
    await flushPromises()
    expect(generateMock).toHaveBeenCalledWith('p-1')
  })

  it('只读模式不渲染任何操作按钮', async () => {
    listMock.mockResolvedValue(payload())
    const wrapper = mountComp(false)
    await flushPromises()
    expect(wrapper.find('[data-testid="ctx-generate-btn"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="ctx-add-btn"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="ctx-link-accept"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="ctx-repo-accept"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="ctx-link-delete"]').exists()).toBe(false)
  })
})
