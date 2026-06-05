/**
 * PromptEditor.vue 单元测试
 *
 * 覆盖路径：
 *  1. open=false 时 Sheet 不渲染内容
 *  2. open=true + mode='edit' + currentPrompt 加载后 → 渲染 4 个 Tab 触发器
 *  3. open=true + mode='create' → 仅 3 个 Tab（版本历史 Tab 被 v-if 隐藏）
 *  4. SheetContent 包含 sm:!max-w-3xl 和 w-full class
 *  5. 所有 TabsContent 包含 force-mount 属性
 *  6. body 初始与 currentPrompt.active_version.body 相同时 isDirty=false，保存按钮 disabled
 *  7. body 修改后 isDirty=true，保存按钮 enabled
 *  8. 点击保存 → confirm 被调用 → store.updatePrompt 被调用 → emit update:open=false
 *  9. dirty=true 时用户关闭 Sheet → confirm 拦截；返回 true 才关闭；返回 false 强制保持 open=true
 * 10. PromptBodyEditor 通过 v-model 绑定 editedBody（状态提升到 PromptEditor 外层）
 *
 * Mock 策略：
 *  - ~/stores/prompts：usePromptsStore 返回全部 state ref-like + action mock
 *  - ~/composables/useConfirmDialog：confirm mock 返回 Promise
 *  - ~/composables/useToast & useErrorHandler：success/error/handleError mock
 *  - Sheet/Tabs 家族以及子组件透传渲染到默认 DOM 以便 class 断言
 *
 * vitest 与 ESLint 兼容：vi.mock 会被 vitest 自动 hoist 到文件顶部，所以 closure
 * 变量必须通过 vi.hoisted() 一并 hoist；mock 中 currentPrompt / versions / saving
 * 使用 plain `{ value: T }` 对象而非真正的 ref —— 每个测试在 mount 前直接赋值，
 * 组件 setup 期的 `computed(() => storeCurrentPrompt.value)` 会读到当前快照。
 */

import type { PromptDetail } from '~/types/prompts'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import PromptEditor from '../PromptEditor.vue'

// ============================================================================
// 模块 mock —— 所有 closure 变量通过 vi.hoisted 与 vi.mock 工厂一同提升
// ============================================================================

const mocks = vi.hoisted(() => ({
  confirmMock: vi.fn(),
  updatePromptMock: vi.fn(),
  createPromptMock: vi.fn(),
  clearCurrentMock: vi.fn(),
  loadVersionsMock: vi.fn(),
  successMock: vi.fn(),
  handleErrorMock: vi.fn(),
  // plain ref-like 对象 —— PromptEditor setup 中通过 .value 读取即可
  currentPromptRef: { value: null as PromptDetail | null },
  versionsRef: { value: [] as unknown[] },
  savingRef: { value: false },
}))

vi.mock('~/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({ confirm: mocks.confirmMock }),
}))

vi.mock('~/stores/prompts', () => ({
  usePromptsStore: () => ({
    updatePrompt: mocks.updatePromptMock,
    createPrompt: mocks.createPromptMock,
    clearCurrent: mocks.clearCurrentMock,
    loadVersions: mocks.loadVersionsMock,
    currentPrompt: mocks.currentPromptRef,
    versions: mocks.versionsRef,
    saving: mocks.savingRef,
  }),
}))

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({
    success: mocks.successMock,
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  }),
}))

vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: mocks.handleErrorMock }),
}))

// ============================================================================
// Fixture
// ============================================================================

function makePrompt(overrides: Partial<PromptDetail> = {}): PromptDetail {
  return {
    id: 'prompt-abc',
    slug: 'chat.system.developer',
    category: 'chat_agent',
    scope: 'system',
    project: null,
    title: '开发者提示词',
    description: '测试描述',
    is_builtin: false,
    active_version: {
      id: 'ver-1',
      version: 1,
      body: 'Hello {{input_text}}',
      variables_schema: { input_text: { required: true } },
      declared_variables: ['input_text'],
      change_note: '',
      created_by: 1,
      created_at: '2026-04-01T00:00:00Z',
    },
    declared_variables: ['input_text'],
    created_by: 1,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    ...overrides,
  }
}

async function flushAsync(): Promise<void> {
  await new Promise(resolve => setTimeout(resolve, 20))
}

// ============================================================================
// 统一 stub：保留 props/class/子 slot 渲染，抽掉 reka-ui Portal 行为
// ============================================================================

const SheetStub = {
  name: 'Sheet',
  props: ['open'],
  emits: ['update:open'],
  template: '<div data-testid="sheet-root" :data-open="open"><slot /></div>',
}
const SheetContentStub = {
  name: 'SheetContent',
  props: ['class', 'side'],
  template: '<div data-testid="sheet-content" :class="$props.class"><slot /></div>',
}

function PassthroughStub(name: string) {
  return {
    name,
    template: `<div data-stub="${name}"><slot /></div>`,
  }
}

const TabsStub = {
  name: 'Tabs',
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: '<div data-testid="tabs-root"><slot /></div>',
}
const TabsListStub = PassthroughStub('TabsList')
const TabsTriggerStub = {
  name: 'TabsTrigger',
  props: ['value'],
  template: '<button type="button" :data-tab-trigger="value"><slot /></button>',
}
const TabsContentStub = {
  name: 'TabsContent',
  props: ['value', 'forceMount', 'class'],
  template: '<section :data-tab-content="value" :data-force-mount="forceMount !== undefined && forceMount !== false ? \'true\' : \'false\'" :class="$props.class"><slot /></section>',
}

const PromptBodyEditorStub = {
  name: 'PromptBodyEditor',
  props: ['modelValue', 'readonly'],
  emits: ['update:modelValue'],
  template: '<div data-testid="body-editor" :data-model-value="modelValue"></div>',
}
const PromptVariablePanelStub = {
  name: 'PromptVariablePanel',
  props: ['body', 'variablesSchema'],
  template: '<div data-testid="variable-panel"></div>',
}
const PromptMetadataFormStub = {
  name: 'PromptMetadataForm',
  props: ['prompt', 'mode'],
  emits: ['update:values'],
  template: '<div data-testid="metadata-form"></div>',
}
const VariableSchemaEditorStub = {
  name: 'VariableSchemaEditor',
  props: ['modelValue'],
  emits: ['update:modelValue', 'parseError'],
  template: '<div data-testid="schema-editor"></div>',
}
const PromptPreviewPanelStub = {
  name: 'PromptPreviewPanel',
  props: ['prompt', 'body'],
  template: '<div data-testid="preview-panel"></div>',
}
const PromptVersionListStub = {
  name: 'PromptVersionList',
  props: ['prompt', 'versions'],
  template: '<div data-testid="version-list"></div>',
}
const ButtonStub = {
  name: 'Button',
  props: ['disabled', 'variant', 'title'],
  template: '<button type="button" :disabled="disabled" :title="title" :data-variant="variant"><slot /></button>',
}

function mountEditor(props: { open: boolean, mode: 'edit' | 'create', spaceId?: string }) {
  return mount(PromptEditor, {
    props,
    global: {
      stubs: {
        Sheet: SheetStub,
        SheetContent: SheetContentStub,
        SheetHeader: PassthroughStub('SheetHeader'),
        SheetTitle: PassthroughStub('SheetTitle'),
        SheetDescription: PassthroughStub('SheetDescription'),
        SheetFooter: PassthroughStub('SheetFooter'),
        Tabs: TabsStub,
        TabsList: TabsListStub,
        TabsTrigger: TabsTriggerStub,
        TabsContent: TabsContentStub,
        Button: ButtonStub,
        PromptBodyEditor: PromptBodyEditorStub,
        PromptVariablePanel: PromptVariablePanelStub,
        PromptMetadataForm: PromptMetadataFormStub,
        VariableSchemaEditor: VariableSchemaEditorStub,
        PromptPreviewPanel: PromptPreviewPanelStub,
        PromptVersionList: PromptVersionListStub,
      },
    },
  })
}

// ============================================================================
// Tests
// ============================================================================

describe('promptEditor.vue', () => {
  beforeEach(() => {
    mocks.confirmMock.mockReset()
    mocks.updatePromptMock.mockReset()
    mocks.createPromptMock.mockReset()
    mocks.clearCurrentMock.mockReset()
    mocks.loadVersionsMock.mockReset()
    mocks.successMock.mockReset()
    mocks.handleErrorMock.mockReset()
    mocks.currentPromptRef.value = null
    mocks.versionsRef.value = []
    mocks.savingRef.value = false
  })

  it('1. open=false 时 Sheet 不渲染内容（sheet-content stub 不存在）', () => {
    const wrapper = mountEditor({ open: false, mode: 'edit' })
    // open=false 时 Sheet stub 的 data-open 属性 = "false"
    expect(wrapper.find('[data-testid="sheet-root"]').attributes('data-open')).toBe('false')
  })

  it('2. open=true + mode=edit + currentPrompt 已加载 → 渲染 4 个 Tab 触发器', async () => {
    mocks.currentPromptRef.value = makePrompt()
    const wrapper = mountEditor({ open: true, mode: 'edit' })
    await nextTick()
    const triggers = wrapper.findAll('[data-tab-trigger]')
    expect(triggers.length).toBe(4)
    const values = triggers.map(t => t.attributes('data-tab-trigger'))
    expect(values).toEqual(['metadata', 'body', 'preview', 'versions'])
    const texts = triggers.map(t => t.text())
    expect(texts).toContain('基础信息')
    expect(texts).toContain('正文编辑')
    expect(texts).toContain('预览')
    expect(texts).toContain('版本历史')
  })

  it('3. mode=create 隐藏 版本历史 Tab（仅 3 个触发器）', async () => {
    const wrapper = mountEditor({ open: true, mode: 'create' })
    await nextTick()
    const triggers = wrapper.findAll('[data-tab-trigger]')
    expect(triggers.length).toBe(3)
    const values = triggers.map(t => t.attributes('data-tab-trigger'))
    expect(values).toEqual(['metadata', 'body', 'preview'])
    expect(values).not.toContain('versions')
  })

  it('4. SheetContent 包含 sm:!max-w-3xl 和 w-full flex flex-col class', async () => {
    mocks.currentPromptRef.value = makePrompt()
    const wrapper = mountEditor({ open: true, mode: 'edit' })
    await nextTick()
    const sheetContent = wrapper.find('[data-testid="sheet-content"]')
    const cls = sheetContent.attributes('class') ?? ''
    expect(cls).toContain('sm:max-w-3xl!')
    expect(cls).toContain('w-full')
    expect(cls).toContain('flex')
    expect(cls).toContain('flex-col')
  })

  it('5. 所有 TabsContent 都传递 force-mount=true 给 reka-ui', async () => {
    mocks.currentPromptRef.value = makePrompt()
    const wrapper = mountEditor({ open: true, mode: 'edit' })
    await nextTick()
    const contents = wrapper.findAll('[data-tab-content]')
    // edit 模式 4 个 Tab 都应 force-mount
    expect(contents.length).toBe(4)
    contents.forEach((c) => {
      expect(c.attributes('data-force-mount')).toBe('true')
    })
  })

  it('6. body 初始与 currentPrompt.active_version.body 相同 → isDirty=false 保存按钮 disabled', async () => {
    mocks.currentPromptRef.value = makePrompt()
    const wrapper = mountEditor({ open: true, mode: 'edit' })
    await nextTick()
    const buttons = wrapper.findAll('button')
    const saveBtn = buttons.find(b => b.text() === '保存')
    expect(saveBtn).toBeTruthy()
    expect(saveBtn!.attributes('disabled')).toBeDefined()
  })

  it('7. body 修改后 isDirty=true，保存按钮 enabled', async () => {
    mocks.currentPromptRef.value = makePrompt()
    const wrapper = mountEditor({ open: true, mode: 'edit' })
    await nextTick()
    const bodyEditor = wrapper.findComponent(PromptBodyEditorStub)
    await bodyEditor.vm.$emit('update:modelValue', 'Hello {{input_text}} CHANGED')
    await nextTick()
    const buttons = wrapper.findAll('button')
    const saveBtn = buttons.find(b => b.text() === '保存')
    expect(saveBtn).toBeTruthy()
    expect(saveBtn!.attributes('disabled')).toBeUndefined()
  })

  it('8. 点击保存 → confirm 被调用 → store.updatePrompt 被调用 → emit update:open=false', async () => {
    mocks.currentPromptRef.value = makePrompt()
    mocks.confirmMock.mockResolvedValueOnce(true)
    mocks.updatePromptMock.mockResolvedValueOnce(makePrompt())
    const wrapper = mountEditor({ open: true, mode: 'edit' })
    await nextTick()

    // 触发 body 变更让 isDirty=true
    const bodyEditor = wrapper.findComponent(PromptBodyEditorStub)
    await bodyEditor.vm.$emit('update:modelValue', 'Hello {{input_text}} NEW')
    await nextTick()

    const saveBtn = wrapper.findAll('button').find(b => b.text() === '保存')
    expect(saveBtn).toBeTruthy()
    await saveBtn!.trigger('click')
    await flushAsync()

    expect(mocks.confirmMock).toHaveBeenCalledTimes(1)
    expect(mocks.updatePromptMock).toHaveBeenCalledTimes(1)
    expect(mocks.updatePromptMock).toHaveBeenCalledWith(
      'prompt-abc',
      expect.objectContaining({
        title: '开发者提示词',
        description: '测试描述',
        body: 'Hello {{input_text}} NEW',
      }),
    )
    const emitted = wrapper.emitted('update:open')
    expect(emitted).toBeTruthy()
    expect(emitted![emitted!.length - 1]).toEqual([false])
    expect(mocks.successMock).toHaveBeenCalledWith('保存成功')
  })

  it('9. dirty=true 时关闭 Sheet 走 confirm 拦截；返回 false 重置 open=true', async () => {
    mocks.currentPromptRef.value = makePrompt()
    mocks.confirmMock.mockResolvedValueOnce(false)
    const wrapper = mountEditor({ open: true, mode: 'edit' })
    await nextTick()
    const bodyEditor = wrapper.findComponent(PromptBodyEditorStub)
    await bodyEditor.vm.$emit('update:modelValue', 'DIRTY')
    await nextTick()
    const sheetStub = wrapper.findComponent(SheetStub)
    await sheetStub.vm.$emit('update:open', false)
    await flushAsync()

    expect(mocks.confirmMock).toHaveBeenCalledTimes(1)
    const emitted = wrapper.emitted('update:open') ?? []
    expect(emitted.length).toBeGreaterThan(0)
    expect(emitted[emitted.length - 1]).toEqual([true])
    expect(mocks.clearCurrentMock).not.toHaveBeenCalled()
  })

  it('10. PromptBodyEditor 通过 v-model 绑定 editedBody（状态提升到 PromptEditor 外层）', async () => {
    mocks.currentPromptRef.value = makePrompt()
    const wrapper = mountEditor({ open: true, mode: 'edit' })
    await nextTick()
    const bodyEditor = wrapper.findComponent(PromptBodyEditorStub)
    // 初始值 = currentPrompt.active_version.body
    expect(bodyEditor.props('modelValue')).toBe('Hello {{input_text}}')
    await bodyEditor.vm.$emit('update:modelValue', 'NEW BODY')
    await nextTick()
    // PromptVariablePanel 接收的 body prop 应当也同步到 NEW BODY
    const variablePanel = wrapper.findComponent(PromptVariablePanelStub)
    expect(variablePanel.props('body')).toBe('NEW BODY')
  })
})
