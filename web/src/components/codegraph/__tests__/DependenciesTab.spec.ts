/**
 * — DependenciesTab 单测
 * 验证：焦点拉取 neighbors、上下游渲染、空态文案、组件焦点下钻 emit。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DependenciesTab from '../DependenciesTab.vue'

const getNeighbors = vi.fn()

vi.mock('~/api/codegraph', () => ({
  getNeighbors: (...args: unknown[]) => getNeighbors(...args),
}))

vi.mock('@vue-flow/core', () => ({
  VueFlow: {
    template: '<div class="vue-flow-stub"><slot /></div>',
    props: ['nodes', 'edges', 'minZoom', 'maxZoom', 'fitViewOnInit', 'panOnScroll', 'preventScrolling', 'nodesDraggable'],
  },
  useVueFlow: () => ({ fitView: vi.fn() }),
  Panel: { template: '<div class="panel-stub"><slot /></div>', props: ['position'] },
  MarkerType: { ArrowClosed: 'arrowclosed' },
}))

vi.mock('@vue-flow/background', () => ({
  Background: { template: '<div class="bg-stub" />' },
}))

vi.mock('@vue-flow/controls', () => ({
  Controls: { template: '<div class="controls-stub" />' },
}))

vi.mock('~/composables/useDagreLayout', () => ({
  useDagreLayout: () => ({ applyLayout: (nodes: unknown[]) => nodes }),
}))

const REPO = '48338acf-35d3-4b44-abfc-c8946113529e'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('dependenciesTab', () => {
  it('文件焦点输入回车触发 getNeighbors 并渲染上下游', async () => {
    getNeighbors.mockResolvedValueOnce({
      node_type: 'file',
      direction: 'both',
      nodes: [
        { id: 'a.py', type: 'file', label: 'a.py' },
        { id: 'b.py', type: 'file', label: 'b.py' },
        { id: 'c.py', type: 'file', label: 'c.py' },
      ],
      edges: [
        { source: 'a.py', target: 'b.py', kind: 'call', count: 2 },
        { source: 'c.py', target: 'a.py', kind: 'call' },
      ],
    })

    const wrapper = mount(DependenciesTab, { props: { repositoryId: REPO } })
    const input = wrapper.find('input')
    await input.setValue('a.py')
    await input.trigger('keyup.enter')
    await flushPromises()

    expect(getNeighbors).toHaveBeenCalledWith(REPO, 'file', 'a.py', 'both')
    expect(wrapper.find('.vue-flow-stub').exists()).toBe(true)
  })

  it('空依赖显示区分文案', async () => {
    getNeighbors.mockResolvedValueOnce({
      node_type: 'file',
      direction: 'both',
      nodes: [{ id: 'x.py', type: 'file', label: 'x.py' }],
      edges: [],
    })

    const wrapper = mount(DependenciesTab, { props: { repositoryId: REPO } })
    const input = wrapper.find('input')
    await input.setValue('x.py')
    await input.trigger('keyup.enter')
    await flushPromises()

    expect(wrapper.text()).toContain('未发现依赖关系')
  })

  it('组件焦点点击下钻按钮 emit select-symbol', async () => {
    getNeighbors.mockResolvedValue({
      node_type: 'component',
      direction: 'both',
      nodes: [{ id: 'sym-1', type: 'component', label: 'UserCard', file: 'src/UserCard.vue' }],
      edges: [],
    })

    const wrapper = mount(DependenciesTab, {
      props: {
        repositoryId: REPO,
        focus: { nodeType: 'component', id: 'sym-1', label: 'UserCard' },
      },
    })
    await flushPromises()

    expect(getNeighbors).toHaveBeenCalledWith(REPO, 'component', 'sym-1', 'both')
    const drillBtn = wrapper.findAll('button').find(b => b.text().includes('下钻'))
    expect(drillBtn).toBeTruthy()
    await drillBtn!.trigger('click')
    expect(wrapper.emitted('selectSymbol')?.[0]).toEqual(['sym-1'])
  })

  it('未选焦点显示引导文案', () => {
    const wrapper = mount(DependenciesTab, { props: { repositoryId: REPO } })
    expect(wrapper.text()).toContain('作为焦点')
  })
})
