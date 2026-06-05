/**
 * pages/spaces/[id]/prompts.vue 集成测试 ——
 *
 * 覆盖路径：
 *  1. 组件挂载后调用 store.loadProjectList(spaceId)
 *  2. 渲染 PageHeader 文案 "Prompt 覆盖" / "项目级提示词覆盖与系统级 fallback"
 *  3. DataTable 绑定 mergedProjectList 作为 data
 *  4. status='overridden' 行渲染 "项目级已覆盖" Badge variant default
 *  5. status='fallback' 行渲染 "使用系统级 fallback" Badge variant outline
 *  6. status='space_only' 行渲染 "仅项目级" Badge variant secondary
 *  7. canEdit=false 时所有操作按钮 disabled + tooltip "仅项目管理员可操作"
 *  8. canEdit=true 时 fallback 行操作按钮文案 "创建项目级副本"
 *  9. canEdit=true 时 overridden 行操作按钮文案 "编辑"
 * 10. 点击操作按钮 → sheetOpen=true（且 fallback → create / overridden → edit）
 *
 * Mock 策略：vi.hoisted 提升 closure，全 stub 化 PageContainer/PageHeader/DataTable/
 * PromptEditor/Badge/Button，绕开 reka-ui Teleport。
 * vue-router 整体 mock 为 useRoute returning { params: { id: 'test-space-id' } }。
 */

import type { ColumnDef } from '@tanstack/vue-table'
import type { MergedSpaceListItem } from '~/stores/prompts'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, h, nextTick, ref } from 'vue'
import PromptsOverridesPage from '../[id]/prompts.vue'

// ============================================================================
// Mock —— closure 通过 vi.hoisted 提升
// ============================================================================
const mocks = vi.hoisted(() => ({
  loadSpaceListMock: vi.fn(),
  loadDetailMock: vi.fn(),
  loadVersionsMock: vi.fn(),
  clearCurrentMock: vi.fn(),
  handleErrorMock: vi.fn(),
  mergedSpaceListRef: null as unknown as ReturnType<typeof import('vue').ref<MergedSpaceListItem[]>>,
  loadingRef: null as unknown as ReturnType<typeof import('vue').ref<boolean>>,
  // canEditRef 是 readonly ComputedRef<boolean>。用 import('vue').ComputedRef 类型
  canEditRef: null as unknown as import('vue').ComputedRef<boolean>,
  canEditValue: { current: true },
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: 'test-space-id' } }),
}))

vi.mock('~/stores/prompts', () => ({
  usePromptsStore: () => ({
    mergedSpaceList: mocks.mergedSpaceListRef,
    loading: mocks.loadingRef,
    loadSpaceList: mocks.loadSpaceListMock,
    loadDetail: mocks.loadDetailMock,
    loadVersions: mocks.loadVersionsMock,
    clearCurrent: mocks.clearCurrentMock,
  }),
}))

vi.mock('~/composables/usePermission', () => ({
  usePermission: () => ({ canEdit: mocks.canEditRef }),
}))

vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: mocks.handleErrorMock }),
}))

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
function makeMerged(overrides: Partial<MergedSpaceListItem>): MergedSpaceListItem {
  return {
    id: 'm-1',
    slug: 'chat.system.developer',
    category: 'chat_agent',
    scope: 'system',
    project: null,
    title: '开发者',
    description: '',
    is_builtin: true,
    active_version_number: 1,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-10T12:00:00Z',
    status: 'fallback',
    space_prompt: null,
    ...overrides,
  }
}

const overriddenRow: MergedSpaceListItem = makeMerged({
  id: 'sys-overridden',
  slug: 'chat.system.developer',
  status: 'overridden',
  space_prompt: makeMerged({
    id: 'proj-override-1',
    slug: 'chat.system.developer',
    scope: 'project',
    is_builtin: false,
  }),
})
const fallbackRow: MergedSpaceListItem = makeMerged({
  id: 'sys-fallback',
  slug: 'chat.system.code_review',
  status: 'fallback',
  space_prompt: null,
})
const spaceOnlyRow: MergedSpaceListItem = makeMerged({
  id: 'proj-only',
  slug: 'space.custom.greeting',
  scope: 'project',
  is_builtin: false,
  status: 'space_only',
  space_prompt: null,
})

// ============================================================================
// Stubs
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
  template: '<header data-testid="page-header"><h1>{{ title }}</h1><p>{{ description }}</p></header>',
}
const DataTableStub = {
  name: 'DataTable',
  props: ['data', 'columns', 'tableId', 'loading'],
  template: '<div data-testid="data-table" :data-table-id="tableId"></div>',
}
const PromptEditorStub = {
  name: 'PromptEditor',
  props: ['open', 'mode', 'spaceId'],
  emits: ['update:open'],
  template: '<div data-testid="prompt-editor" :data-open="open" :data-mode="mode" :data-space-id="spaceId"></div>',
}
const ButtonStub = {
  name: 'Button',
  props: ['disabled', 'variant', 'size', 'title'],
  emits: ['click'],
  template: '<button type="button" :disabled="disabled" :title="title" :data-variant="variant"><slot /></button>',
}
const BadgeStub = {
  name: 'Badge',
  props: ['variant'],
  template: '<span :data-badge-variant="variant"><slot /></span>',
}

function mountPage() {
  return mount(PromptsOverridesPage, {
    global: {
      stubs: {
        PageContainer: PageContainerStub,
        PageHeader: PageHeaderStub,
        DataTable: DataTableStub,
        PromptEditor: PromptEditorStub,
        Button: ButtonStub,
        Badge: BadgeStub,
      },
    },
  })
}

// ============================================================================
// 帮助函数：通过 columns 配置直接调用 cell renderer 取得 VNode 并断言
// ============================================================================
function findColumn(
  cols: ColumnDef<MergedSpaceListItem>[],
  key: string,
): ColumnDef<MergedSpaceListItem> {
  const col = cols.find(
    c =>
      ('accessorKey' in c && c.accessorKey === key)
      || ('id' in c && c.id === key),
  )
  if (!col)
    throw new Error(`column ${key} not found`)
  return col
}

function callCell(
  col: ColumnDef<MergedSpaceListItem>,
  row: MergedSpaceListItem,
): unknown {
  // tanstack column.cell 通常接收 { row: { original } } 上下文
  const cell = col.cell as ((ctx: unknown) => unknown) | undefined
  if (!cell)
    throw new Error('column has no cell renderer')
  return cell({ row: { original: row } })
}

/**
 * Vue 3 h(Component, props, slot) 第三参数若为 () => 子节点 函数，
 * vue 在 createBlock 阶段会包装为 { default: fn, _: 1 } slot 对象。
 * 此 helper 统一从 vnode.children 提取 default slot 调用结果。
 */
function callDefaultSlot(vnode: { children?: unknown }): string {
  const children = vnode.children
  if (typeof children === 'function')
    return (children as () => string)()
  if (children && typeof children === 'object' && 'default' in children) {
    const slot = (children as { default: () => unknown }).default
    if (typeof slot === 'function') {
      const result = slot()
      // slot() 可能返回 string | string[] | VNode[]
      if (Array.isArray(result))
        return result.map(r => (typeof r === 'string' ? r : '')).join('')
      return String(result)
    }
  }
  if (typeof children === 'string')
    return children
  return ''
}

// ============================================================================
// Tests
// ============================================================================
describe('pages/spaces/[id]/prompts.vue (PROMPTUI-03)', () => {
  beforeEach(() => {
    mocks.loadSpaceListMock.mockReset().mockResolvedValue(undefined)
    mocks.loadDetailMock.mockReset().mockResolvedValue(undefined)
    mocks.loadVersionsMock.mockReset().mockResolvedValue(undefined)
    mocks.clearCurrentMock.mockReset()
    mocks.handleErrorMock.mockReset()
    mocks.mergedSpaceListRef = ref<MergedSpaceListItem[]>([])
    mocks.loadingRef = ref<boolean>(false)
    mocks.canEditValue.current = true
    mocks.canEditRef = computed(() => mocks.canEditValue.current)
  })

  it('1. 组件挂载后调用 store.loadSpaceList(spaceId)', async () => {
    mountPage()
    await nextTick()
    await new Promise(r => setTimeout(r, 0))
    expect(mocks.loadSpaceListMock).toHaveBeenCalledWith('test-space-id')
  })

  it('2. PageHeader 渲染中文标题 "Prompt 覆盖"', async () => {
    const wrapper = mountPage()
    await nextTick()
    expect(wrapper.text()).toContain('Prompt 覆盖')
    expect(wrapper.text()).toContain('空间级提示词覆盖与系统级 fallback')
  })

  it('3. DataTable 绑定 mergedProjectList 作为 data', async () => {
    mocks.mergedSpaceListRef.value = [overriddenRow, fallbackRow]
    const wrapper = mountPage()
    await nextTick()
    const dt = wrapper.findComponent(DataTableStub)
    expect(dt.exists()).toBe(true)
    expect(dt.props('data')).toHaveLength(2)
    expect(dt.props('tableId')).toBe('space-prompts-list')
  })

  it('4. status="overridden" 渲染 Badge variant=default 文案 "空间级已覆盖"', async () => {
    const wrapper = mountPage()
    await nextTick()
    const dt = wrapper.findComponent(DataTableStub)
    const cols = dt.props('columns') as ColumnDef<MergedSpaceListItem>[]
    const statusCol = findColumn(cols, 'status')
    const vnode = callCell(statusCol, overriddenRow) as { props?: Record<string, unknown>, children?: unknown }
    expect(vnode).toBeTruthy()
    expect(vnode.props?.variant).toBe('default')
    expect(callDefaultSlot(vnode)).toBe('空间级已覆盖')
  })

  it('5. status="fallback" 渲染 Badge variant=outline 文案 "使用系统级 fallback"', async () => {
    const wrapper = mountPage()
    await nextTick()
    const dt = wrapper.findComponent(DataTableStub)
    const cols = dt.props('columns') as ColumnDef<MergedSpaceListItem>[]
    const statusCol = findColumn(cols, 'status')
    const vnode = callCell(statusCol, fallbackRow) as { props?: Record<string, unknown>, children?: unknown }
    expect(vnode.props?.variant).toBe('outline')
    expect(callDefaultSlot(vnode)).toBe('使用系统级 fallback')
  })

  it('6. status="project_only" 渲染 Badge variant=secondary 文案 "仅空间级"', async () => {
    const wrapper = mountPage()
    await nextTick()
    const dt = wrapper.findComponent(DataTableStub)
    const cols = dt.props('columns') as ColumnDef<MergedSpaceListItem>[]
    const statusCol = findColumn(cols, 'status')
    const vnode = callCell(statusCol, spaceOnlyRow) as { props?: Record<string, unknown>, children?: unknown }
    expect(vnode.props?.variant).toBe('secondary')
    expect(callDefaultSlot(vnode)).toBe('仅空间级')
  })

  it('7. canEdit=false 时所有操作按钮 disabled + tooltip "仅空间管理员可操作"', async () => {
    mocks.canEditValue.current = false
    const wrapper = mountPage()
    await nextTick()
    const dt = wrapper.findComponent(DataTableStub)
    const cols = dt.props('columns') as ColumnDef<MergedSpaceListItem>[]
    const actionsCol = findColumn(cols, 'actions')
    const vnode = callCell(actionsCol, fallbackRow) as { props?: Record<string, unknown> }
    expect(vnode.props?.disabled).toBe(true)
    expect(vnode.props?.title).toBe('仅空间管理员可操作')
  })

  it('8. canEdit=true 时 fallback 行操作按钮文案 "创建空间级副本"', async () => {
    mocks.canEditValue.current = true
    const wrapper = mountPage()
    await nextTick()
    const dt = wrapper.findComponent(DataTableStub)
    const cols = dt.props('columns') as ColumnDef<MergedSpaceListItem>[]
    const actionsCol = findColumn(cols, 'actions')
    const vnode = callCell(actionsCol, fallbackRow) as { children?: unknown }
    expect(callDefaultSlot(vnode)).toBe('创建空间级副本')
  })

  it('9. canEdit=true 时 overridden 行操作按钮文案 "编辑"', async () => {
    const wrapper = mountPage()
    await nextTick()
    const dt = wrapper.findComponent(DataTableStub)
    const cols = dt.props('columns') as ColumnDef<MergedSpaceListItem>[]
    const actionsCol = findColumn(cols, 'actions')
    const vnode = callCell(actionsCol, overriddenRow) as { children?: unknown }
    expect(callDefaultSlot(vnode)).toBe('编辑')
  })

  it('10. 点击 fallback 行按钮 → editor 切到 create + clearCurrent + open=true', async () => {
    const wrapper = mountPage()
    await nextTick()
    const dt = wrapper.findComponent(DataTableStub)
    const cols = dt.props('columns') as ColumnDef<MergedSpaceListItem>[]
    const actionsCol = findColumn(cols, 'actions')
    const vnode = callCell(actionsCol, fallbackRow) as {
      props?: { onClick?: () => void }
    }
    expect(typeof vnode.props?.onClick).toBe('function')
    vnode.props!.onClick!()
    await nextTick()
    const editor = wrapper.findComponent(PromptEditorStub)
    expect(editor.props('open')).toBe(true)
    expect(editor.props('mode')).toBe('create')
    expect(editor.props('spaceId')).toBe('test-space-id')
    expect(mocks.clearCurrentMock).toHaveBeenCalled()
  })

  it('11. 点击 overridden 行按钮 → editor 切到 edit + 用 space_prompt.id 调 loadDetail', async () => {
    const wrapper = mountPage()
    await nextTick()
    const dt = wrapper.findComponent(DataTableStub)
    const cols = dt.props('columns') as ColumnDef<MergedSpaceListItem>[]
    const actionsCol = findColumn(cols, 'actions')
    const vnode = callCell(actionsCol, overriddenRow) as { props?: { onClick?: () => void } }
    vnode.props!.onClick!()
    await nextTick()
    await new Promise(r => setTimeout(r, 0))
    const editor = wrapper.findComponent(PromptEditorStub)
    expect(editor.props('open')).toBe(true)
    expect(editor.props('mode')).toBe('edit')
    // overridden 行应使用 space_prompt.id 而非系统级 row.id
    expect(mocks.loadDetailMock).toHaveBeenCalledWith('proj-override-1')
    expect(mocks.loadVersionsMock).toHaveBeenCalledWith('proj-override-1')
  })

  it('12. canEdit=false 时点击按钮被早拒（onClick 直接 return，不调 store action）', async () => {
    mocks.canEditValue.current = false
    const wrapper = mountPage()
    await nextTick()
    const dt = wrapper.findComponent(DataTableStub)
    const cols = dt.props('columns') as ColumnDef<MergedSpaceListItem>[]
    const actionsCol = findColumn(cols, 'actions')
    const vnode = callCell(actionsCol, overriddenRow) as { props?: { onClick?: () => void } }
    vnode.props!.onClick!()
    await nextTick()
    expect(mocks.loadDetailMock).not.toHaveBeenCalled()
    expect(mocks.clearCurrentMock).not.toHaveBeenCalled()
  })
})

// ============================================================================
// 显式占位以满足 ESLint top-level h import 不被 tree-shake（避免 unused 警告）
// ============================================================================
void h
