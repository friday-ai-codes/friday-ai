/**
 * StructuredJsonView —— 工具调用 JSON 结构化展示 + 原始切换 + 搜索定制。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StructuredJsonView from '~/components/chat/StructuredJsonView.vue'

describe('structuredJsonView', () => {
  it('对象 input 默认结构化展示，可切换到原始 JSON', async () => {
    const wrapper = mount(StructuredJsonView, {
      props: { value: { query: 'foo', limit: 10 }, toolName: 'search_repository_code', kind: 'input' },
    })
    expect(wrapper.find('.sjv-tree').exists()).toBe(true)
    expect(wrapper.html()).toContain('query')

    const rawBtn = wrapper.findAll('.sjv-switch-btn').find(b => b.text() === '原始 JSON')!
    await rawBtn.trigger('click')
    expect(wrapper.find('.sjv-raw').exists()).toBe(true)
    expect(wrapper.find('.sjv-raw').text()).toContain('"query"')
  })

  it('search_repository_code 输出走定制结果视图 + 诊断', () => {
    const output = JSON.stringify({
      data: { results: [{ file_path: 'a/b.py', repository: 'repo', score: 0.91, snippet: 'def x(): ...' }] },
      metadata: { query: 'entrance', total_results: 1 },
      diagnosis: { summary: '召回 1 条', issues: ['命中较少'], suggestions: ['换关键词'] },
    })
    const wrapper = mount(StructuredJsonView, {
      props: { value: output, toolName: 'mcp__chat-tools__search_repository_code', kind: 'output' },
    })
    expect(wrapper.find('.sjv-search').exists()).toBe(true)
    expect(wrapper.html()).toContain('a/b.py')
    expect(wrapper.html()).toContain('1 条结果')
    expect(wrapper.find('.sjv-diagnosis').exists()).toBe(true)
    expect(wrapper.html()).toContain('换关键词')
  })

  it('search_repository_code 空结果显示未召回', () => {
    const output = JSON.stringify({ data: { results: [] }, metadata: { query: 'x', total_results: 0 } })
    const wrapper = mount(StructuredJsonView, {
      props: { value: output, toolName: 'search_repository_code', kind: 'output' },
    })
    expect(wrapper.find('.sjv-search-empty').exists()).toBe(true)
  })

  it('纯文本（非 JSON）只显示原始模式、不显示切换条', () => {
    const wrapper = mount(StructuredJsonView, {
      props: { value: 'plain text not json', kind: 'output' },
    })
    expect(wrapper.find('.sjv-raw').exists()).toBe(true)
    expect(wrapper.find('.sjv-toolbar').exists()).toBe(false)
  })
})
