/**
 * VariableSchemaEditor.vue 单测
 *
 * 覆盖:
 *   - Label 文本 「变量元数据（JSON）」严格对齐 UI-SPEC §Copywriting
 *   - 内嵌 JsonEditor 子组件(通过 import 引用定位,不依赖 name 注册)
 *   - modelValue 对象序列化为格式化 JSON 字符串传给 JsonEditor
 *   - 有效 JSON 字符串 → emit update:modelValue 为对象
 *   - 无效 JSON 字符串 → emit parse-error 事件
 *   - 非对象 JSON(数组 / null / primitive) → emit parse-error 事件
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import JsonEditor from '~/components/execution/JsonEditor.vue'
import VariableSchemaEditor from '../VariableSchemaEditor.vue'

describe('variableSchemaEditor', () => {
  it('渲染 label 「变量元数据（JSON）」', () => {
    const wrapper = mount(VariableSchemaEditor, {
      props: { modelValue: {} },
    })
    expect(wrapper.text()).toContain('变量元数据（JSON）')
  })

  it('内嵌 JsonEditor 子组件', () => {
    const wrapper = mount(VariableSchemaEditor, {
      props: { modelValue: { name: { required: true } } },
    })
    const je = wrapper.findComponent(JsonEditor)
    expect(je.exists()).toBe(true)
  })

  it('modelValue 对象序列化为格式化 JSON 字符串传给 JsonEditor', () => {
    const wrapper = mount(VariableSchemaEditor, {
      props: { modelValue: { name: { required: true } } },
    })
    const je = wrapper.findComponent(JsonEditor)
    const passed = je.props('modelValue') as string
    expect(JSON.parse(passed)).toEqual({ name: { required: true } })
  })

  it('jsonEditor 高度固定 240px(UI-SPEC CodeMirror 视觉契约)', () => {
    const wrapper = mount(VariableSchemaEditor, {
      props: { modelValue: {} },
    })
    const je = wrapper.findComponent(JsonEditor)
    expect(je.props('height')).toBe('240px')
  })

  it('无效 JSON 触发 parse-error 事件', async () => {
    const wrapper = mount(VariableSchemaEditor, {
      props: { modelValue: {} },
    })
    const je = wrapper.findComponent(JsonEditor)
    je.vm.$emit('update:modelValue', '{invalid json')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('parseError')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')).toBeFalsy()
  })

  it('有效 JSON 触发 update:modelValue 事件且值为对象', async () => {
    const wrapper = mount(VariableSchemaEditor, {
      props: { modelValue: {} },
    })
    const je = wrapper.findComponent(JsonEditor)
    je.vm.$emit('update:modelValue', '{"age":{"required":false}}')
    await wrapper.vm.$nextTick()
    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted).toBeTruthy()
    expect(emitted?.[0]?.[0]).toEqual({ age: { required: false } })
  })

  it('jSON 数组(非对象)触发 parse-error,拒绝通过', async () => {
    const wrapper = mount(VariableSchemaEditor, {
      props: { modelValue: {} },
    })
    const je = wrapper.findComponent(JsonEditor)
    je.vm.$emit('update:modelValue', '[1, 2, 3]')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('parseError')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')).toBeFalsy()
  })

  it('jSON null(非对象)触发 parse-error,拒绝通过', async () => {
    const wrapper = mount(VariableSchemaEditor, {
      props: { modelValue: {} },
    })
    const je = wrapper.findComponent(JsonEditor)
    je.vm.$emit('update:modelValue', 'null')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('parseError')).toBeTruthy()
  })

  it('外部 modelValue 变化时重新序列化并同步到 JsonEditor', async () => {
    const wrapper = mount(VariableSchemaEditor, {
      props: { modelValue: {} },
    })
    await wrapper.setProps({ modelValue: { foo: { required: true } } })
    await wrapper.vm.$nextTick()
    const je = wrapper.findComponent(JsonEditor)
    const passed = je.props('modelValue') as string
    expect(JSON.parse(passed)).toEqual({ foo: { required: true } })
  })
})
