import { readFileSync } from 'node:fs'
import path from 'node:path'
/**
 * PromptBodyEditor.vue 单测
 *
 * 策略说明(happy-dom 下 CodeMirror smoke 测试):
 * - happy-dom 不支持 contenteditable 真实输入模拟,因此不测真实键入
 * - 断言集中在 DOM 结构/class/style 这三个可静态验证的契约
 * - emit 测试通过触发内部 Codemirror 组件的 update:modelValue 事件,绕开真实输入路径
 * - import 字面量检查通过读取 SFC 源文件完成,避免运行时反射失败
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { Codemirror } from 'vue-codemirror'
import PromptBodyEditor from '../PromptBodyEditor.vue'
// Wave 的契约测试(variableHighlight.test.ts)使用 Node 全局 __dirname 成功,
// 本文件沿用同一模式。vitest 在 ESM 下也注入 __dirname shim,fileURLToPath 会失败。
const sfcPath = path.resolve(__dirname, '../PromptBodyEditor.vue')
describe('promptBodyEditor', => {
 it('渲染外层 wrapper(Glassmorphism class 组合)', => {
 const wrapper = mount(PromptBodyEditor, {
 props: { modelValue: '{{greeting}} 世界' },
 })
 const outer = wrapper.find('div.rounded-lg')
 expect(outer.exists).toBe(true)
 expect(outer.classes).toContain('overflow-hidden')
 expect(outer.classes).toContain('border')
 expect(outer.classes).toContain('border-border/50')
 })
 it('外层 wrapper 固定 480px 高度(work item CodeMirror 视觉契约)', => {
 const wrapper = mount(PromptBodyEditor, {
 props: { modelValue: '' },
 })
 const outer = wrapper.find('div.rounded-lg')
 expect(outer.attributes('style')).toContain('height: 480px')
 })
 it('包含 Codemirror 子组件(smoke)', => {
 const wrapper = mount(PromptBodyEditor, {
 props: { modelValue: '{{name}}' },
 })
 const cm = wrapper.findComponent(Codemirror)
 expect(cm.exists).toBe(true)
 })
 it('modelValue prop 透传给 Codemirror', => {
 const wrapper = mount(PromptBodyEditor, {
 props: { modelValue: 'hello {{name}}' },
 })
 const cm = wrapper.findComponent(Codemirror)
 expect(cm.props('modelValue')).toBe('hello {{name}}')
 })
 it('emits update:modelValue 当 Codemirror 子组件触发变更', async => {
 const wrapper = mount(PromptBodyEditor, {
 props: { modelValue: 'old' },
 })
 const cm = wrapper.findComponent(Codemirror)
 cm.vm.$emit('update:modelValue', 'new value')
 await wrapper.vm.$nextTick
 const emitted = wrapper.emitted('update:modelValue')
 expect(emitted).toBeTruthy
 expect(emitted?.[0]).toEqual(['new value'])
 })
 it('readonly prop 映射为 Codemirror 的 disabled 属性', => {
 const wrapper = mount(PromptBodyEditor, {
 props: { modelValue: '', readonly: true },
 })
 const cm = wrapper.findComponent(Codemirror)
 expect(cm.props('disabled')).toBe(true)
 })
 it('源文件 import variableHighlight 扩展(契约)', => {
 const source = readFileSync(sfcPath, 'utf-8')
 expect(source).toContain('from \'./codemirror/variableHighlight\'')
 expect(source).toContain('variableHighlight')
 })
 it('源文件扩展栈使用 fridayLightTheme / search / lineWrapping(契约)', => {
 const source = readFileSync(sfcPath, 'utf-8')
 // 浅色主题取代 oneDark —— 详见 PromptBodyEditor.vue 顶部「视觉设计变更」注释。
 expect(source).not.toContain('@codemirror/theme-one-dark')
 expect(source).toContain('fridayLightTheme')
 expect(source).toContain('@codemirror/search')
 expect(source).toContain('EditorView.lineWrapping')
 })
 it('源文件不包含 lang-markdown / lang-handlebars(契约:Prompt 语法是纯 Jinja2)', => {
 const source = readFileSync(sfcPath, 'utf-8')
 expect(source).not.toContain('lang-markdown')
 expect(source).not.toContain('lang-handlebars')
 })
 it('源文件包含:deep(.cm-prompt-variable) 与精确 HSL 值(work item 契约)', => {
 const source = readFileSync(sfcPath, 'utf-8')
 expect(source).toContain(':deep(.cm-prompt-variable)')
 expect(source).toContain('hsl(168 76% 42%)')
 expect(source).toContain(':deep(.cm-prompt-variable-unknown)')
 expect(source).toContain('hsl(0 72% 51%)')
 })
})
