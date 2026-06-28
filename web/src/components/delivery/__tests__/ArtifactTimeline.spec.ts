/**
 * ArtifactTimeline 守护测试（Chassis v2 · P7，只读版本轨）。
 *
 * 覆盖三问呈现：
 *  - 当前最新版本是什么：当前版本徽标 + render_markdown 摘要。
 *  - 为何变成它：produced_by_ref + supersedes 链（“替换 vN”）。
 *  - 哪些下游产物引用它：选中版本拉下游引用聚合（编码任务 / SDD 规格 / 架构融合）。
 *  - 空态：无交付物显示占位。
 */
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listArtifactsMock = vi.fn()
const getArtifactTimelineMock = vi.fn()
const getArtifactVersionDownstreamMock = vi.fn()

vi.mock('~/api/deliveryArtifacts', () => ({
  listArtifacts: (...a: unknown[]) => listArtifactsMock(...a),
  getArtifactTimeline: (...a: unknown[]) => getArtifactTimelineMock(...a),
  getArtifactVersionDownstream: (...a: unknown[]) => getArtifactVersionDownstreamMock(...a),
}))

const ArtifactTimeline = (await import('../ArtifactTimeline.vue')).default

function makeArtifact() {
  return {
    id: 'art-1',
    artifact_type: 'technical_plan',
    title: '登录改造方案',
    status: 'draft',
    work_item_id: null,
    created_at: '2026-06-20T00:00:00Z',
    updated_at: '2026-06-21T00:00:00Z',
    current_version: {
      id: 'v2',
      version_no: 2,
      created_at: '2026-06-21T00:00:00Z',
      content_hash: 'h2',
      supersedes_id: 'v1',
      produced_by_ref: 'signal:clarify-2',
      produced_by_session_id: 's2',
      approval_status: 'pending',
      is_current: true,
    },
  }
}

function makeTimeline() {
  return {
    ...makeArtifact(),
    current_version_markdown: '# 登录改造方案 v2\n\n统一 cookie-JWT',
    versions: [
      {
        id: 'v2',
        version_no: 2,
        created_at: '2026-06-21T00:00:00Z',
        content_hash: 'h2',
        supersedes_id: 'v1',
        produced_by_ref: 'signal:clarify-2',
        produced_by_session_id: 's2',
        approval_status: 'pending',
        is_current: true,
      },
      {
        id: 'v1',
        version_no: 1,
        created_at: '2026-06-20T00:00:00Z',
        content_hash: 'h1',
        supersedes_id: null,
        produced_by_ref: 'signal:init',
        produced_by_session_id: 's1',
        approval_status: 'none',
        is_current: false,
      },
    ],
  }
}

function makeDownstream() {
  return {
    artifact_version_id: 'v2',
    coding_tasks: [{ id: 'ct1', repository_id: 'r1', status: 'pending', wave: 0, attempt: 0 }],
    sdd_specs: [{ id: 'sp1', repository_id: 'r1', status: 'draft', change_kind: 'proposal' }],
    architect_merges: [{ id: 'm1', session_id: 'sess1', validation_status: 'passed', attempt: 1 }],
    total: 3,
  }
}

function mountComp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(ArtifactTimeline, {
    props: { spaceId: 'space-1', artifactType: 'technical_plan' },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
}

describe('artifactTimeline 版本轨', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listArtifactsMock.mockResolvedValue([makeArtifact()])
    getArtifactTimelineMock.mockResolvedValue(makeTimeline())
    getArtifactVersionDownstreamMock.mockResolvedValue(makeDownstream())
  })

  it('按 space + artifact_type 拉列表并渲染交付物切换', async () => {
    const wrapper = mountComp()
    await flushPromises()
    expect(listArtifactsMock).toHaveBeenCalledWith({
      space_id: 'space-1',
      artifact_type: 'technical_plan',
      work_item_id: undefined,
    })
    expect(wrapper.find('[data-testid="artifact-tab-art-1"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('登录改造方案')
  })

  it('当前最新版本是什么：当前版本徽标 + markdown 摘要', async () => {
    const wrapper = mountComp()
    await flushPromises()
    const current = wrapper.find('[data-testid="artifact-current"]')
    expect(current.exists()).toBe(true)
    expect(current.text()).toContain('当前版本')
    expect(current.text()).toContain('v2')
    expect(wrapper.find('[data-testid="artifact-current-md"]').text()).toContain('统一 cookie-JWT')
  })

  it('为何变成它：produced_by_ref + supersedes 链（倒序）', async () => {
    const wrapper = mountComp()
    await flushPromises()
    const versions = wrapper.find('[data-testid="artifact-versions"]')
    expect(versions.text()).toContain('signal:clarify-2')
    // v2 替换 v1
    expect(wrapper.find('[data-testid="artifact-version-2"]').text()).toContain('替换 v1')
    // v1 为初始版本
    expect(wrapper.find('[data-testid="artifact-version-1"]').text()).toContain('初始版本')
  })

  it('哪些下游产物引用它：当前版本自动拉下游聚合', async () => {
    const wrapper = mountComp()
    await flushPromises()
    expect(getArtifactVersionDownstreamMock).toHaveBeenCalledWith('v2')
    const ds = wrapper.find('[data-testid="artifact-downstream"]')
    expect(ds.find('[data-testid="downstream-coding-task"]').exists()).toBe(true)
    expect(ds.find('[data-testid="downstream-sdd-spec"]').exists()).toBe(true)
    expect(ds.find('[data-testid="downstream-architect-merge"]').exists()).toBe(true)
  })

  it('选择历史版本 → 重新拉该版本下游引用', async () => {
    const wrapper = mountComp()
    await flushPromises()
    await wrapper.find('[data-testid="artifact-version-1"]').trigger('click')
    await flushPromises()
    expect(getArtifactVersionDownstreamMock).toHaveBeenCalledWith('v1')
  })

  it('空态：无交付物显示占位', async () => {
    listArtifactsMock.mockResolvedValue([])
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.find('[data-testid="artifact-empty"]').exists()).toBe(true)
    expect(getArtifactTimelineMock).not.toHaveBeenCalled()
  })
})
