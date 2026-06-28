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
import { usePaletteDragState } from '../../composables/usePaletteDragState'
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

function pushHost(wf: ReturnType<typeof useWorkflowsStore>, id = 'node-1', nodeType = 'ai_plan_research') {
  wf.nodes.push({
    id,
    shortId: id.slice(0, 3),
    nodeType,
    name: '宿主',
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
}

describe('baseWorkflowNode 能力槽渲染 + 拖拽落入（SLOT-04）', () => {
  beforeEach(() => {
    const store = useNodeTypesStore()
    store.nodeTypes = [
      makeNodeType({
        node_type: 'ai_plan_research',
        category: 'ai',
        inputs: [makePort('default'), makePort('resume', 'clarification_answer')],
        outputs: [makePort('default'), makePort('clarify', 'clarification_request'), makePort('error')],
      }),
      makeNodeType({
        node_type: 'clarification_card',
        category: 'ai',
        inputs: [makePort('clarification_request')],
        outputs: [makePort('clarification_answer'), makePort('feishu_message'), makePort('error')],
      }),
    ]
  })

  it('宿主按 taxonomy 渲染能力槽（澄清/文档/通知）；typed 端口不渲染为 handle，plain 端口仍渲染', async () => {
    const wrapper = mountNode('ai_plan_research')
    await nextTick()

    // ai_plan_research → hostSlots = [clarification, document, notification] → 3 个 dropzone
    expect(wrapper.findAll('.slot-dropzone').length).toBe(3)
    // typed 端口（clarify/resume）是内部接线端点，不渲染为可见 handle
    expect(findHandle(wrapper, 'clarify', 'source')).toBeUndefined()
    expect(findHandle(wrapper, 'resume', 'target')).toBeUndefined()
    // plain 端口（default 出口）仍渲染（零回归）
    expect(findHandle(wrapper, 'default', 'source')).toBeDefined()
  })

  it('拖入兼容插件落槽 → 建插件子节点(parentNodeId) + 按能力自动接线', async () => {
    const wf = useWorkflowsStore()
    pushHost(wf)
    const wrapper = mountNode('ai_plan_research')
    await nextTick()

    // 第 1 个 dropzone = 澄清槽；拖入澄清卡（提供 clarification）
    await wrapper.findAll('.slot-dropzone')[0].trigger('drop', {
      dataTransfer: { getData: () => 'clarification_card' },
    })

    const child = wf.nodes.find(n => (n.metadata as any)?.parentNodeId === 'node-1')
    expect(child).toBeDefined()
    expect(child!.nodeType).toBe('clarification_card')
    // 双向澄清接线：host.clarify→plugin.clarification_request + plugin.clarification_answer→host.resume
    expect(wf.edges.some(e => e.source === 'node-1' && e.sourcePort === 'clarify')).toBe(true)
    expect(wf.edges.some(e => e.target === 'node-1' && e.targetPort === 'resume')).toBe(true)
  })

  it('拖入不兼容插件 → 不落槽（类型不匹配，无附着）', async () => {
    const wf = useWorkflowsStore()
    pushHost(wf)
    const wrapper = mountNode('ai_plan_research')
    await nextTick()

    // 第 2 个 dropzone = 文档槽；拖入澄清卡（提供 clarification ≠ document）
    await wrapper.findAll('.slot-dropzone')[1].trigger('drop', {
      dataTransfer: { getData: () => 'clarification_card' },
    })

    expect(wf.nodes.find(n => (n.metadata as any)?.parentNodeId === 'node-1')).toBeUndefined()
  })
})

describe('baseWorkflowNode 能力槽类型匹配高亮（SLOT-04 palette 拖拽）', () => {
  beforeEach(() => {
    const store = useNodeTypesStore()
    store.nodeTypes = [
      makeNodeType({
        node_type: 'ai_plan_research',
        category: 'ai',
        inputs: [makePort('default'), makePort('resume', 'clarification_answer')],
        outputs: [makePort('default'), makePort('clarify', 'clarification_request'), makePort('error')],
      }),
    ]
  })

  afterEach(() => {
    usePaletteDragState().endPaletteDrag()
  })

  it('拖起兼容插件(澄清卡) → 澄清槽高亮(active)，其余能力槽降亮(opacity-40)', async () => {
    usePaletteDragState().startPaletteDrag('clarification_card')
    const wrapper = mountNode('ai_plan_research')
    await nextTick()

    const zones = wrapper.findAll('.slot-dropzone')
    expect(zones[0].classes()).toContain('slot-dropzone-active') // clarification 兼容
    expect(zones[1].classes()).toContain('opacity-40') // document 不兼容
    expect(zones[2].classes()).toContain('opacity-40') // notification 不兼容
  })

  it('非拖拽态：能力槽无高亮/降亮（idle 零回归）', async () => {
    const wrapper = mountNode('ai_plan_research')
    await nextTick()

    const zone = wrapper.findAll('.slot-dropzone')[0]
    expect(zone.classes()).not.toContain('slot-dropzone-active')
    expect(zone.classes()).not.toContain('opacity-40')
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
