/**
 * pages/projects/[id]/prompts.vue 集成测试 —— Phase Plan Task 2
 *
 * 覆盖路径（Plan Task 2 behavior §1-§10）：
 * 1. 组件挂载后调用 store.loadProjectList(projectId)
 * 2. 渲染 PageHeader 文案 "Prompt 覆盖" / "项目级提示词覆盖与系统级 fallback"
 * 3. DataTable 绑定 mergedProjectList 作为 data
 * 4. status='overridden' 行渲染 "项目级已覆盖" Badge variant default
 * 5. status='fallback' 行渲染 "使用系统级 fallback" Badge variant outline
 * 6. status='project_only' 行渲染 "仅项目级" Badge variant secondary
 * 7. canEdit=false 时所有操作按钮 disabled + tooltip "仅项目管理员可操作"
 * 8. canEdit=true 时 fallback 行操作按钮文案 "创建项目级副本"
 * 9. canEdit=true 时 overridden 行操作按钮文案 "编辑"
 * 10. 点击操作按钮 → sheetOpen=true（且 fallback → create / overridden → edit）
 *
 * Mock 策略：vi.hoisted 提升 closure，全 stub 化 PageContainer/PageHeader/DataTable/
 * PromptEditor/Badge/Button，绕开 reka-ui Teleport。
 * vue-router 整体 mock 为 useRoute returning { params: { id: 'test-project-id' } }。
 */
import type { ColumnDef } from '@tanstack/vue-table'
import type { MergedProjectListItem } from '~/stores/prompts'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, h, nextTick, ref } from 'vue'
import PromptsOverridesPage from '../[id]/prompts.vue'
// ============================================================================
// Mock —— closure 通过 vi.hoisted 提升
// ============================================================================
const mocks = vi.hoisted( => ({
 loadProjectListMock: vi.fn,
 loadDetailMock: vi.fn,
 loadVersionsMock: vi.fn,
 clearCurrentMock: vi.fn,
 handleErrorMock: vi.fn,
 mergedProjectListRef: null as unknown as ReturnType<typeof import('vue').ref<MergedProjectListItem>>,
 loadingRef: null as unknown as ReturnType<typeof import('vue').ref<boolean>>,
 canEditRef: null as unknown as ReturnType<typeof import('vue').computed<boolean>>,
 canEditValue: { current: true },
}))
vi.mock('vue-router', => ({
 useRoute: => ({ params: { id: 'test-project-id' } }),
}))
vi.mock('~/stores/prompts', => ({
 usePromptsStore: => ({
 mergedProjectList: mocks.mergedProjectListRef,
 loading: mocks.loadingRef,
 loadProjectList: mocks.loadProjectListMock,
 loadDetail: mocks.loadDetailMock,
 loadVersions: mocks.loadVersionsMock,
 clearCurrent: mocks.clearCurrentMock,
 }),
}))
vi.mock('~/composables/usePermission', => ({
 usePermission: => ({ canEdit: mocks.canEditRef }),
}))
vi.mock('~/composables/useErrorHandler', => ({
 useErrorHandler: => ({ handleError: mocks.handleErrorMock }),
}))
vi.mock('pinia', async => {
 const actual = await vi.importActual<typeof import('pinia')>('pinia')
 return {
 ...actual,
 storeToRefs: (store: Record<string, unknown>) => store,
 }
})
// ============================================================================
// Fixtures
// ============================================================================
function makeMerged(overrides: Partial<MergedProjectListItem>): MergedProjectListItem {
 return {
 id: '',
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
 project_prompt: null,
 ...overrides,
 }
}
const overriddenRow: MergedProjectListItem = makeMerged({
 id: 'sys-overridden',
 slug: 'chat.system.developer',
 status: 'overridden',
 project_prompt: makeMerged({
 id: 'proj-override-1',
 slug: 'chat.system.developer',
 scope: 'project',
 project: 'test-project-id',
 is_builtin: false,
 }),
})
const fallbackRow: MergedProjectListItem = makeMerged({
 id: 'sys-fallback',
 slug: 'chat.system.code_review',
 status: 'fallback',
 project_prompt: null,
})
const projectOnlyRow: MergedProjectListItem = makeMerged({
 id: 'proj-only',
 slug: 'project.custom.greeting',
 scope: 'project',
 project: 'test-project-id',
 is_builtin: false,
 status: 'project_only',
 project_prompt: null,
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
 template: '<div data-testid="data-table":data-table-id="tableId"></div>',
}
const PromptEditorStub = {
 name: 'PromptEditor',
 props: ['open', 'mode', 'projectId'],
 emits: ['update:open'],
 template: '<div data-testid="prompt-editor":data-open="open":data-mode="mode":data-project-id="projectId"></div>',
}
const ButtonStub = {
 name: 'Button',
 props: ['disabled', 'variant', 'size', 'title'],
 emits: ['click'],
 template: '<button type="button":disabled="disabled":title="title":data-variant="variant"><slot /></button>',
}
const BadgeStub = {
 name: 'Badge',
 props: ['variant'],
 template: '<span:data-badge-variant="variant"><slot /></span>',
}
function mountPage {
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
 cols: ColumnDef<MergedProjectListItem>,
 key: string,
): ColumnDef<MergedProjectListItem> {
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
 col: ColumnDef<MergedProjectListItem>,
 row: MergedProjectListItem,
): unknown {
 // tanstack column.cell 通常接收 { row: { original } } 上下文
 const cell = col.cell as ((ctx: unknown) => unknown) | undefined
 if (!cell)
 throw new Error('column has no cell renderer')
 return cell({ row: { original: row } })
}
// ============================================================================
// Tests
// ============================================================================
describe('pages/projects/[id]/prompts.vue ', => {
 beforeEach( => {
 mocks.loadProjectListMock.mockReset.mockResolvedValue(undefined)
 mocks.loadDetailMock.mockReset.mockResolvedValue(undefined)
 mocks.loadVersionsMock.mockReset.mockResolvedValue(undefined)
 mocks.clearCurrentMock.mockReset
 mocks.handleErrorMock.mockReset
 mocks.mergedProjectListRef = ref<MergedProjectListItem>
 mocks.loadingRef = ref<boolean>(false)
 mocks.canEditValue.current = true
 mocks.canEditRef = computed( => mocks.canEditValue.current)
 })
 it('1. 组件挂载后调用 store.loadProjectList(projectId)', async => {
 mountPage
 await nextTick
 await new Promise(r => setTimeout(r, 0))
 expect(mocks.loadProjectListMock).toHaveBeenCalledWith('test-project-id')
 })
 it('2. PageHeader 渲染中文标题 "Prompt 覆盖"', async => {
 const wrapper = mountPage
 await nextTick
 expect(wrapper.text).toContain('Prompt 覆盖')
 expect(wrapper.text).toContain('项目级提示词覆盖与系统级 fallback')
 })
 it('3. DataTable 绑定 mergedProjectList 作为 data', async => {
 mocks.mergedProjectListRef.value = [overriddenRow, fallbackRow]
 const wrapper = mountPage
 await nextTick
 const dt = wrapper.findComponent(DataTableStub)
 expect(dt.exists).toBe(true)
 expect(dt.props('data')).toHaveLength(2)
 expect(dt.props('tableId')).toBe('project-prompts-list')
 })
 it('4. status="overridden" 渲染 Badge variant=default 文案 "项目级已覆盖"', async => {
 const wrapper = mountPage
 await nextTick
 const dt = wrapper.findComponent(DataTableStub)
 const cols = dt.props('columns') as ColumnDef<MergedProjectListItem>
 const statusCol = findColumn(cols, 'status')
 const vnode = callCell(statusCol, overriddenRow) as { props?: Record<string, unknown>, children?: unknown }
 expect(vnode).toBeTruthy
 // h(Badge, { variant: 'default' }, => '项目级已覆盖')
 expect(vnode.props?.variant).toBe('default')
 // children 是 => string slot
 const slot = vnode.children as => string
 expect(slot).toBe('项目级已覆盖')
 })
 it('5. status="fallback" 渲染 Badge variant=outline 文案 "使用系统级 fallback"', async => {
 const wrapper = mountPage
 await nextTick
 const dt = wrapper.findComponent(DataTableStub)
 const cols = dt.props('columns') as ColumnDef<MergedProjectListItem>
 const statusCol = findColumn(cols, 'status')
 const vnode = callCell(statusCol, fallbackRow) as { props?: Record<string, unknown>, children?: unknown }
 expect(vnode.props?.variant).toBe('outline')
 expect((vnode.children as => string)).toBe('使用系统级 fallback')
 })
 it('6. status="project_only" 渲染 Badge variant=secondary 文案 "仅项目级"', async => {
 const wrapper = mountPage
 await nextTick
 const dt = wrapper.findComponent(DataTableStub)
 const cols = dt.props('columns') as ColumnDef<MergedProjectListItem>
 const statusCol = findColumn(cols, 'status')
 const vnode = callCell(statusCol, projectOnlyRow) as { props?: Record<string, unknown>, children?: unknown }
 expect(vnode.props?.variant).toBe('secondary')
 expect((vnode.children as => string)).toBe('仅项目级')
 })
 it('7. canEdit=false 时所有操作按钮 disabled + tooltip "仅项目管理员可操作"', async => {
 mocks.canEditValue.current = false
 const wrapper = mountPage
 await nextTick
 const dt = wrapper.findComponent(DataTableStub)
 const cols = dt.props('columns') as ColumnDef<MergedProjectListItem>
 const actionsCol = findColumn(cols, 'actions')
 const vnode = callCell(actionsCol, fallbackRow) as { props?: Record<string, unknown> }
 expect(vnode.props?.disabled).toBe(true)
 expect(vnode.props?.title).toBe('仅项目管理员可操作')
 })
 it('8. canEdit=true 时 fallback 行操作按钮文案 "创建项目级副本"', async => {
 mocks.canEditValue.current = true
 const wrapper = mountPage
 await nextTick
 const dt = wrapper.findComponent(DataTableStub)
 const cols = dt.props('columns') as ColumnDef<MergedProjectListItem>
 const actionsCol = findColumn(cols, 'actions')
 const vnode = callCell(actionsCol, fallbackRow) as { children?: unknown }
 const label = (vnode.children as => string)
 expect(label).toBe('创建项目级副本')
 })
 it('9. canEdit=true 时 overridden 行操作按钮文案 "编辑"', async => {
 const wrapper = mountPage
 await nextTick
 const dt = wrapper.findComponent(DataTableStub)
 const cols = dt.props('columns') as ColumnDef<MergedProjectListItem>
 const actionsCol = findColumn(cols, 'actions')
 const vnode = callCell(actionsCol, overriddenRow) as { children?: unknown }
 expect((vnode.children as => string)).toBe('编辑')
 })
 it('10. 点击 fallback 行按钮 → editor 切到 create + clearCurrent + open=true', async => {
 const wrapper = mountPage
 await nextTick
 const dt = wrapper.findComponent(DataTableStub)
 const cols = dt.props('columns') as ColumnDef<MergedProjectListItem>
 const actionsCol = findColumn(cols, 'actions')
 const vnode = callCell(actionsCol, fallbackRow) as {
 props?: { onClick?: => void }
 }
 expect(typeof vnode.props?.onClick).toBe('function')
 vnode.props!.onClick!
 await nextTick
 const editor = wrapper.findComponent(PromptEditorStub)
 expect(editor.props('open')).toBe(true)
 expect(editor.props('mode')).toBe('create')
 expect(editor.props('projectId')).toBe('test-project-id')
 expect(mocks.clearCurrentMock).toHaveBeenCalled
 })
 it('11. 点击 overridden 行按钮 → editor 切到 edit + 用 project_prompt.id 调 loadDetail', async => {
 const wrapper = mountPage
 await nextTick
 const dt = wrapper.findComponent(DataTableStub)
 const cols = dt.props('columns') as ColumnDef<MergedProjectListItem>
 const actionsCol = findColumn(cols, 'actions')
 const vnode = callCell(actionsCol, overriddenRow) as { props?: { onClick?: => void } }
 vnode.props!.onClick!
 await nextTick
 await new Promise(r => setTimeout(r, 0))
 const editor = wrapper.findComponent(PromptEditorStub)
 expect(editor.props('open')).toBe(true)
 expect(editor.props('mode')).toBe('edit')
 // overridden 行应使用 project_prompt.id 而非系统级 row.id
 expect(mocks.loadDetailMock).toHaveBeenCalledWith('proj-override-1')
 expect(mocks.loadVersionsMock).toHaveBeenCalledWith('proj-override-1')
 })
 it('12. canEdit=false 时点击按钮被早拒（onClick 直接 return，不调 store action）', async => {
 mocks.canEditValue.current = false
 const wrapper = mountPage
 await nextTick
 const dt = wrapper.findComponent(DataTableStub)
 const cols = dt.props('columns') as ColumnDef<MergedProjectListItem>
 const actionsCol = findColumn(cols, 'actions')
 const vnode = callCell(actionsCol, overriddenRow) as { props?: { onClick?: => void } }
 vnode.props!.onClick!
 await nextTick
 expect(mocks.loadDetailMock).not.toHaveBeenCalled
 expect(mocks.clearCurrentMock).not.toHaveBeenCalled
 })
})
// ============================================================================
// 显式占位以满足 ESLint top-level h import 不被 tree-shake（避免 unused 警告）
// ============================================================================
void h
