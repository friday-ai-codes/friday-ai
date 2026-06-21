import type { NodeType } from '~/stores/useNodeTypesStore'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import BaseWorkflowNode from '../BaseWorkflowNode.vue'

/**
 * SSOT-02 / D-04：BaseWorkflowNode 的 Handle 由后端 NodePort（store inputs/outputs）渲染。
 *
 * 验证（RESEARCH Pitfall 1）：
 * - 空 store（getNodeType 返回 undefined）→ 回退最小端口（单 in/单 out + default）。
 * - store 就绪后（注入 nodeTypes）→ 按后端端口渲染，且 computed 依赖 store ref 自动重渲染。
 * - 审批节点 outputs 含 approved/rejected。
 *
 * Handle/NodeToolbar/router/toast 为外部框架依赖，以轻量 stub 替身，聚焦端口渲染断言。
 */

// @vue-flow/core：Handle stub 暴露 id/type 供断言；useVueFlow 提供 getSelectedNodes ref
vi.mock('@vue-flow/core', () => ({
  Handle: defineComponent({
    name: 'Handle',
    props: {
      id: { type: String, default: '' },
      type: { type: String, default: '' },
      position: { type: String, default: '' },
    },
    setup(props) {
      return () => h('div', { 'data-testid': 'handle', 'data-handle-id': props.id, 'data-handle-type': props.type, 'data-handle-position': props.position })
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

function makePort(name: string) {
  return { name, label: name, type: 'any', required: false, description: '' }
}

function mountNode(nodeType: string) {
  return mount(BaseWorkflowNode, {
    props: {
      id: 'node-1',
      data: { name: 'Test Node', nodeType },
    },
  })
}

function handleIds(wrapper: ReturnType<typeof mountNode>, type: 'target' | 'source') {
  return wrapper
    .findAll('[data-testid="handle"]')
    .filter(h => h.attributes('data-handle-type') === type)
    .map(h => h.attributes('data-handle-id'))
}

function handlePositions(wrapper: ReturnType<typeof mountNode>, type: 'target' | 'source') {
  return wrapper
    .findAll('[data-testid="handle"]')
    .filter(h => h.attributes('data-handle-type') === type)
    .map(h => h.attributes('data-handle-position'))
}

describe('baseWorkflowNode Handle 渲染', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('空 store（getNodeType undefined）回退最小端口：单 in / 单 out default', () => {
    const wrapper = mountNode('ai_coding')

    expect(handleIds(wrapper, 'target')).toEqual(['default'])
    expect(handleIds(wrapper, 'source')).toEqual(['default'])
  })

  it('入 Handle 永远左入（left）、出 Handle 永远右出（right）', () => {
    const wrapper = mountNode('ai_coding')

    expect(handlePositions(wrapper, 'target')).toEqual(['left'])
    expect(handlePositions(wrapper, 'source')).toEqual(['right'])
  })

  it('触发器节点（inputs 为空 / category trigger）不渲染入 Handle', async () => {
    const store = useNodeTypesStore()
    store.nodeTypes = [
      makeNodeType({
        node_type: 'manual_trigger',
        category: 'trigger',
        inputs: [],
        outputs: [makePort('default')],
      }),
    ]

    const wrapper = mountNode('manual_trigger')
    await nextTick()

    expect(handleIds(wrapper, 'target')).toEqual([])
    expect(handleIds(wrapper, 'source')).toEqual(['default'])
  })

  it('store 就绪后 ai_coding 渲染后端输入端口 plan（computed 自动重渲染）', async () => {
    const store = useNodeTypesStore()
    const wrapper = mountNode('ai_coding')

    // 首帧空 store → 回退
    expect(handleIds(wrapper, 'target')).toEqual(['default'])

    store.nodeTypes = [
      makeNodeType({
        node_type: 'ai_coding',
        category: 'ai',
        inputs: [makePort('plan')],
        outputs: [makePort('coding_result')],
      }),
    ]
    await nextTick()

    expect(handleIds(wrapper, 'target')).toContain('plan')
    expect(handleIds(wrapper, 'source')).toContain('coding_result')
  })

  it('审批节点 outputs 含 approved 与 rejected', async () => {
    const store = useNodeTypesStore()
    store.nodeTypes = [
      makeNodeType({
        node_type: 'human_approval',
        category: 'control',
        inputs: [makePort('default')],
        outputs: [makePort('approved'), makePort('rejected')],
      }),
    ]

    const wrapper = mountNode('human_approval')
    await nextTick()

    const outputs = handleIds(wrapper, 'source')
    expect(outputs).toContain('approved')
    expect(outputs).toContain('rejected')
  })
})
