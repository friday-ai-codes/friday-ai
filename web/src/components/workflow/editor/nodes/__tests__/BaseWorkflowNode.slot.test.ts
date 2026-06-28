import type { NodeType } from '~/stores/useNodeTypesStore'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { useConnectionDragState } from '../../composables/useConnectionDragState'
import BaseWorkflowNode from '../BaseWorkflowNode.vue'

/**
 * SLOT-03 / SLOT-04：BaseWorkflowNode 端口视觉（shape 方形/圆形 + 着色）、拖拽态机
 * （compatible-highlight / forbidden）、IM 门控锁徽标、附着子节点徽标单测。
 *
 * - Handle stub 透传 class/style（fallthrough），供形状/着色/拖拽态断言。
 * - 真实 zh-CN.json 作 i18n messages，锁关键文案（附着 / 需先添加「创建群聊」节点）。
 */

vi.mock('@vue-flow/core', () => ({
  Handle: defineComponent({
    name: 'Handle',
    props: {
      id: { type: String, default: '' },
      type: { type: String, default: '' },
      position: { type: String, default: '' },
    },
    setup(props) {
      return () => h('div', {
        'data-testid': 'handle',
        'data-handle-id': props.id,
        'data-handle-type': props.type,
      })
    },
  }),
  Position: { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' },
  useVueFlow: () => ({ getSelectedNodes: ref([]) }),
}))

vi.mock('@vue-flow/node-toolbar', () => ({
  NodeToolbar: defineComponent({
    name: 'NodeToolbar',
    setup(_, { slots }) {
      return () => h('div', slots.default?.())
    },
  }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

function makeNodeType(overrides: Partial<NodeType>): NodeType {
  return {
    node_type: overrides.node_type ?? 'x',
    display_name: overrides.display_name ?? 'X',
    description: overrides.description ?? '',
    icon: overrides.icon ?? 'box',
    category: overrides.category ?? 'action',
    config_schema: overrides.config_schema ?? {},
    inputs: overrides.inputs ?? [],
    outputs: overrides.outputs ?? [],
    requires_container: overrides.requires_container ?? false,
    is_blocking: overrides.is_blocking ?? false,
  }
}

function makePort(name: string, shape?: string) {
  return { name, label: name, type: 'any', required: false, description: '', shape }
}

function mountNode(nodeType: string, dataOverrides: Record<string, unknown> = {}) {
  return mount(BaseWorkflowNode, {
    props: {
      id: 'node-1',
      data: { name: 'Test Node', nodeType, ...dataOverrides },
    },
    global: { plugins: [i18n] },
  })
}

function findHandle(wrapper: ReturnType<typeof mountNode>, id: string, type: 'target' | 'source') {
  return wrapper
    .findAll('[data-testid="handle"]')
    .find(h => h.attributes('data-handle-id') === id && h.attributes('data-handle-type') === type)
}

beforeEach(() => {
  setActivePinia(createPinia())
})

afterEach(() => {
  // 重置模块级拖拽态单例，避免用例间串味
  useConnectionDragState().endConnect()
})

describe('baseWorkflowNode 端口形状/着色（SLOT-03）', () => {
  it('typed shape input → 卡内嵌虚线插槽位（缺口 + 拖入提示 + 拼图凸榫连接点）；typed output → 圆角方形实心', async () => {
    const store = useNodeTypesStore()
    store.nodeTypes = [
      makeNodeType({
        node_type: 'ai_plan_research',
        category: 'ai',
        inputs: [makePort('clarify', 'clarification_request')],
        outputs: [makePort('resume', 'clarification_answer')],
      }),
    ]
    const wrapper = mountNode('ai_plan_research')
    await nextTick()

    // typed input 不再是边缘漂浮方块，而是卡内嵌「拼积木」插槽位：
    // 连接点为左缘拼图凸榫（slot-tab-handle），卡内渲染虚线缺口 + 拖入提示文案。
    const input = findHandle(wrapper, 'clarify', 'target')!
    expect(input.classes()).toContain('slot-tab-handle')
    const dropzone = wrapper.find('.slot-dropzone')
    expect(dropzone.exists()).toBe(true)
    expect(dropzone.text()).toContain('clarify') // 插槽标题=端口 label
    expect(dropzone.text()).toContain('拖入兼容卡片') // dropHint 文案（真实 zh-CN）

    // typed output 仍为圆角方形实心凸点（右侧出口，未改）
    const output = findHandle(wrapper, 'resume', 'source')!
    expect(output.classes()).toContain('slot-handle-typed')
    expect(output.classes()).toContain('slot-handle-output')
    const outputStyle = output.attributes('style') ?? ''
    expect(outputStyle).toContain('border-radius: 4px')
    expect(outputStyle).toContain('#f59e0b') // clarification_answer shape 实心色
  })

  it('default/error 通用端口 → 圆形（无 typed 类）+ 既有语义色（零回归）', async () => {
    const store = useNodeTypesStore()
    store.nodeTypes = [
      makeNodeType({
        node_type: 'http_request',
        category: 'action',
        inputs: [makePort('default')],
        outputs: [makePort('default'), makePort('error')],
      }),
    ]
    const wrapper = mountNode('http_request')
    await nextTick()

    const defaultOut = findHandle(wrapper, 'default', 'source')!
    expect(defaultOut.classes()).not.toContain('slot-handle-typed')
    expect(defaultOut.attributes('style') ?? '').toContain('#10b981') // emerald 成功
    expect(defaultOut.attributes('style') ?? '').not.toContain('border-radius: 4px')

    const errorOut = findHandle(wrapper, 'error', 'source')!
    expect(errorOut.classes()).not.toContain('slot-handle-typed')
    expect(errorOut.attributes('style') ?? '').toContain('#ef4444') // red 失败
  })
})

describe('baseWorkflowNode 拖拽态机（SLOT-03）', () => {
  beforeEach(() => {
    const store = useNodeTypesStore()
    store.nodeTypes = [
      makeNodeType({
        node_type: 'tgt',
        category: 'integration',
        inputs: [makePort('msg', 'feishu_message'), makePort('doc', 'feishu_document')],
        outputs: [makePort('default')],
      }),
    ]
  })

  it('拖拽中：兼容 input handle 带 compatible-highlight，不兼容带 forbidden', async () => {
    // 源 output shape=feishu_message → 'msg'(feishu_message) 兼容、'doc'(feishu_document) 不兼容
    useConnectionDragState().startConnect('src', 'out', 'feishu_message')
    const wrapper = mountNode('tgt')
    await nextTick()

    const msg = findHandle(wrapper, 'msg', 'target')!
    const doc = findHandle(wrapper, 'doc', 'target')!
    expect(msg.classes()).toContain('compatible-highlight')
    expect(doc.classes()).toContain('forbidden')
  })

  it('非拖拽态：input handle 无 compatible/forbidden 类（idle 零回归）', async () => {
    const wrapper = mountNode('tgt')
    await nextTick()

    const msg = findHandle(wrapper, 'msg', 'target')!
    expect(msg.classes()).not.toContain('compatible-highlight')
    expect(msg.classes()).not.toContain('forbidden')
  })
})

describe('baseWorkflowNode IM 门控（SLOT-04 / CONTEXT D）', () => {
  beforeEach(() => {
    const ntStore = useNodeTypesStore()
    ntStore.nodeTypes = [
      makeNodeType({ node_type: 'notify_feishu_im', category: 'integration', inputs: [makePort('default')], outputs: [makePort('default')] }),
      makeNodeType({ node_type: 'create_group_chat', category: 'integration', inputs: [makePort('default')], outputs: [makePort('default')] }),
    ]
  })

  it('图无 IM 源 → notify_feishu_im 渲染锁徽标 + imGatedHint 文案', async () => {
    const store = useWorkflowsStore()
    store.nodes.push({
      id: 'n1',
      shortId: 'n1',
      nodeType: 'notify_feishu_im',
      name: 'IM 通知',
      description: '',
      position: { x: 0, y: 0 },
      config: {},
      onError: 'abort',
      retryTimes: 0,
      retryDelay: 5,
      nodeTimeoutSeconds: null,
      fallbackValues: null,
      runCondition: null,
      metadata: {},
    } as any)

    const wrapper = mountNode('notify_feishu_im')
    await nextTick()

    const gate = wrapper.find('[title="需先添加「创建群聊」节点以提供 chat_id"]')
    expect(gate.exists()).toBe(true)
    expect(wrapper.find('[title="需先添加「创建群聊」节点以提供 chat_id"]').html()).toContain('lucide--lock')
  })

  it('图含 create_group_chat → 不门控（无锁徽标）', async () => {
    const store = useWorkflowsStore()
    store.nodes.push(
      { id: 'src', shortId: 'src', nodeType: 'create_group_chat', name: '建群', description: '', position: { x: 0, y: 0 }, config: {}, onError: 'abort', retryTimes: 0, retryDelay: 5, nodeTimeoutSeconds: null, fallbackValues: null, runCondition: null, metadata: {} } as any,
    )

    const wrapper = mountNode('notify_feishu_im')
    await nextTick()

    expect(wrapper.find('[title="需先添加「创建群聊」节点以提供 chat_id"]').exists()).toBe(false)
  })
})

describe('baseWorkflowNode 附着徽标（SLOT-04，读 data.metadata.parentNodeId）', () => {
  it('data.metadata.parentNodeId 非空 → 渲染『附着』徽标 + attachedHint', async () => {
    const wrapper = mountNode('clarification_card', { metadata: { parentNodeId: 'parent-1' } })
    await nextTick()

    const badge = wrapper.find('[title="澄清随方案节点存在，删除方案节点将一并移除"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('附着')
  })

  it('无 parentNodeId → 不渲染附着徽标', async () => {
    const wrapper = mountNode('clarification_card', { metadata: {} })
    await nextTick()

    expect(wrapper.find('[title="澄清随方案节点存在，删除方案节点将一并移除"]').exists()).toBe(false)
  })
})
