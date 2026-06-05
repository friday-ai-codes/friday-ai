/**
 * — Playground Tabs 容器单测
 * 验证：默认 layers tab + 切换 graphrag tab 不丢 searchResult
 *      + GraphRAGDiffusionTab 收到 hop1/hop2 props
 *      + onDiffusionNodeClick 打开 drawer 并写入 selectedChunkId
 */
import type { PlaygroundSearchResponse } from '~/api/codegraph'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PlaygroundPage from '~/pages/codegraph/playground.vue'

vi.mock('~/api/codegraph', async () => {
  const actual = await vi.importActual<typeof import('~/api/codegraph')>(
    '~/api/codegraph',
  )
  return {
    ...actual,
    playgroundSearch: vi.fn(),
  }
})

vi.mock('~/api/repositories', () => ({
  repositoriesApi: {
    list: vi.fn().mockResolvedValue({ count: 0, results: [] }),
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn(),
  }),
}))

vi.mock('~/components/codegraph/PlaygroundQueryInput.vue', () => ({
  default: {
    name: 'PlaygroundQueryInput',
    props: ['loading'],
    emits: ['search', 'chat-prefill'],
    template: '<div class="stub-playgroundqueryinput" />',
  },
}))
vi.mock('~/components/codegraph/LayerResultsAccordion.vue', () => ({
  default: {
    name: 'LayerResultsAccordion',
    props: ['result', 'loading'],
    template: '<div class="stub-layerresultsaccordion" />',
  },
}))
vi.mock('~/components/codegraph/GraphRAGDiffusionTab.vue', () => ({
  default: {
    name: 'GraphRAGDiffusionTab',
    props: ['hop1Neighbors', 'hop2Neighbors', 'sourceChunks', 'loading'],
    emits: ['node-click'],
    template: '<div class="stub-graphragdiffusiontab" />',
  },
}))
vi.mock('~/components/codegraph/CodePreviewDrawer.vue', () => ({
  default: {
    name: 'CodePreviewDrawer',
    props: ['open', 'chunkId', 'searchResult'],
    emits: ['update:open'],
    template: '<div class="stub-codepreviewdrawer" />',
  },
}))

vi.mock('~/components/ui/tabs', () => ({
  Tabs: {
    name: 'TabsStub',
    props: {
      modelValue: { type: String, default: 'layers' },
    },
    emits: ['update:modelValue'],
    template: `<div class="stub-tabs" :data-active-tab="modelValue"><slot /></div>`,
  },
  TabsList: {
    name: 'TabsListStub',
    template: '<div class="stub-tabs-list"><slot /></div>',
  },
  TabsTrigger: {
    name: 'TabsTriggerStub',
    props: { value: { type: String, required: true } },
    template: '<button class="stub-tabs-trigger" :data-value="value"><slot /></button>',
  },
  TabsContent: {
    name: 'TabsContentStub',
    props: { value: { type: String, required: true } },
    template: '<div class="stub-tabs-content" :data-value="value"><slot /></div>',
  },
}))

const HOP1 = [
  {
    chunk_id: 'chunk-hop1-aaa',
    file_path: 'src/auth/login.py',
    line_start: 10,
    line_end: 42,
    edge_type: 'CALL' as const,
    weight: 0.85,
    reason: 'L3 命中调用',
    hop: 1 as const,
  },
]

const HOP2 = [
  {
    chunk_id: 'chunk-hop2-bbb',
    file_path: 'src/auth/utils.py',
    line_start: null,
    line_end: null,
    edge_type: 'IMPORT' as const,
    weight: 0.42,
    reason: '二跳 import',
    hop: 2 as const,
  },
]

const MOCK_RESPONSE: PlaygroundSearchResponse = {
  query: 'auth login',
  repository_ids: ['repo-1'],
  layers: [],
  final_context: '# ctx',
  total_tokens: 300,
  hop1_neighbors: HOP1,
  hop2_neighbors: HOP2,
  graph_context: '### Graph Context',
}

const L3_ITEMS = [
  {
    chunk_id: 'src-1-aaa',
    file_path: 'src/auth/login.py',
    line_start: 1,
    line_end: 30,
    content: 'def login(): ...',
  },
  {
    chunk_id: 'src-2-bbb',
    file_path: 'src/auth/utils.py',
    line_start: null,
    line_end: null,
    content: 'def helper(): ...',
  },
  // 缺 chunk_id（应被 extractSourceChunks 跳过）
  {
    file_path: 'src/no-id.py',
    line_start: 1,
    line_end: 5,
  },
  // 非 object（应跳过）
  null,
]

const MOCK_RESPONSE_WITH_L3: PlaygroundSearchResponse = {
  ...MOCK_RESPONSE,
  layers: [
    { layer: 'L1', status: 'ok', result_count: 0, items: [], error: null, extra: null },
    { layer: 'L3', status: 'ok', result_count: L3_ITEMS.length, items: L3_ITEMS, error: null, extra: null },
  ],
}

describe('playgroundPage Tabs', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('a: 默认 activeTab 等于 layers（per UI-SPEC §10 硬约束 16）', async () => {
    const wrapper = mount(PlaygroundPage)
    await flushPromises()
    const tabsRoot = wrapper.find('.stub-tabs')
    expect(tabsRoot.exists()).toBe(true)
    expect(tabsRoot.attributes('data-active-tab')).toBe('layers')
  })

  it('b: 切换到 graphrag tab 时 searchResult 不丢失，playgroundSearch 仅调一次', async () => {
    const codegraph = await import('~/api/codegraph')
    const playgroundSearchMock = vi.mocked(codegraph.playgroundSearch)
    playgroundSearchMock.mockResolvedValue(MOCK_RESPONSE)

    const wrapper = mount(PlaygroundPage)
    await flushPromises()

    // 触发一次 search
    const queryStub = wrapper.findComponent({ name: 'PlaygroundQueryInput' })
    queryStub.vm.$emit('search', { query: 'auth login' })
    await flushPromises()

    expect(playgroundSearchMock).toHaveBeenCalledTimes(1)

    // 切换 tab → graphrag
    const tabsRoot = wrapper.findComponent({ name: 'TabsStub' })
    tabsRoot.vm.$emit('update:modelValue', 'graphrag')
    await flushPromises()

    // searchResult 仍然存在 → GraphRAGDiffusionTab 收到非空 hop1
    const graphRagStub = wrapper.findComponent({ name: 'GraphRAGDiffusionTab' })
    expect(graphRagStub.props('hop1Neighbors')).toEqual(HOP1)

    // playgroundSearch 仅调一次（per UI-SPEC §11 不变量 1：tab 切换不重发请求）
    expect(playgroundSearchMock).toHaveBeenCalledTimes(1)
  })

  it('c: GraphRAGDiffusionTab 收到 hop1Neighbors / hop2Neighbors props', async () => {
    const codegraph = await import('~/api/codegraph')
    const playgroundSearchMock = vi.mocked(codegraph.playgroundSearch)
    playgroundSearchMock.mockResolvedValue(MOCK_RESPONSE)

    const wrapper = mount(PlaygroundPage)
    await flushPromises()

    const queryStub = wrapper.findComponent({ name: 'PlaygroundQueryInput' })
    queryStub.vm.$emit('search', { query: 'auth login' })
    await flushPromises()

    const graphRagStub = wrapper.findComponent({ name: 'GraphRAGDiffusionTab' })
    expect(graphRagStub.exists()).toBe(true)
    expect(graphRagStub.props('hop1Neighbors')).toEqual(HOP1)
    expect(graphRagStub.props('hop2Neighbors')).toEqual(HOP2)
    expect(graphRagStub.props('sourceChunks')).toEqual([])
    expect(graphRagStub.props('loading')).toBe(false)
  })

  it('cr-01: extractSourceChunks 从 L3 layers items 反查抽取 source chunks（含 chunk_id / file_path 校验）', async () => {
    const codegraph = await import('~/api/codegraph')
    const playgroundSearchMock = vi.mocked(codegraph.playgroundSearch)
    playgroundSearchMock.mockResolvedValue(MOCK_RESPONSE_WITH_L3)

    const wrapper = mount(PlaygroundPage)
    await flushPromises()

    const queryStub = wrapper.findComponent({ name: 'PlaygroundQueryInput' })
    queryStub.vm.$emit('search', { query: 'auth login' })
    await flushPromises()

    const graphRagStub = wrapper.findComponent({ name: 'GraphRAGDiffusionTab' })
    const sources = graphRagStub.props('sourceChunks') as Array<Record<string, unknown>>
    expect(sources).toHaveLength(2)
    expect(sources[0]).toEqual({
      chunk_id: 'src-1-aaa',
      file_path: 'src/auth/login.py',
      line_start: 1,
      line_end: 30,
      content: 'def login(): ...',
    })
    expect(sources[1].chunk_id).toBe('src-2-bbb')
    expect(sources[1].line_start).toBeNull()
    expect(sources[1].line_end).toBeNull()
  })

  it('d: onDiffusionNodeClick 打开 drawer 并写入 selectedChunkId', async () => {
    const wrapper = mount(PlaygroundPage)
    await flushPromises()

    const drawerStub = wrapper.findComponent({ name: 'CodePreviewDrawer' })
    expect(drawerStub.props('open')).toBe(false)
    expect(drawerStub.props('chunkId')).toBeNull()

    const graphRagStub = wrapper.findComponent({ name: 'GraphRAGDiffusionTab' })
    graphRagStub.vm.$emit('node-click', 'chunk-x')
    await flushPromises()

    expect(drawerStub.props('open')).toBe(true)
    expect(drawerStub.props('chunkId')).toBe('chunk-x')
  })
})
