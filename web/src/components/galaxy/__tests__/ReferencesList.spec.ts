/**
 * — ReferencesList.vue 组件测试（shape 与后端 GalaxyNodeDetail 对齐）
 */
import type { GalaxyEdge, GalaxyNode, GalaxyReference } from '~/api/galaxy'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReferencesList from '../ReferencesList.vue'

function makeNode(overrides: Partial<GalaxyNode> = {}): GalaxyNode {
  return {
    id: 'symbol:abc',
    type: 'symbol',
    label: 'MyFunction',
    file_path: 'src/utils.ts',
    repository_id: 'repo-1',
    line_start: 10,
    line_end: 20,
    metadata: {},
    degree: 5,
    ...overrides,
  }
}

function makeEdge(overrides: Partial<GalaxyEdge> = {}): GalaxyEdge {
  return {
    id: 'edge-1',
    source: 'symbol:abc',
    target: 'symbol:def',
    edge_type: 'CALL',
    weight: 0.8,
    repository_id: 'repo-1',
    target_repository_id: null,
    metadata: {},
    ...overrides,
  }
}

function makeReference(overrides: Partial<GalaxyReference> = {}): GalaxyReference {
  return {
    type: 'api_call_site',
    id: 'callsite:1',
    label: 'fetchUsers()',
    repository_id: 'repo-2',
    match_confidence: 0.95,
    ...overrides,
  }
}

describe('referencesList', () => {
  it('渲染 called_by 段落', async () => {
    const wrapper = mount(ReferencesList, {
      props: {
        calledBy: [
          makeReference({ id: 'symbol:caller1', label: 'callerOne' }),
          makeReference({ id: 'symbol:caller2', label: 'callerTwo' }),
        ],
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('被调用')
    expect(wrapper.text()).toContain('callerOne')
    expect(wrapper.text()).toContain('callerTwo')
    wrapper.unmount()
  })

  it('渲染 references（引用方）段落', async () => {
    const wrapper = mount(ReferencesList, {
      props: {
        calls: [makeReference({ label: 'getUserApi()' })],
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('引用方')
    expect(wrapper.text()).toContain('getUserApi()')
    expect(wrapper.text()).toContain('95%')
    wrapper.unmount()
  })

  it('渲染 neighbors 段落（含边类型与方向）', async () => {
    const wrapper = mount(ReferencesList, {
      props: {
        neighbors: [
          {
            node: makeNode({ id: 'n1', label: 'HelperFn' }),
            edge: makeEdge({ edge_type: 'SEMANTIC' }),
            direction: 'outgoing' as const,
          },
        ],
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('关联节点')
    expect(wrapper.text()).toContain('HelperFn')
    expect(wrapper.text()).toContain('SEMANTIC')
    expect(wrapper.text()).toContain('→')
    wrapper.unmount()
  })

  it('incoming 邻居显示入边箭头', async () => {
    const wrapper = mount(ReferencesList, {
      props: {
        neighbors: [
          {
            node: makeNode({ id: 'n2', label: 'CallerFn' }),
            edge: makeEdge(),
            direction: 'incoming' as const,
          },
        ],
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('←')
    wrapper.unmount()
  })

  it('点击 called_by 项 emit node-select', async () => {
    const wrapper = mount(ReferencesList, {
      props: {
        calledBy: [makeReference({ id: 'symbol:caller' })],
      },
    })
    await flushPromises()
    const items = wrapper.findAll('li')
    await items[0].trigger('click')
    expect(wrapper.emitted('node-select')).toBeTruthy()
    expect(wrapper.emitted('node-select')![0]).toEqual(['symbol:caller'])
    wrapper.unmount()
  })

  it('点击 neighbors 项 emit node-select 正确 nodeId', async () => {
    const wrapper = mount(ReferencesList, {
      props: {
        neighbors: [
          {
            node: makeNode({ id: 'symbol:nbr' }),
            edge: makeEdge(),
            direction: 'incoming' as const,
          },
        ],
      },
    })
    await flushPromises()
    const items = wrapper.findAll('li')
    await items[0].trigger('click')
    expect(wrapper.emitted('node-select')![0]).toEqual(['symbol:nbr'])
    wrapper.unmount()
  })

  it('全空时显示空状态', async () => {
    const wrapper = mount(ReferencesList, {
      props: {},
    })
    await flushPromises()
    expect(wrapper.text()).toContain('暂无引用关系')
    wrapper.unmount()
  })

  it('loading=true 时显示骨架', async () => {
    const wrapper = mount(ReferencesList, {
      props: { loading: true },
    })
    await flushPromises()
    expect(wrapper.find('.animate-pulse').exists()).toBe(true)
    wrapper.unmount()
  })
})
