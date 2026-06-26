/**
 * DocsSection / MemorySection 守护测试（Phase 84 WB-03）。
 *
 * 覆盖：
 *  - 5 文件切换（memory/state/milestones/research/preflight）
 *  - 查看态 md 渲染（rendered_markdown）
 *  - 编辑态：system block 只读 / human block 可编辑
 *  - 保存仅提交人工区 → updateHumanBlocks（触发同步引擎回灌）
 *  - 保存后 syncing 同步态（派发→轮询）
 *  - MEMORY 草稿采纳/拒绝 → 二次确认 + confirmDraft/rejectDraft
 *
 * 文案以真实 zh-CN.json 断言（沿用 MemoryTab.spec.ts / workbench-shell.spec.ts 范式）。
 */
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() }),
}))
vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))
const confirmMock = vi.fn().mockResolvedValue(true)
vi.mock('~/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({ confirm: confirmMock }),
}))

// 轻量替身：避开 shiki / CodeMirror6 在 happy-dom 的重初始化。
vi.mock('~/components/execution/MarkdownRenderer.vue', () => ({
  default: {
    name: 'MarkdownRenderer',
    props: { content: { type: String, default: '' } },
    setup: (p: { content: string }) => () => h('div', { class: 'md-stub' }, p.content),
  },
}))
vi.mock('~/components/project/workbench/MarkdownSourceEditor.vue', () => ({
  default: {
    name: 'MarkdownSourceEditor',
    props: {
      modelValue: { type: String, default: '' },
      readonly: { type: Boolean, default: false },
      height: { type: String, default: '' },
    },
    setup: (p: { modelValue: string, readonly: boolean }) => () =>
      h('div', { class: 'cm-stub', 'data-readonly': p.readonly ? 'true' : 'false' }, p.modelValue),
  },
}))

const listDocsMock = vi.fn()
const getDocContentMock = vi.fn()
const updateHumanBlocksMock = vi.fn().mockResolvedValue({})
vi.mock('~/api/projectWorkspace', () => ({
  projectWorkspaceApi: {
    listDocs: (...a: unknown[]) => listDocsMock(...a),
    getDocContent: (...a: unknown[]) => getDocContentMock(...a),
    updateHumanBlocks: (...a: unknown[]) => updateHumanBlocksMock(...a),
  },
}))

const memListMock = vi.fn().mockResolvedValue([])
const memListDraftsMock = vi.fn().mockResolvedValue([])
const confirmDraftMock = vi.fn().mockResolvedValue({})
const rejectDraftMock = vi.fn().mockResolvedValue({})
vi.mock('~/api/projectMemory', () => ({
  projectMemoryApi: {
    list: (...a: unknown[]) => memListMock(...a),
    listDrafts: (...a: unknown[]) => memListDraftsMock(...a),
    create: vi.fn().mockResolvedValue({}),
    edit: vi.fn(),
    supersede: vi.fn(),
    confirmDraft: (...a: unknown[]) => confirmDraftMock(...a),
    rejectDraft: (...a: unknown[]) => rejectDraftMock(...a),
  },
}))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

const DocsSection = (await import('../DocsSection.vue')).default

function makeDocs() {
  return (['memory', 'state', 'milestones', 'research', 'preflight'] as const).map(dt => ({
    id: `d-${dt}`,
    project_id: 'p1',
    doc_type: dt,
    feishu_document_id: '',
    feishu_doc_token: '',
    sync_status: 'synced',
    last_synced_revision: 1,
    created_at: '2026-06-20T00:00:00Z',
    updated_at: '2026-06-20T00:00:00Z',
  }))
}

const STATE_CONTENT = {
  doc_type: 'state',
  sync_status: 'synced',
  last_synced_revision: 1,
  rendered_markdown: '# 状态文件\n\n当前里程碑进行中',
  blocks: [
    { block_id: 'b-sys', db_ref: 'r1', section: 'system', text: '系统区内容', editable: false },
    { block_id: 'b-hum', db_ref: 'r2', section: 'human', text: '人工区内容', editable: true },
  ],
}

const DRAFT = {
  id: 'd1',
  project_id: 'p1',
  content: 'LLM 提议：登录态统一走 cookie-JWT',
  status: 'pending',
  source_conversation_id: 'c1',
  proposed_by_id: 'u1',
  confirmed_memory_id: null,
  created_at: '2026-06-20T00:00:00Z',
  updated_at: '2026-06-20T00:00:00Z',
}

function mountDocs() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(DocsSection, {
    props: { projectId: 'p1' },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

describe('docsSection 5 文件查看/编辑', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listDocsMock.mockResolvedValue(makeDocs())
    getDocContentMock.mockResolvedValue(STATE_CONTENT)
    memListMock.mockResolvedValue([])
    memListDraftsMock.mockResolvedValue([])
  })

  it('渲染 5 个文件切换（真实 zh-CN 文案），默认 MEMORY', async () => {
    const wrapper = mountDocs()
    await flushPromises()
    for (const dt of ['memory', 'state', 'milestones', 'research', 'preflight'] as const)
      expect(wrapper.find(`[data-testid="doc-file-${dt}"]`).exists()).toBe(true)
    expect(wrapper.text()).toContain(zhCN.projects.workbench.docs.file.state)
    // 默认 memory → 挂载 MemorySection
    expect(wrapper.find('[data-testid="workbench-memory-section"]').exists()).toBe(true)
  })

  it('切换到 state 文件 → 查看态 md 渲染', async () => {
    const wrapper = mountDocs()
    await flushPromises()
    await wrapper.find('[data-testid="doc-file-state"]').trigger('click')
    await flushPromises()
    expect(getDocContentMock).toHaveBeenCalledWith('p1', 'state')
    expect(wrapper.find('[data-testid="doc-view"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('当前里程碑进行中')
  })

  it('进入编辑态：system block 只读、human block 可编辑', async () => {
    const wrapper = mountDocs()
    await flushPromises()
    await wrapper.find('[data-testid="doc-file-state"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="doc-edit-toggle"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="doc-edit"]').exists()).toBe(true)
    // 系统区只读提示文案
    expect(wrapper.text()).toContain(zhCN.projects.workbench.docs.systemReadonly)
    const sysEditor = wrapper.find('[data-testid="doc-block-system"] .cm-stub')
    const humEditor = wrapper.find('[data-testid="doc-block-human"] .cm-stub')
    expect(sysEditor.exists()).toBe(true)
    expect(humEditor.exists()).toBe(true)
    expect(sysEditor.attributes('data-readonly')).toBe('true')
    expect(humEditor.attributes('data-readonly')).toBe('false')
  })

  it('保存仅提交人工区 → updateHumanBlocks', async () => {
    const wrapper = mountDocs()
    await flushPromises()
    await wrapper.find('[data-testid="doc-file-state"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="doc-edit-toggle"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="doc-save-btn"]').trigger('click')
    await flushPromises()
    expect(updateHumanBlocksMock).toHaveBeenCalledWith('p1', 'state', [
      { block_id: 'b-hum', text: '人工区内容' },
    ])
    // 保存成功回到查看态
    expect(wrapper.find('[data-testid="doc-view"]').exists()).toBe(true)
  })

  it('保存触发 syncing 同步态（派发→轮询）', async () => {
    getDocContentMock.mockResolvedValue({ ...STATE_CONTENT, sync_status: 'syncing' })
    const wrapper = mountDocs()
    await flushPromises()
    await wrapper.find('[data-testid="doc-file-state"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="doc-view"]').exists()).toBe(true)
    expect(wrapper.text()).toContain(zhCN.projects.workbench.overview.syncing)
  })
})

describe('memorySection 草稿确认', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listDocsMock.mockResolvedValue(makeDocs())
    getDocContentMock.mockResolvedValue(STATE_CONTENT)
    memListMock.mockResolvedValue([])
    memListDraftsMock.mockResolvedValue([DRAFT])
  })

  it('渲染 pending 草稿并采纳 → 二次确认 + confirmDraft', async () => {
    const wrapper = mountDocs()
    await flushPromises()
    expect(wrapper.find('[data-testid="draft-section"]').exists()).toBe(true)
    expect(wrapper.text()).toContain(zhCN.projects.memory.draft.title)
    await wrapper.find('[data-testid="draft-accept"]').trigger('click')
    await flushPromises()
    expect(confirmMock).toHaveBeenCalled()
    expect(confirmDraftMock).toHaveBeenCalledWith('p1', 'd1')
  })

  it('拒绝草稿 → 二次确认 + rejectDraft', async () => {
    const wrapper = mountDocs()
    await flushPromises()
    await wrapper.find('[data-testid="draft-reject"]').trigger('click')
    await flushPromises()
    expect(confirmMock).toHaveBeenCalled()
    expect(rejectDraftMock).toHaveBeenCalledWith('p1', 'd1')
  })
})
