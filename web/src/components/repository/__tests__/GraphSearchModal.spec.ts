/**
 * GraphSearchModal — 仓库级 GraphRAG 关联搜索弹窗 component 测试
 *
 * 覆盖：
 *  1. 输入查询触发搜索并展示命中片段（graphSearch 被调 + results 列表渲染）
 *  2. 切分支后搜索带正确 branch 参数（branch 经 prop 透传给 graphSearch，GSEARCH-04 红线）
 *  3. 复用 GraphRAGDiffusionTab 并喂 hop1/hop2/sourceChunks props
 *
 * vi.mock('~/api/repositories') 拦截 graphSearch；stub GraphRAGDiffusionTab 避免 Vue Flow
 * 真实渲染；stub shadcn Dialog 让弹窗内容在测试中直接渲染。
 */
import type { GraphSearchResponse } from '~/api/repositories'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { graphSearch } from '~/api/repositories'
import GraphSearchModal from '../GraphSearchModal.vue'

vi.mock('~/api/repositories', () => ({
  graphSearch: vi.fn(),
}))

// ===== 固定返回（含 results / hop1 / hop2） =====
function buildResponse(): GraphSearchResponse {
  return {
    query: '登录鉴权',
    results: [
      {
        chunk_id: 'c1',
        file_path: 'server/auth/login.py',
        line_start: 10,
        line_end: 42,
        content: 'def login(request): ...',
        score: 0.91,
        language: 'python',
      },
      {
        chunk_id: 'c2',
        file_path: 'server/auth/token.py',
        line_start: 1,
        line_end: 20,
        content: 'class Token: ...',
        score: 0.77,
      },
    ],
    hop1_neighbors: [
      {
        chunk_id: 'n1',
        file_path: 'server/auth/session.py',
        line_start: 5,
        line_end: 30,
        edge_type: 'CALL',
        weight: 0.8,
        reason: '调用 login',
        hop: 1,
      },
    ],
    hop2_neighbors: [
      {
        chunk_id: 'n2',
        file_path: 'server/auth/middleware.py',
        line_start: 1,
        line_end: 50,
        edge_type: 'IMPORT',
        weight: 0.4,
        reason: '导入 session',
        hop: 2,
      },
    ],
    graph_context: '## Graph Context\n...',
    total_tokens: 1234,
  }
}

// ===== stubs =====
const DiffusionStub = defineComponent({
  name: 'GraphRAGDiffusionTab',
  props: {
    hop1Neighbors: { type: Array, default: () => [] },
    hop2Neighbors: { type: Array, default: () => [] },
    sourceChunks: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false },
  },
  template: '<div data-testid="diffusion-stub" />',
})

const InputStub = defineComponent({
  name: 'Input',
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue'],
  template: `<input
    data-testid="query-input"
    :value="modelValue"
    @input="$emit('update:modelValue', $event.target.value)"
    @keydown="$emit('keydown', $event)"
  />`,
})

const ButtonStub = defineComponent({
  name: 'Button',
  props: { disabled: { type: Boolean, default: false } },
  template: '<button :disabled="disabled" v-bind="$attrs"><slot /></button>',
})

// Dialog 系列：始终渲染 slot，绕过 reka-ui portal/open 状态
const PassthroughStub = defineComponent({ template: '<div><slot /></div>' })

const stubs = {
  GraphRAGDiffusionTab: DiffusionStub,
  Input: InputStub,
  Button: ButtonStub,
  Dialog: PassthroughStub,
  DialogScrollContent: PassthroughStub,
  DialogHeader: PassthroughStub,
  DialogTitle: PassthroughStub,
  DialogDescription: PassthroughStub,
}

function mountModal(props: Record<string, unknown> = {}) {
  return mount(GraphSearchModal, {
    props: { repositoryId: 'repo-1', open: true, ...props },
    global: { stubs },
  })
}

async function triggerSearch(wrapper: ReturnType<typeof mountModal>, query: string) {
  await wrapper.find('[data-testid="query-input"]').setValue(query)
  const btn = wrapper.findAll('button').find(b => b.text().includes('搜索'))
  await btn!.trigger('click')
  await flushPromises()
}

describe('graphSearchModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(graphSearch).mockResolvedValue(buildResponse())
  })

  it('输入查询触发搜索并展示命中片段', async () => {
    const wrapper = mountModal()
    await triggerSearch(wrapper, '登录鉴权')

    expect(graphSearch).toHaveBeenCalledTimes(1)
    expect(graphSearch).toHaveBeenCalledWith('repo-1', expect.objectContaining({ query: '登录鉴权' }))

    // 命中片段列表渲染（2 条 results）
    const items = wrapper.findAll('li')
    expect(items.length).toBe(2)
    expect(wrapper.text()).toContain('server/auth/login.py')
    expect(wrapper.text()).toContain('server/auth/token.py')
  })

  it('切分支后搜索带正确 branch 参数（GSEARCH-04 红线）', async () => {
    const wrapper = mountModal({ branch: 'feat-a' })
    await triggerSearch(wrapper, '会话管理')

    expect(graphSearch).toHaveBeenCalledWith('repo-1', {
      query: '会话管理',
      branch: 'feat-a',
    })
  })

  it('复用 GraphRAGDiffusionTab 并喂 hop1/hop2/sourceChunks props', async () => {
    const wrapper = mountModal()
    await triggerSearch(wrapper, '登录鉴权')

    const diffusion = wrapper.findComponent(DiffusionStub)
    expect(diffusion.exists()).toBe(true)
    expect(diffusion.props('hop1Neighbors')).toHaveLength(1)
    expect(diffusion.props('hop2Neighbors')).toHaveLength(1)
    // sourceChunks 从 results 构建（2 条）
    expect(diffusion.props('sourceChunks')).toHaveLength(2)
    expect((diffusion.props('sourceChunks') as Array<{ chunk_id: string }>)[0].chunk_id).toBe('c1')
  })
})
