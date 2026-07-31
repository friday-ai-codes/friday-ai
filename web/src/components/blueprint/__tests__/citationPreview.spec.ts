/**
 * 引用二级预览六件的组件测试（Phase 115-03，UI-SPEC §10.1 / §18.2）。
 *
 * 覆盖路径（编号与 115-03-PLAN Task 3 ②逐条对应）：
 *  1. 九档 `source_type` 分发：六类进弹层各自命中对应子件；三类外链在 chip 层就走 `<a>`
 *     （见 `BlueprintBlock.spec.ts` 第 8 条），此处只断言**弹层不为它们渲染任何预览子件**
 *  2. ⭐ **三条兜底并列**（本文件头号靶子，三条并列才逮得住「只判非 2xx」的实现）：
 *     (a) 来源成功 ⇒ 渲染正文、**不出现** `CitationFallback`
 *     (b) 来源 404 ⇒ 出现 `CitationFallback` 且 `open` 仍为 `true`（**弹窗未被关掉**）
 *     (c) ⭐ `chunk-at` 返回 `{ chunks: [], usable: false }`（**200-空 chunks**，P-3 最常见的一档）
 *         ⇒ 出现 `CitationFallback`
 *  3. `locator.line_start` 缺失 ⇒ `getChunkAt` **一次都不调**且直接兜底
 *  4. ⛔ 不回显后端错误体：抛 `ApiError(400, '请求失败', { error: '缺少必填参数 path' })` 时
 *     渲染文本既不含「缺少必填参数」也不含「请求失败」
 *  5. `quote` 也为空 ⇒ 走 `CompactEmptyState`
 *  6. `CitationBlueprintPreview` 不嵌套第二层弹层，且传给 `BlueprintBlockList` 的
 *     `plainMermaid` 为 `true`、`threads` 为空数组
 */

import type { Citation } from '~/types/blueprint'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import { ApiError } from '~/api/client'
import BlueprintBlockList from '~/components/blueprint/BlueprintBlockList.vue'
import CitationBlueprintPreview from '~/components/blueprint/citation/CitationBlueprintPreview.vue'
import CitationCodePreview from '~/components/blueprint/citation/CitationCodePreview.vue'
import CitationFallback from '~/components/blueprint/citation/CitationFallback.vue'
import CitationKnowledgePreview from '~/components/blueprint/citation/CitationKnowledgePreview.vue'
import CitationPreviewDialog from '~/components/blueprint/CitationPreviewDialog.vue'

const api = vi.hoisted(() => ({
  getEntity: vi.fn(),
  getChunkAt: vi.fn(),
  getRepositoryCharter: vi.fn(),
  getBlueprintDocument: vi.fn(),
}))

vi.mock('~/api', () => ({
  knowledgeApi: { getEntity: api.getEntity },
  repositoryChunksApi: {
    getChunkAt: api.getChunkAt,
    getRepositoryCharter: api.getRepositoryCharter,
  },
  blueprintsApi: { getBlueprintDocument: api.getBlueprintDocument },
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        entity: { fields: { version: '版本', entityId: '实体 ID', validAt: '生效时间' } },
        blueprints: {
          block: { copy: '复制本段原文', copied: '已复制', language: '语言：{name}', diagramUnavailable: '流程图暂时无法渲染' },
          annotation: { markLabel: '共 {count} 条批注（{kind}）', degraded: '已标注整块', quotedSnapshot: '引用时的原文快照' },
          citation: {
            open: '查看引用来源',
            openExternal: '在新页面打开',
            fallback: '原始来源不可达，以下为引用时的快照',
            chunkCount: '共 {n} 个片段',
            lineRange: '第 {start}–{end} 行',
            sourceKnowledgeEntity: '知识条目',
            sourceRagChunk: '代码片段',
            sourceRepoFile: '仓库文件',
            sourceArtifactVersion: '交付物版本',
            sourceBlueprint: '技术方案',
            sourceRepoCharter: '仓库章程',
            sourceWorkItem: '需求工作项',
            sourceFeishuDoc: '飞书文档',
            sourceUrl: '外部链接',
          },
        },
      },
    },
  },
})

/** Dialog 原语一律 slot 直通：reka-ui 的内容走 Teleport，直通后才能在 wrapper 内断言。 */
const DIALOG_STUBS = {
  Dialog: { template: '<div><slot /></div>' },
  DialogScrollContent: { template: '<div><slot /></div>' },
  DialogHeader: { template: '<div><slot /></div>' },
  DialogTitle: { template: '<div><slot /></div>' },
  RouterLink: { template: '<a><slot /></a>' },
}

const CHILD_STUBS = {
  CitationKnowledgePreview: true,
  CitationCodePreview: true,
  CitationCharterPreview: true,
  CitationBlueprintPreview: true,
  CitationFallback: true,
}

function makeCitation(overrides: Partial<Citation> = {}): Citation {
  return {
    citation_id: 'c1',
    source_type: 'knowledge_entity',
    source_id: 'entity-1',
    title: '被引来源',
    quote: '这是引用时的原文快照',
    ...overrides,
  }
}

function newPlugins() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return [i18n, [VueQueryPlugin, { queryClient }]] as never[]
}

function mountDialog(citation: Citation, stubChildren = true) {
  return mount(CitationPreviewDialog, {
    props: { open: true, citation },
    global: {
      plugins: newPlugins(),
      stubs: stubChildren ? { ...DIALOG_STUBS, ...CHILD_STUBS } : DIALOG_STUBS,
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('citationPreviewDialog —— 九档 source_type 分发', () => {
  it('1a. knowledge_entity ⇒ CitationKnowledgePreview', () => {
    const wrapper = mountDialog(makeCitation({ source_type: 'knowledge_entity' }))
    expect(wrapper.html()).toContain('citation-knowledge-preview-stub')
  })

  it('1b. repo_file ⇒ CitationCodePreview', () => {
    const wrapper = mountDialog(makeCitation({
      source_type: 'repo_file',
      locator: { repository_id: 'repo-1', file_path: 'src/a.py', line_start: 10 },
    }))
    expect(wrapper.html()).toContain('citation-code-preview-stub')
  })

  it('1c. rag_chunk ⇒ CitationCodePreview（与 repo_file 同一子件）', () => {
    const wrapper = mountDialog(makeCitation({
      source_type: 'rag_chunk',
      locator: { repository_id: 'repo-1', file_path: 'src/b.py', line_start: 3 },
    }))
    expect(wrapper.html()).toContain('citation-code-preview-stub')
  })

  it('1d. repo_charter ⇒ CitationCharterPreview', () => {
    const wrapper = mountDialog(makeCitation({
      source_type: 'repo_charter',
      locator: { repository_id: 'repo-1', section: 'boundaries' },
    }))
    expect(wrapper.html()).toContain('citation-charter-preview-stub')
  })

  it('1e. blueprint / artifact_version ⇒ CitationBlueprintPreview', () => {
    for (const sourceType of ['blueprint', 'artifact_version'] as const) {
      const wrapper = mountDialog(makeCitation({ source_type: sourceType, source_id: 'art-1' }))
      expect(wrapper.html()).toContain('citation-blueprint-preview-stub')
    }
  })

  it('1f. ⭐ 外链三类（url / work_item / feishu_doc）⇒ 弹层不为它们渲染任何预览子件', () => {
    for (const sourceType of ['url', 'work_item', 'feishu_doc'] as const) {
      const wrapper = mountDialog(makeCitation({ source_type: sourceType }))
      expect(wrapper.html()).toContain('citation-fallback-stub')
      expect(wrapper.html()).not.toContain('citation-knowledge-preview-stub')
      expect(wrapper.html()).not.toContain('citation-code-preview-stub')
      expect(wrapper.html()).not.toContain('citation-blueprint-preview-stub')
    }
  })

  it('1g. 缺关键定位（代码引用没有 repository_id）⇒ 直接落 CitationFallback', () => {
    const wrapper = mountDialog(makeCitation({
      source_type: 'repo_file',
      locator: { file_path: 'src/a.py', line_start: 10 },
    }))
    expect(wrapper.html()).toContain('citation-fallback-stub')
    expect(wrapper.html()).not.toContain('citation-code-preview-stub')
  })
})

describe('citation 预览 —— ⭐ 三条兜底并列（弹窗保持打开、不回显错误体）', () => {
  it('2a. 来源成功 ⇒ 渲染正文，**不出现** CitationFallback', async () => {
    api.getEntity.mockResolvedValue({
      entity_id: 'entity-1',
      kind: 'work_item',
      version: 3,
      title: '知识条目标题',
      provenance: {},
      source_kind: 'feishu_work_item',
      source_id: '1',
      origin: 'feishu',
    })

    const wrapper = mount(CitationKnowledgePreview, {
      props: { entityId: 'entity-1', fallback: { title: '被引来源', quote: '快照' } },
      global: { plugins: newPlugins(), stubs: DIALOG_STUBS },
    })
    await flushPromises()
    await new Promise(resolve => setTimeout(resolve, 50))
    await flushPromises()

    expect(wrapper.text()).toContain('知识条目标题')
    expect(wrapper.findComponent(CitationFallback).exists()).toBe(false)
  })

  it('2b. 来源 404 ⇒ 出现 CitationFallback，且 open 仍为 true（⛔ 弹窗未被关掉）', async () => {
    api.getEntity.mockRejectedValue(new ApiError(404, '无权访问或该蓝图不存在'))

    const wrapper = mountDialog(
      makeCitation({ source_type: 'knowledge_entity', source_id: 'entity-1' }),
      false,
    )
    await flushPromises()
    await new Promise(resolve => setTimeout(resolve, 50))
    await flushPromises()

    expect(wrapper.findComponent(CitationFallback).exists()).toBe(true)
    expect(wrapper.text()).toContain('原始来源不可达')
    // ⭐ 与 analog（pages/knowledge/index.vue 的 catch 关弹窗 + toast）**完全相反**
    expect(wrapper.emitted('update:open')).toBeUndefined()
    expect(wrapper.props('open')).toBe(true)
  })

  it('2c. ⭐ chunk-at 返回 200-空 chunks（usable=false）⇒ CitationFallback（P-3 最常见的一档）', async () => {
    api.getChunkAt.mockResolvedValue({ chunks: [], usable: false })

    const wrapper = mount(CitationCodePreview, {
      props: {
        repositoryId: 'repo-1',
        locator: { file_path: 'src/a.py', line_start: 10 },
        fallback: { title: '被引来源', quote: 'def main():' },
      },
      global: { plugins: newPlugins(), stubs: DIALOG_STUBS },
    })
    await flushPromises()
    await new Promise(resolve => setTimeout(resolve, 50))
    await flushPromises()

    expect(api.getChunkAt).toHaveBeenCalledTimes(1)
    expect(wrapper.findComponent(CitationFallback).exists()).toBe(true)
    expect(wrapper.text()).toContain('原始来源不可达')
  })

  it('2d. 负向对照：usable=true ⇒ 渲染路径 + 行号区间，**不出现** CitationFallback', async () => {
    api.getChunkAt.mockResolvedValue({
      chunks: [{ chunk_id: 'ck-1', file_path: 'src/a.py', line_start: 10, line_end: 42, chunk_index: 0 }],
      usable: true,
    })

    const wrapper = mount(CitationCodePreview, {
      props: {
        repositoryId: 'repo-1',
        locator: { file_path: 'src/a.py', line_start: 10 },
        fallback: { title: '被引来源', quote: 'def main():\n    pass' },
      },
      global: { plugins: newPlugins(), stubs: DIALOG_STUBS },
    })
    await flushPromises()
    await new Promise(resolve => setTimeout(resolve, 50))
    await flushPromises()

    expect(wrapper.findComponent(CitationFallback).exists()).toBe(false)
    expect(wrapper.find('[data-testid="citation-code-path"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('第 10–42 行')
    // ⭐ 降级形态：只有路径 + 行号 + quote 快照，⛔ 无源码正文
    expect(wrapper.text()).toContain('def main():')
  })

  it('3. ⭐ locator.line_start 缺失 ⇒ getChunkAt 一次都不调，直接兜底', async () => {
    const wrapper = mount(CitationCodePreview, {
      props: {
        repositoryId: 'repo-1',
        locator: { file_path: 'src/a.py' },
        fallback: { title: '被引来源', quote: '快照内容' },
      },
      global: { plugins: newPlugins(), stubs: DIALOG_STUBS },
    })
    await flushPromises()
    await new Promise(resolve => setTimeout(resolve, 50))
    await flushPromises()

    expect(api.getChunkAt).toHaveBeenCalledTimes(0)
    expect(wrapper.findComponent(CitationFallback).exists()).toBe(true)
  })

  it('4. ⛔ 不回显后端错误体（chunk-at 的错误体键是 error，通用键会回落成无意义文案）', async () => {
    api.getChunkAt.mockRejectedValue(
      new ApiError(400, '请求失败', { error: '缺少必填参数 path' }),
    )

    const wrapper = mount(CitationCodePreview, {
      props: {
        repositoryId: 'repo-1',
        locator: { file_path: 'src/a.py', line_start: 10 },
        fallback: { title: '被引来源', quote: '快照内容' },
      },
      global: { plugins: newPlugins(), stubs: DIALOG_STUBS },
    })
    await flushPromises()
    await new Promise(resolve => setTimeout(resolve, 50))
    await flushPromises()

    expect(wrapper.findComponent(CitationFallback).exists()).toBe(true)
    expect(wrapper.text()).not.toContain('缺少必填参数')
    expect(wrapper.text()).not.toContain('请求失败')
  })

  it('5. CitationFallback 的 quote 也为空 ⇒ 走 CompactEmptyState', () => {
    const withQuote = mount(CitationFallback, {
      props: { title: '被引来源', quote: '有快照' },
      global: { plugins: newPlugins(), stubs: { CompactEmptyState: true } },
    })
    expect(withQuote.html()).not.toContain('compact-empty-state-stub')

    const empty = mount(CitationFallback, {
      props: { title: '被引来源', quote: '   ' },
      global: { plugins: newPlugins(), stubs: { CompactEmptyState: true } },
    })
    expect(empty.html()).toContain('compact-empty-state-stub')
  })
})

describe('citationBlueprintPreview —— 迷你只读、无嵌套（§18.2）', () => {
  it('6. 不嵌套第二层弹层；传给 BlueprintBlockList 的 plainMermaid 为 true、threads 为空', async () => {
    api.getBlueprintDocument.mockResolvedValue({
      version_id: 'v-1',
      version_no: 2,
      is_current: true,
      produced_by_ref: 'human_edit:1',
      created_at: '2026-08-01T00:00:00Z',
      quality: { citation_coverage: 1, ai_rejection_rate: null, human_edit_volume: null, clarification_rounds: null },
      content: {
        schema_version: 'blueprint/v1',
        meta: {
          title: '被引蓝图标题',
          project_id: 'p-1',
          summary: [{ block_id: 's1', type: 'paragraph', text: '摘要一段' }],
        },
        citations: {},
      },
    })

    const wrapper = mount(CitationBlueprintPreview, {
      props: { artifactId: 'art-1', blockId: 's1', fallback: { title: '被引来源', quote: '快照' } },
      global: { plugins: newPlugins(), stubs: { ...DIALOG_STUBS, MermaidDiagram: true } },
    })
    await flushPromises()
    await new Promise(resolve => setTimeout(resolve, 50))
    await flushPromises()

    expect(wrapper.text()).toContain('被引蓝图标题')

    const list = wrapper.findComponent(BlueprintBlockList)
    expect(list.exists()).toBe(true)
    expect(list.props('plainMermaid')).toBe(true)
    expect(list.props('threads')).toEqual([])
    expect(list.props('readonly')).toBe(true)

    // ⭐ 预览内不开第二层弹层：子树里不存在引用预览弹层组件
    expect(wrapper.findComponent(CitationPreviewDialog).exists()).toBe(false)
  })

  it('7. 取不到被引蓝图 ⇒ CitationFallback（弹窗内容不留白）', async () => {
    api.getBlueprintDocument.mockRejectedValue(new ApiError(404, '无权访问或该蓝图不存在'))

    const wrapper = mount(CitationBlueprintPreview, {
      props: { artifactId: 'art-1', fallback: { title: '被引来源', quote: '快照内容' } },
      global: { plugins: newPlugins(), stubs: { ...DIALOG_STUBS, MermaidDiagram: true } },
    })
    await flushPromises()
    await new Promise(resolve => setTimeout(resolve, 50))
    await flushPromises()

    expect(wrapper.findComponent(CitationFallback).exists()).toBe(true)
    expect(wrapper.text()).toContain('快照内容')
  })
})
