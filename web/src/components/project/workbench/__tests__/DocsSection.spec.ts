/**
 * DocsSection 工作区 5 文件查看/编辑守护测试（WB-03）。
 *
 * 覆盖：5 文件切换、查看态 markdown 渲染、编辑态 system 只读 / human 可编辑、
 * 保存调 updateHumanBlocks（人工区写回 → 同步引擎回灌）并重新拉取（轮询刷新）、
 * MEMORY 草稿采纳触发二次确认 + confirmDraft，关键 zh-CN 文案。
 */
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
const confirmMock = vi.fn()
vi.mock('~/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({ confirm: confirmMock }),
}))

const listDocsMock = vi.fn()
const getDocContentMock = vi.fn()
const updateHumanBlocksMock = vi.fn()
vi.mock('~/api/projectWorkspace', () => ({
  projectWorkspaceApi: {
    listDocs: (...a: unknown[]) => listDocsMock(...a),
    getDocContent: (...a: unknown[]) => getDocContentMock(...a),
    updateHumanBlocks: (...a: unknown[]) => updateHumanBlocksMock(...a),
  },
}))

const memListMock = vi.fn()
const memListDraftsMock = vi.fn()
const confirmDraftMock = vi.fn()
const rejectDraftMock = vi.fn()
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

const SourceEditorStub = {
  name: 'MarkdownSourceEditor',
  props: { modelValue: { type: String, default: '' }, readonly: { type: Boolean, default: false } },
  emits: ['update:modelValue'],
  template: `<textarea class="src-editor" :data-readonly="readonly ? 'true' : 'false'" :value="modelValue" @input="$emit('update:modelValue', ($event.target).value)"></textarea>`,
}
const MdRendererStub = {
  name: 'MarkdownRenderer',
  props: { content: { type: String, default: '' } },
  template: `<div class="md-view">{{ content }}</div>`,
}

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

const Comp = (await import('../DocsSection.vue')).default

function mountSection() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(Comp, {
    props: { projectId: 'p1' },
    global: {
      plugins: [i18n, [VueQueryPlugin, { queryClient }]],
      stubs: { MarkdownSourceEditor: SourceEditorStub, MarkdownRenderer: MdRendererStub },
    },
  })
}

function doc(docType: string, syncStatus = 'synced') {
  return {
    id: `d-${docType}`,
    project_id: 'p1',
    doc_type: docType,
    feishu_document_id: 'fd',
    feishu_doc_token: 'tok',
    sync_status: syncStatus,
    last_synced_revision: 1,
    created_at: '2026-06-20T00:00:00Z',
    updated_at: '2026-06-20T00:00:00Z',
  }
}

const DOCS = ['memory', 'state', 'milestones', 'research', 'preflight'].map(d => doc(d))

const STATE_CONTENT = {
  doc_type: 'state',
  sync_status: 'synced',
  last_synced_revision: 1,
  rendered_markdown: '# 状态\n这是渲染内容',
  blocks: [
    { block_id: 'b-sys', db_ref: 'r1', section: 'system', text: '系统区文本', editable: false },
    { block_id: 'b-hum', db_ref: 'r2', section: 'human', text: '人工区文本', editable: true },
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

describe('docsSection 5 文件查看/编辑', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    confirmMock.mockResolvedValue(true)
    listDocsMock.mockResolvedValue(DOCS)
    getDocContentMock.mockResolvedValue(STATE_CONTENT)
    updateHumanBlocksMock.mockResolvedValue({ ...STATE_CONTENT, sync_status: 'syncing' })
    memListMock.mockResolvedValue([])
    memListDraftsMock.mockResolvedValue([])
    confirmDraftMock.mockResolvedValue({})
    rejectDraftMock.mockResolvedValue({})
  })

  it('渲染 5 个文件切换并默认进入 MEMORY 区', async () => {
    const wrapper = mountSection()
    await flushPromises()
    for (const dt of ['memory', 'state', 'milestones', 'research', 'preflight'])
      expect(wrapper.find(`[data-testid="doc-file-${dt}"]`).exists()).toBe(true)
    expect(wrapper.text()).toContain(zhCN.projects.workbench.docs.file.memory)
    expect(wrapper.text()).toContain(zhCN.projects.workbench.docs.file.preflight)
    // 默认 memory → 渲染 MemorySection
    expect(wrapper.find('[data-testid="workbench-memory-section"]').exists()).toBe(true)
  })

  it('切到 state 文件 → 查看态 markdown 渲染', async () => {
    const wrapper = mountSection()
    await flushPromises()
    await wrapper.find('[data-testid="doc-file-state"]').trigger('click')
    await flushPromises()
    expect(getDocContentMock).toHaveBeenCalledWith('p1', 'state')
    expect(wrapper.find('[data-testid="doc-view"]').exists()).toBe(true)
    expect(wrapper.find('.md-view').text()).toContain('这是渲染内容')
  })

  it('编辑态：system 区只读、human 区可编辑 + 只读提示', async () => {
    const wrapper = mountSection()
    await flushPromises()
    await wrapper.find('[data-testid="doc-file-state"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="doc-edit-toggle"]').trigger('click')
    await flushPromises()
    const editors = wrapper.findAll('.src-editor')
    expect(editors).toHaveLength(2)
    expect(editors[0].attributes('data-readonly')).toBe('true') // system
    expect(editors[1].attributes('data-readonly')).toBe('false') // human
    expect(wrapper.find('[data-testid="doc-system-hint"]').exists()).toBe(true)
    expect(wrapper.text()).toContain(zhCN.projects.workbench.docs.systemReadonly)
    expect(wrapper.text()).toContain(zhCN.projects.workbench.docs.save)
  })

  it('保存：调 updateHumanBlocks 写回人工区并重新拉取（轮询刷新）', async () => {
    const wrapper = mountSection()
    await flushPromises()
    await wrapper.find('[data-testid="doc-file-state"]').trigger('click')
    await flushPromises()
    const before = getDocContentMock.mock.calls.length
    await wrapper.find('[data-testid="doc-edit-toggle"]').trigger('click')
    await flushPromises()
    await wrapper.findAll('.src-editor')[1].setValue('编辑后的人工区')
    await wrapper.find('[data-testid="doc-save-btn"]').trigger('click')
    await flushPromises()
    expect(updateHumanBlocksMock).toHaveBeenCalledWith('p1', 'state', [
      { block_id: 'b-hum', text: '编辑后的人工区' },
    ])
    // 保存成功后失效查询 → 重新拉取（同步状态轮询的刷新入口）
    expect(getDocContentMock.mock.calls.length).toBeGreaterThan(before)
  })

  it('MEMORY 草稿采纳 → 二次确认 + confirmDraft', async () => {
    memListDraftsMock.mockResolvedValue([DRAFT])
    const wrapper = mountSection()
    await flushPromises()
    expect(wrapper.find('[data-testid="draft-section"]').exists()).toBe(true)
    expect(wrapper.text()).toContain(zhCN.projects.memory.draft.title)
    await wrapper.find('[data-testid="draft-accept"]').trigger('click')
    await flushPromises()
    expect(confirmMock).toHaveBeenCalled()
    expect(confirmDraftMock).toHaveBeenCalledWith('p1', 'd1')
  })
})
