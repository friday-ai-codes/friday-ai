/**
 * — CompactEmptyState 紧凑空态组件单测
 *
 * 验证：icon/title/description 渲染、默认 slot（CTA）渲染、紧凑容器契约
 * （居中布局类 items-center/text-center 且不含全页级 EmptyState 的 py-16）。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CompactEmptyState from '../CompactEmptyState.vue'

describe('compactEmptyState', () => {
  it('渲染传入的 icon / title / description', () => {
    const wrapper = mount(CompactEmptyState, {
      props: {
        icon: 'lucide--folder',
        title: '暂无关联空间',
        description: '将仓库关联到空间后统一管理',
      },
    })
    const text = wrapper.text()
    expect(text).toContain('暂无关联空间')
    expect(text).toContain('将仓库关联到空间后统一管理')
    expect(wrapper.html()).toContain('icon-[lucide--folder]')
  })

  it('description 为空时不渲染描述段落', () => {
    const wrapper = mount(CompactEmptyState, {
      props: { title: '空空如也' },
    })
    expect(wrapper.text()).toContain('空空如也')
    // 默认 description 为空字符串 → 不渲染 description <p>
    expect(wrapper.findAll('p')).toHaveLength(1)
  })

  it('渲染默认 slot（CTA）内容', () => {
    const wrapper = mount(CompactEmptyState, {
      props: { title: '暂无数据' },
      slots: { default: '<button class="cta-btn">前往空间管理</button>' },
    })
    expect(wrapper.find('.cta-btn').exists()).toBe(true)
    expect(wrapper.text()).toContain('前往空间管理')
  })

  it('未传 slot 时不渲染 CTA 容器', () => {
    const wrapper = mount(CompactEmptyState, {
      props: { title: '暂无数据' },
    })
    expect(wrapper.find('.cta-btn').exists()).toBe(false)
  })

  it('紧凑容器契约：居中布局 + 无全页级 py-16', () => {
    const wrapper = mount(CompactEmptyState, {
      props: { title: '暂无数据' },
    })
    const root = wrapper.element as HTMLElement
    const cls = root.className
    expect(cls).toContain('items-center')
    expect(cls).toContain('text-center')
    // 紧凑回归守门：不得退化为全页级 EmptyState 的 py-16
    expect(wrapper.html()).not.toContain('py-16')
  })
})
