/**
 * pages/admin/prompts/index.vue 集成测试 ——
 *
 * 覆盖路径：
 *  1. 组件挂载后自动调用 store.loadSystemList()
 *  2. 渲染 PageHeader 标题 "Prompt 管理"
 *  3. DataTable 接收 systemList 作为 data prop
 *  4. columns 包含 slug / title / category / updated_at / is_builtin 5 个累加器
 *  5. 页面包含 category 下拉 Select，5 个分类 + 'all'
 *  6. category 切换后再次调用 loadSystemList(category)
 *  7. 点击 "新建 Prompt" → sheetOpen=true、editorMode='create'、clearCurrent 被调用
 *  8. 点击行 → sheetOpen=true、editorMode='edit'、loadDetail/loadVersions 被调用
 *  9. PromptEditor 子组件挂载存在
 *
 * Mock 策略与 PromptEditor.test.ts 一致：通过 vi.hoisted 把 mock 与 ref-like 状态提升，
 * Sheet/Tabs 家族 / DataTable / Select 全 stub 化，绕开 reka-ui DialogPortal & Teleport。
 */

import type { PromptListItem } from '~/types/prompts'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import PromptsAdminPage from '../prompts/index.vue'

// ============================================================================
// Mock —— closure 变量统一通过 vi.hoisted 提升
//
// 注意：systemList / loading 必须是真实的 vue ref，因为页面通过 storeToRefs(store)
// 解构后传递给 DataTable 的 :data="systemList" 在模板里会自动 unwrap，
// 测试断言通过 props('data') 拿到的也应是 unwrap 后的数组而非 ref-like 对象。
// ============================================================================
const mocks = vi.hoisted(() => {
  // 注意：vi.hoisted 在 vue 模块加载前运行，因此用 plain 占位 + beforeEach 注入
  return {
    loadSystemListMock: vi.fn(),
    loadDetailMock: vi.fn(),
    loadVersionsMock: vi.fn(),
    clearCurrentMock: vi.fn(),
    handleErrorMock: vi.fn(),
    systemListRef: null as unknown as ReturnType<typeof import('vue').ref<PromptListItem[]>>,
    loadingRef: null as unknown as ReturnType<typeof import('vue').ref<boolean>>,
  }
})

vi.mock('~/stores/prompts', () => ({
  usePromptsStore: () => ({
    systemList: mocks.systemListRef,
    loading: mocks.loadingRef,
    loadSystemList: mocks.loadSystemListMock,
    loadDetail: mocks.loadDetailMock,
    loadVersions: mocks.loadVersionsMock,
    clearCurrent: mocks.clearCurrentMock,
  }),
}))

vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: mocks.handleErrorMock }),
}))

// 页面经 useTableUrlState 持久化筛选/分页到 URL，需提供 vue-router 上下文
vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRoute: () => ({ query: {}, params: {}, path: '/admin/prompts' }),
    useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  }
})

// pinia storeToRefs 对真实 vue ref 是 identity 行为，这里 mock 为 identity
// 以免 createTestingPinia 之外的 setup-syntax store 解构错误。
vi.mock('pinia', async () => {
  const actual = await vi.importActual<typeof import('pinia')>('pinia')
  return {
    ...actual,
    storeToRefs: (store: Record<string, unknown>) => store,
  }
})

// ============================================================================
// Fixtures
// ============================================================================
function makeListItem(overrides: Partial<PromptListItem> = {}): PromptListItem {
  return {
    id: 'p-1',
    slug: 'chat.system.developer',
    category: 'chat_agent',
    scope: 'system',
    project: null,
    title: '开发者提示词',
    description: '开发者人格',
    is_builtin: true,
    active_version_number: 1,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-10T12:00:00Z',
    ...overrides,
  }
}

// ============================================================================
// 全 stub —— 保留 props 透传，绕开 reka-ui Teleport / DataTable 内部
// ============================================================================
function PassthroughStub(name: string) {
  return {
    name,
    template: `<div data-stub="${name}"><slot /></div>`,
  }
}

const PageContainerStub = PassthroughStub('PageContainer')
const PageHeaderStub = {
  name: 'PageHeader',
  props: ['icon', 'title', 'description'],
  template: '<header data-testid="page-header"><h1>{{ title }}</h1><p>{{ description }}</p><slot name="actions" /></header>',
}
const DataTableStub = {
  name: 'DataTable',
  props: ['data', 'columns', 'tableId', 'loading', 'onRowClick'],
  template: '<div data-testid="data-table" :data-table-id="tableId" :data-row-count="data?.length ?? 0"><slot name="filters" /></div>',
}
const PromptEditorStub = {
  name: 'PromptEditor',
  props: ['open', 'mode', 'spaceId'],
  emits: ['update:open'],
  template: '<div data-testid="prompt-editor" :data-open="open" :data-mode="mode" :data-space-id="spaceId"></div>',
}
const ButtonStub = {
  name: 'Button',
  props: ['disabled', 'variant'],
  template: '<button type="button" :disabled="disabled" :data-variant="variant"><slot /></button>',
}
const BadgeStub = {
  name: 'Badge',
  props: ['variant'],
  template: '<span :data-badge-variant="variant"><slot /></span>',
}
const SelectStub = {
  name: 'Select',
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: '<div data-testid="category-select" :data-value="modelValue"><slot /></div>',
}
const SelectTriggerStub = PassthroughStub('SelectTrigger')
const SelectContentStub = PassthroughStub('SelectContent')
const SelectItemStub = {
  name: 'SelectItem',
  props: ['value'],
  template: '<div :data-select-item="value"><slot /></div>',
}
const SelectValueStub = PassthroughStub('SelectValue')

function mountPage() {
  return mount(PromptsAdminPage, {
    global: {
      stubs: {
        PageContainer: PageContainerStub,
        PageHeader: PageHeaderStub,
        DataTable: DataTableStub,
        PromptEditor: PromptEditorStub,
        Button: ButtonStub,
        Badge: BadgeStub,
        Select: SelectStub,
        SelectTrigger: SelectTriggerStub,
        SelectContent: SelectContentStub,
        SelectItem: SelectItemStub,
        SelectValue: SelectValueStub,
      },
    },
  })
}

// ============================================================================
// Tests
// ============================================================================
describe('pages/admin/prompts/index.vue (PROMPTUI-01)', () => {
  beforeEach(() => {
    mocks.loadSystemListMock.mockReset().mockResolvedValue(undefined)
    mocks.loadDetailMock.mockReset().mockResolvedValue(undefined)
    mocks.loadVersionsMock.mockReset().mockResolvedValue(undefined)
    mocks.clearCurrentMock.mockReset()
    mocks.handleErrorMock.mockReset()
    // 在 vue 模块已加载后用真实 ref 重新挂载到 mocks（vi.hoisted 时刻 vue 尚未加载）
    mocks.systemListRef = ref<PromptListItem[]>([])
    mocks.loadingRef = ref<boolean>(false)
  })

  it('1. 组件挂载后自动调用 store.loadSystemList()', async () => {
    mountPage()
    await nextTick()
    await new Promise(r => setTimeout(r, 0))
    expect(mocks.loadSystemListMock).toHaveBeenCalled()
  })

  it('2. PageHeader 渲染中文标题 "Prompt 管理"', async () => {
    const wrapper = mountPage()
    await nextTick()
    expect(wrapper.text()).toContain('Prompt 管理')
    expect(wrapper.text()).toContain('系统级提示词编辑与版本管理')
  })

  it('3. DataTable 接收 systemList 作为 data prop', async () => {
    mocks.systemListRef.value = [makeListItem(), makeListItem({ id: 'p-2', slug: 'chat.system.code_review' })]
    const wrapper = mountPage()
    await nextTick()
    const dt = wrapper.findComponent(DataTableStub)
    expect(dt.exists()).toBe(true)
    expect(dt.props('data')).toHaveLength(2)
    expect(dt.props('tableId')).toBe('admin-prompts-list')
  })

  it('4. columns 包含 slug / title / category / updated_at / is_builtin 5 个累加器', async () => {
    const wrapper = mountPage()
    await nextTick()
    const dt = wrapper.findComponent(DataTableStub)
    const cols = dt.props('columns') as Array<Record<string, unknown>>
    expect(cols).toHaveLength(5)
    const accessors = cols.map(c => (c.accessorKey as string | undefined) ?? (c.id as string | undefined))
    expect(accessors).toContain('slug')
    expect(accessors).toContain('title')
    expect(accessors).toContain('category')
    expect(accessors).toContain('updated_at')
    expect(accessors).toContain('is_builtin')
  })

  it('5. 页面包含 category 下拉 Select，6 个 SelectItem (all + 5 categories)', async () => {
    const wrapper = mountPage()
    await nextTick()
    const items = wrapper.findAll('[data-select-item]')
    const values = items.map(i => i.attributes('data-select-item'))
    expect(values).toContain('all')
    expect(values).toContain('chat_agent')
    expect(values).toContain('ai_node')
    expect(values).toContain('aux_model')
    expect(values).toContain('feishu_bot')
    expect(values).toContain('repo_summary')
  })

  it('6. category 切换后再次调用 loadSystemList(category)', async () => {
    const wrapper = mountPage()
    await nextTick()
    await new Promise(r => setTimeout(r, 0))
    mocks.loadSystemListMock.mockClear()

    const select = wrapper.findComponent(SelectStub)
    await select.vm.$emit('update:modelValue', 'chat_agent')
    await nextTick()
    await new Promise(r => setTimeout(r, 0))

    expect(mocks.loadSystemListMock).toHaveBeenCalledWith('chat_agent')
  })

  it('7. 点击 "新建 Prompt" → editor 切到 create 模式 + clearCurrent + open=true', async () => {
    const wrapper = mountPage()
    await nextTick()
    const buttons = wrapper.findAll('button')
    const createBtn = buttons.find(b => b.text().includes('新建 Prompt'))
    expect(createBtn).toBeTruthy()
    await createBtn!.trigger('click')
    await nextTick()
    const editor = wrapper.findComponent(PromptEditorStub)
    expect(editor.props('open')).toBe(true)
    expect(editor.props('mode')).toBe('create')
    expect(mocks.clearCurrentMock).toHaveBeenCalled()
  })

  it('8. DataTable onRowClick → editor 切到 edit + loadDetail + loadVersions', async () => {
    mocks.systemListRef.value = [makeListItem({ id: 'row-7' })]
    const wrapper = mountPage()
    await nextTick()
    const dt = wrapper.findComponent(DataTableStub)
    const handler = dt.props('onRowClick') as ((row: PromptListItem) => void)
    expect(typeof handler).toBe('function')
    handler(mocks.systemListRef.value[0])
    await nextTick()
    await new Promise(r => setTimeout(r, 0))

    expect(mocks.loadDetailMock).toHaveBeenCalledWith('row-7')
    expect(mocks.loadVersionsMock).toHaveBeenCalledWith('row-7')
    const editor = wrapper.findComponent(PromptEditorStub)
    expect(editor.props('open')).toBe(true)
    expect(editor.props('mode')).toBe('edit')
  })

  it('9. PromptEditor 子组件挂载存在', async () => {
    const wrapper = mountPage()
    await nextTick()
    expect(wrapper.findComponent(PromptEditorStub).exists()).toBe(true)
  })
})
