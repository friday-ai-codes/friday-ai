import type { NodeExecution } from '~/stores/useExecutionsStore'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import NodeDataTab from '../execution/NodeDataTab.vue'

// Mock JsonEditor 组件（happy-dom 下无法运行 CodeMirror）
// vi.hoisted 在 vi.mock 之前执行，可以安全引用
const { MockJsonEditor } = vi.hoisted(() => {
  // eslint-disable-next-line ts/no-require-imports
  const vue = require('vue')
  return {
    MockJsonEditor: vue.defineComponent({
      name: 'JsonEditor',
      props: {
        modelValue: { type: String, default: '' },
        readonly: { type: Boolean, default: false },
        height: { type: String, default: '300px' },
      },
      emits: ['update:modelValue'],
      setup(props: any, { emit }: any) {
        return () => vue.h('div', { class: 'mock-json-editor' }, [
          vue.h('textarea', {
            'value': props.modelValue,
            'disabled': props.readonly,
            'data-testid': 'json-editor',
            'onInput': (e: Event) => {
              emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
            },
          }),
        ])
      },
    }),
  }
})

vi.mock('../execution/JsonEditor.vue', () => ({
  default: MockJsonEditor,
}))

// 深链走 RouterLink（与三处触点同一约定）。
vi.mock('vue-router', () => ({
  RouterLink: { name: 'RouterLink', props: ['to'], template: '<a :href="to"><slot /></a>' },
}))

// Mock useExecutionsStore 的 sendDebugAction
const mockSendDebugAction = vi.fn()
vi.mock('~/stores/useExecutionsStore', async (importOriginal) => {
  const original = await importOriginal<typeof import('~/stores/useExecutionsStore')>()
  return {
    ...original,
    useExecutionsStore: () => ({
      sendDebugAction: mockSendDebugAction,
    }),
  }
})

// Mock MarkdownRenderer（简单 stub）
vi.mock('../execution/MarkdownRenderer.vue', () => ({
  default: {
    name: 'MarkdownRenderer',
    props: ['content'],
    template: '<div class="mock-markdown">{{ content }}</div>',
  },
}))

function createNodeExecution(overrides: Partial<NodeExecution> = {}): NodeExecution {
  return {
    id: 'ne-1',
    node: 'node-1',
    node_name: '测试节点',
    node_type: 'http_request',
    status: 'completed',
    input_data: { url: 'https://example.com' },
    output_data: { result: 'ok', status_code: 200 },
    error_message: '',
    error_traceback: '',
    attempt: 1,
    approval_data: {},
    container_id: '',
    container_logs: '',
    duration: 1.5,
    created_at: '2026-01-01T00:00:00Z',
    started_at: '2026-01-01T00:00:00Z',
    completed_at: '2026-01-01T00:00:01Z',
    sub_step_progress: null,
    logs: null,
    error_code: null,
    ...overrides,
  }
}

function createAINodeExecution(overrides: Partial<NodeExecution> = {}): NodeExecution {
  return createNodeExecution({
    node_type: 'ai_prompt',
    node_name: 'AI 提示节点',
    output_data: { text: 'AI generated response' },
    ...overrides,
  })
}

describe('nodeDataTab', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockSendDebugAction.mockClear()
  })

  it('非调试暂停时，不显示编辑输出和 Mock 输出按钮', () => {
    const wrapper = mount(NodeDataTab, {
      props: {
        nodeExecution: createNodeExecution(),
        isDebugPaused: false,
      },
    })
    expect(wrapper.text()).not.toContain('编辑输出')
    expect(wrapper.text()).not.toContain('Mock 输出')
  })

  it('调试暂停时，显示编辑输出和 Mock 输出按钮', () => {
    const wrapper = mount(NodeDataTab, {
      props: {
        nodeExecution: createNodeExecution({ status: 'debug_paused' }),
        isDebugPaused: true,
      },
    })
    expect(wrapper.text()).toContain('编辑输出')
    expect(wrapper.text()).toContain('Mock 输出')
  })

  it('编辑模式下保存修改仅更新本地数据，不调用 sendDebugAction', async () => {
    const wrapper = mount(NodeDataTab, {
      props: {
        nodeExecution: createNodeExecution({ status: 'debug_paused' }),
        isDebugPaused: true,
      },
    })

    // 点击编辑输出进入编辑模式
    const editBtn = wrapper.findAll('button').find(b => b.text().includes('编辑输出'))
    expect(editBtn).toBeTruthy()
    await editBtn!.trigger('click')
    await nextTick()

    // 应该进入编辑模式
    expect(wrapper.text()).toContain('编辑模式')

    // 找到可编辑的 JsonEditor 并修改数据使 isDirty 为 true
    const editors = wrapper.findAllComponents({ name: 'JsonEditor' })
    const editableEditor = editors.find(e => !e.props('readonly'))
    expect(editableEditor).toBeTruthy()
    const textarea = editableEditor!.find('textarea')
    const el = textarea.element as HTMLTextAreaElement
    el.value = '{"result": "modified", "status_code": 200}'
    await textarea.trigger('input')
    await nextTick()

    // 点击保存修改
    const saveBtn = wrapper.findAll('button').find(b => b.text().includes('保存修改'))
    expect(saveBtn).toBeTruthy()
    await saveBtn!.trigger('click')
    await nextTick()

    // sendDebugAction 不应被调用
    expect(mockSendDebugAction).not.toHaveBeenCalled()
  })

  it('编辑模式下放行按钮调用 sendDebugAction(release, { edited_output })', async () => {
    const wrapper = mount(NodeDataTab, {
      props: {
        nodeExecution: createNodeExecution({ status: 'debug_paused' }),
        isDebugPaused: true,
      },
    })

    // 进入编辑模式
    const editBtn = wrapper.findAll('button').find(b => b.text().includes('编辑输出'))
    await editBtn!.trigger('click')
    await nextTick()

    // 找到非 readonly 的 JsonEditor（可编辑的那个）
    const editors = wrapper.findAllComponents({ name: 'JsonEditor' })
    const editableEditor = editors.find(e => !e.props('readonly'))
    expect(editableEditor).toBeTruthy()

    // 模拟编辑器内容变更：通过 textarea input 事件
    const textarea = editableEditor!.find('textarea')
    // 直接设置 DOM value 并触发 input 事件
    const el = textarea.element as HTMLTextAreaElement
    el.value = '{"result": "edited_value"}'
    await textarea.trigger('input')
    await nextTick()

    // 点击放行
    const releaseBtn = wrapper.findAll('button').find(b => b.text().includes('放行'))
    expect(releaseBtn).toBeTruthy()
    await releaseBtn!.trigger('click')

    expect(mockSendDebugAction).toHaveBeenCalledWith('release', {
      edited_output: { result: 'edited_value' },
    })
  })

  it('mock 模式下提交 Mock 调用 sendDebugAction(mock, { mock_output })', async () => {
    const wrapper = mount(NodeDataTab, {
      props: {
        nodeExecution: createNodeExecution({ status: 'debug_paused' }),
        isDebugPaused: true,
      },
    })

    // 点击 Mock 输出
    const mockBtn = wrapper.findAll('button').find(b => b.text().includes('Mock 输出'))
    expect(mockBtn).toBeTruthy()
    await mockBtn!.trigger('click')
    await nextTick()

    // 应该进入 Mock 模式
    expect(wrapper.text()).toContain('Mock 模式')

    // 找到可编辑的 JsonEditor 并修改数据
    const editors = wrapper.findAllComponents({ name: 'JsonEditor' })
    const editableEditor = editors.find(e => !e.props('readonly'))
    expect(editableEditor).toBeTruthy()
    const textarea = editableEditor!.find('textarea')
    const el = textarea.element as HTMLTextAreaElement
    el.value = '{"mock_key": "mock_value"}'
    await textarea.trigger('input')
    await nextTick()

    // 点击提交 Mock
    const submitBtn = wrapper.findAll('button').find(b => b.text().includes('提交 Mock'))
    expect(submitBtn).toBeTruthy()
    await submitBtn!.trigger('click')

    expect(mockSendDebugAction).toHaveBeenCalledWith('mock', {
      mock_output: { mock_key: 'mock_value' },
    })
  })

  it('aI 节点调试暂停时默认进入 Mock 模式', () => {
    const wrapper = mount(NodeDataTab, {
      props: {
        nodeExecution: createAINodeExecution({ status: 'debug_paused' }),
        isDebugPaused: true,
      },
    })

    // AI 节点应自动进入 Mock 模式
    expect(wrapper.text()).toContain('Mock 模式')
  })

  it('aI 节点真实执行按钮触发 AISafetyConfirm 对话框', async () => {
    const wrapper = mount(NodeDataTab, {
      props: {
        nodeExecution: createAINodeExecution({ status: 'debug_paused' }),
        isDebugPaused: true,
      },
      global: {
        stubs: {
          // AISafetyConfirm 需要 Teleport，stub 处理
          teleport: true,
        },
      },
    })

    // 找到真实执行按钮
    const realExecBtn = wrapper.findAll('button').find(b => b.text().includes('真实执行'))
    expect(realExecBtn).toBeTruthy()
    await realExecBtn!.trigger('click')
    await nextTick()

    // AISafetyConfirm 组件的 open prop 应为 true
    const dialog = wrapper.findComponent({ name: 'AISafetyConfirm' })
    expect(dialog.exists()).toBe(true)
    expect(dialog.props('open')).toBe(true)
  })
})

// ═════════════════════════════════════════════════════════════════════════════
// 同步点 2 收尾：blueprint/v1 识别（两条链共用 node_type，两档必须正反并列）
// ═════════════════════════════════════════════════════════════════════════════

/** v0 旧链 `ai_plan_research` 的 done 输出（⛔ 无 `schema_version`）。 */
function createLegacyPlanExecution(): NodeExecution {
  return createNodeExecution({
    node_type: 'ai_plan_research',
    node_name: '方案编排',
    output_data: {
      session_id: 's-1',
      artifact_version_id: 'av-1',
      status: 'done',
      plan: { title: '登录改造', execution_plan: [] },
      plan_markdown: '# 登录改造',
    },
  })
}

/** 蓝图链输出（与 v0 同 node_type、同 `session_id`/`plan`/`plan_markdown` 键）。 */
function createBlueprintExecution(output: Record<string, any>): NodeExecution {
  return createNodeExecution({
    node_type: 'ai_plan_research',
    node_name: '方案编排',
    output_data: output,
  })
}

describe('nodeDataTab —— blueprint/v1 识别', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockSendDebugAction.mockClear()
  })

  it('⭐ v0 旧链输出：不出蓝图告示条（逐像素不变）', () => {
    const wrapper = mount(NodeDataTab, {
      props: { nodeExecution: createLegacyPlanExecution() },
    })
    expect(wrapper.find('[data-testid="node-blueprint-notice"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="node-blueprint-link"]').exists()).toBe(false)
  })

  it('⭐ pending_review 挂起：如实讲「等人工终审」而不是「卡住了」', () => {
    const wrapper = mount(NodeDataTab, {
      props: {
        nodeExecution: createBlueprintExecution({
          session_id: 's-1',
          kind: 'human_review',
          schema_version: 'blueprint/v1',
          artifact_id: 'art-9',
          current_status: 'pending_review',
          suspension: { type: 'await_human_review', artifact_id: 'art-9' },
        }),
      },
    })
    const notice = wrapper.find('[data-testid="node-blueprint-notice"]')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain('结构化技术蓝图')
    expect(wrapper.find('[data-testid="node-blueprint-status"]').text()).toBe('待人类审查')
    expect(wrapper.find('[data-testid="node-blueprint-kind"]').text()).toContain('人工终审')
    expect(wrapper.find('[data-testid="node-blueprint-link"]').attributes('href')).toBe(
      '/knowledge/blueprints/art-9',
    )
  })

  it('needs_clarification 挂起：状态与挂起语义各自如实', () => {
    const wrapper = mount(NodeDataTab, {
      props: {
        nodeExecution: createBlueprintExecution({
          session_id: 's-1',
          kind: 'clarification',
          schema_version: 'blueprint/v1',
          artifact_id: 'art-9',
          current_status: 'needs_clarification',
          pending_clarifications: [{ thread_id: 't-1', question: '要不要兼容旧端？' }],
        }),
      },
    })
    expect(wrapper.find('[data-testid="node-blueprint-status"]').text()).toBe('需要澄清')
    expect(wrapper.find('[data-testid="node-blueprint-kind"]').text()).toContain('澄清')
  })

  it('⭐ 历史执行记录兜底：只有 blueprint_content.schema_version 也能识别', () => {
    const wrapper = mount(NodeDataTab, {
      props: {
        nodeExecution: createBlueprintExecution({
          session_id: 's-1',
          artifact_id: 'art-9',
          status: 'done',
          current_status: 'confirmed',
          plan: { title: 'x', execution_plan: [] },
          blueprint_content: { schema_version: 'blueprint/v1', meta: { title: 'x' } },
        }),
      },
    })
    expect(wrapper.find('[data-testid="node-blueprint-notice"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="node-blueprint-status"]').text()).toBe('已确认')
  })

  it('未知 schema_version 一律按 v0 处理（允许清单）', () => {
    const wrapper = mount(NodeDataTab, {
      props: {
        nodeExecution: createBlueprintExecution({
          session_id: 's-1',
          schema_version: 'blueprint/v2',
          artifact_id: 'art-9',
          current_status: 'pending_review',
        }),
      },
    })
    expect(wrapper.find('[data-testid="node-blueprint-notice"]').exists()).toBe(false)
  })

  it('缺 artifact_id 时不渲染深链（⛔ 不给一个点不开的链接）', () => {
    const wrapper = mount(NodeDataTab, {
      props: {
        nodeExecution: createBlueprintExecution({
          session_id: 's-1',
          kind: 'research',
          schema_version: 'blueprint/v1',
          _resume_from_callback: true,
        }),
      },
    })
    expect(wrapper.find('[data-testid="node-blueprint-notice"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="node-blueprint-link"]').exists()).toBe(false)
    // 没进状态机 ⇒ `''` 命中「旧版方案」档而不是未知档。
    expect(wrapper.find('[data-testid="node-blueprint-status"]').text()).toBe('旧版方案')
  })
})
