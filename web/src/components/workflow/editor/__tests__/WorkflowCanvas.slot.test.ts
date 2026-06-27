import type { NodeType } from '~/stores/useNodeTypesStore'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { useConnectionDragState } from '../composables/useConnectionDragState'
import WorkflowCanvas from '../WorkflowCanvas.vue'

/**
 * SLOT-03 磁吸交互 + SLOT-04 附着编组（WorkflowCanvas 画布层集成）单测。
 *
 * 策略：@vue-flow 系包与重组件 stub，`useVueFlow` 用可配置 mock 提供
 * viewport/getNodes/findNode/getEdges/screenToFlowCoordinate；`useConnectionDragState`
 * 等纯逻辑 composable 与 `getValidationError` 保持真实，经 defineExpose 直驱处理器断言。
 */

const mockViewport = ref({ x: 0, y: 0, zoom: 1 })
const mockVfNodes = ref<any[]>([])
const mockVfEdges = ref<any[]>([])
const mockFindNode = vi.fn((id: string) => mockVfNodes.value.find(n => n.id === id))
const mockScreenToFlow = vi.fn((p: { x: number, y: number }) => ({ ...p }))
const mockError = vi.fn()

vi.mock('@vue-flow/core', () => {
  const stub = (name: string) => defineComponent({
    name,
    setup(_, { slots }) {
      return () => h('div', { class: name.toLowerCase() }, slots.default?.())
    },
  })
  return {
    VueFlow: stub('VueFlow'),
    Panel: stub('Panel'),
    ConnectionMode: { Strict: 'strict' },
    SelectionMode: { Partial: 'partial' },
    MarkerType: { ArrowClosed: 'arrowclosed' },
    Position: { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' },
    getBezierPath: () => ['M0,0'],
    useVueFlow: () => ({
      getSelectedNodes: ref([]),
      fitView: vi.fn(),
      viewport: mockViewport,
      getNodes: mockVfNodes,
      getEdges: mockVfEdges,
      findNode: mockFindNode,
      screenToFlowCoordinate: mockScreenToFlow,
    }),
  }
})

vi.mock('@vue-flow/background', () => ({ Background: { name: 'Background', render: () => null } }))
vi.mock('@vue-flow/controls', () => ({ Controls: { name: 'Controls', render: () => null } }))
vi.mock('@vue-flow/minimap', () => ({ MiniMap: { name: 'MiniMap', render: () => null } }))
vi.mock('../nodes', () => ({ nodeTypes: {} }))
vi.mock('../edges/GradientEdge.vue', () => ({ default: { name: 'GradientEdge', render: () => null } }))

vi.mock('../composables/useAlignmentGuides', () => ({
  useAlignmentGuides: () => ({
    alignmentGuides: ref([]),
    checkAlignment: (_id: string, p: { x: number, y: number }) => p,
    clearGuides: vi.fn(),
  }),
}))
vi.mock('../composables/useAutoLayout', () => ({
  useAutoLayout: () => ({ applyAutoLayout: vi.fn(() => false) }),
}))
vi.mock('../composables/useDragAndDrop', () => ({
  useDragAndDrop: () => ({ onDragOver: vi.fn(), onDrop: vi.fn() }),
}))
vi.mock('../composables/useKeyboardShortcuts', () => ({
  useKeyboardShortcuts: vi.fn(),
}))
vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: mockError }),
}))

// AlertDialog（reka-ui）stub 为透传容器：避免 teleport/上下文复杂度，断言走 exposed 状态 + store。
vi.mock('~/components/ui/alert-dialog', () => {
  const passthrough = (name: string) => defineComponent({
    name,
    setup(_, { slots }) {
      return () => h('div', slots.default?.())
    },
  })
  return {
    AlertDialog: passthrough('AlertDialog'),
    AlertDialogAction: passthrough('AlertDialogAction'),
    AlertDialogCancel: passthrough('AlertDialogCancel'),
    AlertDialogContent: passthrough('AlertDialogContent'),
    AlertDialogDescription: passthrough('AlertDialogDescription'),
    AlertDialogFooter: passthrough('AlertDialogFooter'),
    AlertDialogHeader: passthrough('AlertDialogHeader'),
    AlertDialogTitle: passthrough('AlertDialogTitle'),
  }
})

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

function makeStoreNode(overrides: Record<string, unknown>) {
  return {
    id: 'n',
    shortId: 'n',
    nodeType: 'x',
    name: 'N',
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
    ...overrides,
  } as any
}

function mountCanvas() {
  return mount(WorkflowCanvas, { global: { plugins: [i18n] } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  mockVfNodes.value = []
  mockVfEdges.value = []
  mockViewport.value = { x: 0, y: 0, zoom: 1 }
  mockError.mockClear()
  mockScreenToFlow.mockClear()
})

afterEach(() => {
  // 复位模块级拖拽态单例，避免用例间串味
  useConnectionDragState().endConnect()
})

describe('workflowCanvas connect-start/end 驱动共享拖拽态（SLOT-03）', () => {
  it('connect-start 后 dragging=true 且源 output shape 被记录；connect-end 复位', () => {
    useNodeTypesStore().nodeTypes = [
      makeNodeType({
        node_type: 'ai_plan_research',
        category: 'ai',
        outputs: [makePort('clarify', 'clarification_request')],
      }),
    ]
    useWorkflowsStore().nodes.push(makeStoreNode({ id: 'p', nodeType: 'ai_plan_research' }))

    const wrapper = mountCanvas()
    wrapper.vm.onConnectStart({ nodeId: 'p', handleId: 'clarify', handleType: 'source' })

    const drag = useConnectionDragState()
    expect(drag.dragging.value).toBe(true)
    expect(drag.source.value?.shape).toBe('clarification_request')

    wrapper.vm.onConnectEnd()
    expect(drag.dragging.value).toBe(false)
    expect(drag.source.value).toBeNull()
    expect(wrapper.vm.snapTarget).toBeNull()
  })
})

describe('workflowCanvas onConnect 契约校验（SLOT-03）', () => {
  it('不兼容落点：不 addEdge 且 showError 含 incompatibleBody（真实 zh-CN 文案）', () => {
    useNodeTypesStore().nodeTypes = [
      makeNodeType({ node_type: 'srcT', outputs: [makePort('out', 'feishu_message')] }),
      makeNodeType({ node_type: 'tgtT', inputs: [makePort('in', 'feishu_document')] }),
    ]
    mockVfNodes.value = [
      { id: 's', data: { nodeType: 'srcT' } },
      { id: 't', data: { nodeType: 'tgtT' } },
    ]
    const store = useWorkflowsStore()
    const addEdge = vi.spyOn(store, 'addEdge')

    const wrapper = mountCanvas()
    wrapper.vm.onConnect({ source: 's', sourceHandle: 'out', target: 't', targetHandle: 'in' } as any)

    expect(addEdge).not.toHaveBeenCalled()
    expect(mockError).toHaveBeenCalledTimes(1)
    expect(mockError.mock.calls[0][1]).toContain('形状不兼容')
  })

  it('兼容合法连线（default→default 空契约）：照常 addEdge（零回归）', () => {
    useNodeTypesStore().nodeTypes = [
      makeNodeType({ node_type: 'srcT', outputs: [makePort('default')] }),
      makeNodeType({ node_type: 'tgtT', inputs: [makePort('default')] }),
    ]
    mockVfNodes.value = [
      { id: 's', data: { nodeType: 'srcT' } },
      { id: 't', data: { nodeType: 'tgtT' } },
    ]
    const store = useWorkflowsStore()
    const addEdge = vi.spyOn(store, 'addEdge')

    const wrapper = mountCanvas()
    wrapper.vm.onConnect({ source: 's', sourceHandle: 'default', target: 't', targetHandle: 'default' } as any)

    expect(mockError).not.toHaveBeenCalled()
    expect(addEdge).toHaveBeenCalledTimes(1)
    expect(addEdge.mock.calls[0][0]).toMatchObject({ source: 's', target: 't', targetPort: 'default' })
  })
})

describe('workflowCanvas 吸附端点（SLOT-03 snap-locked）', () => {
  it('兼容候选在吸附半径内 → snapTarget 命中、onConnect 用吸附目标端口', () => {
    useNodeTypesStore().nodeTypes = [
      makeNodeType({ node_type: 'srcT', outputs: [makePort('out', 'feishu_message')] }),
      makeNodeType({ node_type: 'tgtT', inputs: [makePort('msg', 'feishu_message')] }),
    ]
    mockVfNodes.value = [
      { id: 's', data: { nodeType: 'srcT' } },
      { id: 't', type: 'tgtT', data: { nodeType: 'tgtT' }, computedPosition: { x: 300, y: 100 }, dimensions: { width: 200, height: 80 } },
    ]
    const store = useWorkflowsStore()
    const addEdge = vi.spyOn(store, 'addEdge')

    const wrapper = mountCanvas()
    useConnectionDragState().startConnect('s', 'out', 'feishu_message')
    // 单入口 → handle flow y = 100 + 80/2 = 140；指针 (300,140) 命中
    wrapper.vm.updateSnapFromPointer({ clientX: 300, clientY: 140 } as any)

    expect(wrapper.vm.snapTarget).toMatchObject({ nodeId: 't', handleId: 'msg' })

    wrapper.vm.onConnect({ source: 's', sourceHandle: 'out', target: 't', targetHandle: null } as any)
    expect(addEdge).toHaveBeenCalledTimes(1)
    expect(addEdge.mock.calls[0][0]).toMatchObject({ target: 't', targetPort: 'msg' })
  })

  it('不兼容候选 → 不吸附（snapTarget 保持 null，吸附不放行不兼容）', () => {
    useNodeTypesStore().nodeTypes = [
      makeNodeType({ node_type: 'srcT', outputs: [makePort('out', 'feishu_message')] }),
      makeNodeType({ node_type: 'tgtT', inputs: [makePort('doc', 'feishu_document')] }),
    ]
    mockVfNodes.value = [
      { id: 's', data: { nodeType: 'srcT' } },
      { id: 't', type: 'tgtT', data: { nodeType: 'tgtT' }, computedPosition: { x: 300, y: 100 }, dimensions: { width: 200, height: 80 } },
    ]

    const wrapper = mountCanvas()
    useConnectionDragState().startConnect('s', 'out', 'feishu_message')
    wrapper.vm.updateSnapFromPointer({ clientX: 300, clientY: 140 } as any)

    expect(wrapper.vm.snapTarget).toBeNull()
  })
})

describe('workflowCanvas clarify 附着（SLOT-04）', () => {
  it('clarify 槽连 clarification_card → store.attachChild（相对坐标），不建普通边', () => {
    useNodeTypesStore().nodeTypes = [
      makeNodeType({ node_type: 'ai_plan_research', category: 'ai', outputs: [makePort('clarify', 'clarification_request')] }),
      makeNodeType({ node_type: 'clarification_card', category: 'ai', inputs: [makePort('in', 'clarification_request')] }),
    ]
    const store = useWorkflowsStore()
    store.nodes.push(
      makeStoreNode({ id: 'p', nodeType: 'ai_plan_research', position: { x: 0, y: 0 } }),
      makeStoreNode({ id: 'c', nodeType: 'clarification_card', position: { x: 400, y: 200 } }),
    )
    mockVfNodes.value = [
      { id: 'p', data: { nodeType: 'ai_plan_research' } },
      { id: 'c', data: { nodeType: 'clarification_card' } },
    ]
    const attachChild = vi.spyOn(store, 'attachChild')
    const addEdge = vi.spyOn(store, 'addEdge')

    const wrapper = mountCanvas()
    wrapper.vm.onConnect({ source: 'p', sourceHandle: 'clarify', target: 'c', targetHandle: 'in' } as any)

    expect(addEdge).not.toHaveBeenCalled()
    expect(attachChild).toHaveBeenCalledTimes(1)
    expect(attachChild.mock.calls[0][0]).toBe('c')
    expect(attachChild.mock.calls[0][1]).toBe('p')
    expect(attachChild.mock.calls[0][2]).toMatchObject({ x: 400, y: 200 })
  })
})

describe('workflowCanvas 附着编组容器（SLOT-04，WARNING 2 存在性断言）', () => {
  it('有附着子 → 渲染 .slot-attach-group + .slot-attach-connector', () => {
    const store = useWorkflowsStore()
    store.nodes.push(
      makeStoreNode({ id: 'p', nodeType: 'ai_plan_research', position: { x: 0, y: 0 } }),
      makeStoreNode({ id: 'c', nodeType: 'clarification_card', position: { x: 300, y: 120 }, metadata: { parentNodeId: 'p' } }),
    )

    const wrapper = mountCanvas()
    expect(wrapper.vm.attachGroups).toHaveLength(1)
    expect(wrapper.find('.slot-attach-group').exists()).toBe(true)
    expect(wrapper.find('.slot-attach-connector').exists()).toBe(true)
  })

  it('基线无附着关系 → 不渲染 .slot-attach-group', () => {
    const store = useWorkflowsStore()
    store.nodes.push(
      makeStoreNode({ id: 'p', nodeType: 'ai_plan_research' }),
      makeStoreNode({ id: 'o', nodeType: 'http_request' }),
    )

    const wrapper = mountCanvas()
    expect(wrapper.vm.attachGroups).toHaveLength(0)
    expect(wrapper.find('.slot-attach-group').exists()).toBe(false)
  })
})

describe('workflowCanvas 级联删除确认（SLOT-04）', () => {
  it('删带附着子的父节点 → 弹确认（延后删）；确认后 removeNode 级联', () => {
    const store = useWorkflowsStore()
    store.nodes.push(
      makeStoreNode({ id: 'p', nodeType: 'ai_plan_research' }),
      makeStoreNode({ id: 'c', nodeType: 'clarification_card', metadata: { parentNodeId: 'p' } }),
    )
    const removeNode = vi.spyOn(store, 'removeNode')

    const wrapper = mountCanvas()
    wrapper.vm.requestRemoveNode('p')

    expect(removeNode).not.toHaveBeenCalled()
    expect(wrapper.vm.pendingDelete).toMatchObject({ id: 'p', count: 1 })

    wrapper.vm.confirmDelete()
    expect(removeNode).toHaveBeenCalledWith('p')
    expect(wrapper.vm.pendingDelete).toBeNull()
  })

  it('删无附着子的普通节点 → 直接删（零回归，不弹确认）', () => {
    const store = useWorkflowsStore()
    store.nodes.push(makeStoreNode({ id: 'x', nodeType: 'http_request' }))
    const removeNode = vi.spyOn(store, 'removeNode')

    const wrapper = mountCanvas()
    wrapper.vm.requestRemoveNode('x')

    expect(removeNode).toHaveBeenCalledWith('x')
    expect(wrapper.vm.pendingDelete).toBeNull()
  })
})

describe('workflowCanvas 解除附着确认（SLOT-04）', () => {
  it('右键附着子节点 → 弹 detach 确认；确认后 detachChild（恢复绝对坐标）', () => {
    const store = useWorkflowsStore()
    store.nodes.push(
      makeStoreNode({ id: 'p', nodeType: 'ai_plan_research', position: { x: 10, y: 20 } }),
      makeStoreNode({ id: 'c', nodeType: 'clarification_card', position: { x: 30, y: 40 }, metadata: { parentNodeId: 'p' } }),
    )
    const detachChild = vi.spyOn(store, 'detachChild')

    const wrapper = mountCanvas()
    wrapper.vm.onNodeContextMenu({ event: { preventDefault: vi.fn() }, node: { id: 'c', data: { metadata: { parentNodeId: 'p' } } } } as any)
    expect(wrapper.vm.pendingDetach).toMatchObject({ childId: 'c' })

    wrapper.vm.confirmDetach()
    expect(detachChild).toHaveBeenCalledTimes(1)
    expect(detachChild.mock.calls[0][0]).toBe('c')
    // 相对→绝对：父(10,20)+子相对(30,40)=(40,60)
    expect(detachChild.mock.calls[0][1]).toMatchObject({ x: 40, y: 60 })
  })

  it('右键非附着节点 → 不弹解除确认', () => {
    const store = useWorkflowsStore()
    store.nodes.push(makeStoreNode({ id: 'x', nodeType: 'http_request' }))

    const wrapper = mountCanvas()
    wrapper.vm.onNodeContextMenu({ event: { preventDefault: vi.fn() }, node: { id: 'x', data: { metadata: {} } } } as any)
    expect(wrapper.vm.pendingDetach).toBeNull()
  })
})
