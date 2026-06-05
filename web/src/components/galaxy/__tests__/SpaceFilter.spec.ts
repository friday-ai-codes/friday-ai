/**
 * SpaceFilter.vue 单元测试
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SpaceFilter from '../SpaceFilter.vue'

// mock ui/select 为可控的简化版本（保留 v-model 语义）
vi.mock('~/components/ui/select', () => {
  return {
    Select: {
      name: 'Select',
      props: ['modelValue', 'disabled'],
      emits: ['update:modelValue'],
      template: `
        <div class="mock-select" :data-value="modelValue" :data-disabled="String(disabled)">
          <slot />
        </div>
      `,
    },
    SelectTrigger: {
      name: 'SelectTrigger',
      template: '<button class="mock-trigger"><slot /></button>',
    },
    SelectValue: {
      name: 'SelectValue',
      props: ['placeholder'],
      template: '<span class="mock-value">{{ placeholder }}</span>',
    },
    SelectContent: {
      name: 'SelectContent',
      template: '<div class="mock-content"><slot /></div>',
    },
    SelectItem: {
      name: 'SelectItem',
      props: ['value'],
      template: '<div class="mock-item" :data-value="value"><slot /></div>',
    },
  }
})

const mockFetchSpaces = vi.fn().mockResolvedValue(undefined)
let mockSpaces: Array<{ id: string, name: string }> = []

vi.mock('~/stores/spaces', () => ({
  useSpacesStore: vi.fn(() => ({
    get spaces() { return mockSpaces },
    loading: false,
    fetchSpaces: mockFetchSpaces,
  })),
}))

describe('spaceFilter.vue', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockSpaces = [
      { id: 'space-1', name: '空间一' },
      { id: 'space-2', name: '空间二' },
    ]
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('挂载时若 store 为空则调用 fetchSpaces', async () => {
    mockSpaces = []
    mount(SpaceFilter, { props: { modelValue: null } })
    await flushPromises()
    expect(mockFetchSpaces).toHaveBeenCalled()
  })

  it('渲染所有空间作为 SelectItem + 全部空间默认项', async () => {
    const wrapper = mount(SpaceFilter, { props: { modelValue: null } })
    await flushPromises()
    const items = wrapper.findAll('.mock-item')
    // 1 个"全部空间" + 2 个 mock space
    expect(items.length).toBe(3)
    expect(items[0].text()).toBe('全部空间')
    expect(items[1].text()).toBe('空间一')
    expect(items[2].text()).toBe('空间二')
  })

  it('modelValue=null → Select.modelValue=__all__', async () => {
    const wrapper = mount(SpaceFilter, { props: { modelValue: null } })
    await flushPromises()
    expect(wrapper.find('.mock-select').attributes('data-value')).toBe('__all__')
  })

  it('modelValue=space-1 → Select.modelValue=space-1', async () => {
    const wrapper = mount(SpaceFilter, { props: { modelValue: 'space-1' } })
    await flushPromises()
    expect(wrapper.find('.mock-select').attributes('data-value')).toBe('space-1')
  })

  it('select 触发 __all__ → emit update:modelValue null', async () => {
    const wrapper = mount(SpaceFilter, { props: { modelValue: 'space-1' } })
    await flushPromises()
    const select = wrapper.findComponent({ name: 'Select' })
    select.vm.$emit('update:modelValue', '__all__')
    await flushPromises()
    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted).toBeTruthy()
    expect(emitted![emitted!.length - 1]).toEqual([null])
  })

  it('select 触发 space-2 → emit update:modelValue space-2', async () => {
    const wrapper = mount(SpaceFilter, { props: { modelValue: null } })
    await flushPromises()
    const select = wrapper.findComponent({ name: 'Select' })
    select.vm.$emit('update:modelValue', 'space-2')
    await flushPromises()
    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted).toBeTruthy()
    expect(emitted![emitted!.length - 1]).toEqual(['space-2'])
  })
})
