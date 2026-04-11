/**
 * PromptVariableForm.vue 单元测试
 *
 * 覆盖路径（Plan Task 1 behavior §1）：
 * 1. body 中单个 {{name}} 生成 Input 字段
 * 2. variablesSchema 带 description 的变量使用 Textarea 且 placeholder 含描述
 * 3. 用户输入时 emit update:values 事件
 * 4. 超过 1024 字符显示 inline 错误并禁止 emit
 * 5. missingVariables prop 命中的字段显示 border-destructive + '此变量为必填'
 * 6. variablesSchema.default 作为 Input 初始值
 */
import type { VariableSpec } from '~/types/prompts'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PromptVariableForm from '../PromptVariableForm.vue'
function makeWrapper(options: {
 body: string
 variablesSchema?: Record<string, VariableSpec>
 missingVariables?: string
}) {
 return mount(PromptVariableForm, {
 props: {
 body: options.body,
 variablesSchema: options.variablesSchema ?? {},
 missingVariables: options.missingVariables,
 },
 })
}
describe('promptVariableForm.vue', => {
 it('body 中单个变量渲染一个 Input + Label', => {
 const wrapper = makeWrapper({ body: 'Hello {{name}}' })
 const labels = wrapper.findAll('label')
 expect(labels.length).toBeGreaterThan(0)
 expect(wrapper.text).toContain('name')
 // 单变量 + 未设置 description + 值为空 → 走 Input 分支（不是 textarea）
 expect(wrapper.find('input').exists).toBe(true)
 })
 it('带 description 的变量使用 Textarea 且 placeholder 含描述', => {
 const wrapper = makeWrapper({
 body: '{{long_text}}',
 variablesSchema: {
 long_text: { description: '多行描述' },
 },
 })
 const textarea = wrapper.find('textarea')
 expect(textarea.exists).toBe(true)
 expect(textarea.attributes('placeholder')).toContain('多行描述')
 })
 it('用户输入后 emit update:values 事件', async => {
 const wrapper = makeWrapper({ body: '{{name}}' })
 const input = wrapper.find('input')
 await input.setValue('Alice')
 const events = wrapper.emitted('update:values')
 expect(events).toBeTruthy
 // 最后一次 emit 应携带 { name: 'Alice' }
 expect(events?.[events.length - 1][0]).toEqual({ name: 'Alice' })
 })
 it('超过 1024 字符显示 inline 错误且不 emit', async => {
 const wrapper = makeWrapper({ body: '{{long}}' })
 const tooLong = 'a'.repeat(1025)
 // 此处用 input，因为初始值短，走 Input 分支
 const input = wrapper.find('input')
 await input.setValue(tooLong)
 expect(wrapper.text).toContain('变量值不能超过 1024 字符')
 // emit 不应包含超长值
 const events = wrapper.emitted('update:values')
 const lastCall = events?.[events.length - 1]?.[0] as Record<string, string> | undefined
 expect(lastCall?.long ?? '').not.toBe(tooLong)
 })
 it('missingVariables 命中的字段显示 border-destructive 与必填错误文本', => {
 const wrapper = makeWrapper({
 body: '{{input_text}}',
 missingVariables: ['input_text'],
 })
 expect(wrapper.text).toContain('此变量为必填')
 // input 或 textarea 任一 class 包含 border-destructive
 const rendered = wrapper.html
 expect(rendered).toContain('border-destructive')
 })
 it('variablesSchema.default 作为 Input 初始值', => {
 const wrapper = makeWrapper({
 body: '{{name}}',
 variablesSchema: {
 name: { default: 'Bob' },
 },
 })
 const input = wrapper.find('input')
 expect((input.element as HTMLInputElement).value).toBe('Bob')
 })
})
