/**
 * PromptVariablePanel.vue 单测
 *
 * 覆盖:
 * - body 扫描 → detectedVariables computed 正确列出字母序变量
 * - 三态徽章:required=true → 必填,required=false → 可选,schema 缺该 key → 未声明
 * - 空态文案 「当前正文未检测到变量」
 * - 响应式:body / variablesSchema 变化 watch 生效
 * - 底部警告文字 「此变量未在元数据中声明」在任意未声明变量存在时可见
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PromptVariablePanel from '../PromptVariablePanel.vue'
describe('promptVariablePanel', => {
 it('body 含两个变量且 schema 为空 → 显示两行 + 未声明徽章', => {
 const wrapper = mount(PromptVariablePanel, {
 props: { body: '{{name}} {{age}}', variablesSchema: {} },
 })
 const items = wrapper.findAll('li')
 expect(items).toHaveLength(2)
 // extractVariables 返回字母序,age 在 name 之前
 expect(items[0].text).toContain('age')
 expect(items[1].text).toContain('name')
 expect(wrapper.text).toContain('未声明')
 })
 it('变量在 schema 中 required=true → 显示必填徽章,不显示未声明', => {
 const wrapper = mount(PromptVariablePanel, {
 props: {
 body: '{{name}}',
 variablesSchema: { name: { required: true } },
 },
 })
 expect(wrapper.text).toContain('必填')
 expect(wrapper.text).not.toContain('未声明')
 })
 it('变量在 schema 中 required=false → 显示可选徽章', => {
 const wrapper = mount(PromptVariablePanel, {
 props: {
 body: '{{name}}',
 variablesSchema: { name: { required: false } },
 },
 })
 expect(wrapper.text).toContain('可选')
 expect(wrapper.text).not.toContain('必填')
 expect(wrapper.text).not.toContain('未声明')
 })
 it('变量在 schema 中未指定 required → 按 falsy 处理(可选)', => {
 const wrapper = mount(PromptVariablePanel, {
 props: {
 body: '{{name}}',
 variablesSchema: { name: {} },
 },
 })
 expect(wrapper.text).toContain('可选')
 expect(wrapper.text).not.toContain('未声明')
 })
 it('body 为空 → 显示空态文案,不渲染 <ul>', => {
 const wrapper = mount(PromptVariablePanel, {
 props: { body: '', variablesSchema: {} },
 })
 expect(wrapper.text).toContain('当前正文未检测到变量')
 expect(wrapper.find('ul').exists).toBe(false)
 })
 it('body 中无 {{var}} 占位符 → 显示空态', => {
 const wrapper = mount(PromptVariablePanel, {
 props: { body: '普通的纯文本,没有任何变量', variablesSchema: {} },
 })
 expect(wrapper.text).toContain('当前正文未检测到变量')
 })
 it('body 响应式变化:从 {{a}} 变为 {{a}} {{b}} 后变量列表更新', async => {
 const wrapper = mount(PromptVariablePanel, {
 props: { body: '{{a}}', variablesSchema: {} },
 })
 expect(wrapper.findAll('li')).toHaveLength(1)
 await wrapper.setProps({ body: '{{a}} {{b}}', variablesSchema: {} })
 expect(wrapper.findAll('li')).toHaveLength(2)
 })
 it('存在未声明变量时展示底部警告文本', => {
 const wrapper = mount(PromptVariablePanel, {
 props: { body: '{{undefined_var}}', variablesSchema: {} },
 })
 expect(wrapper.text).toContain('此变量未在元数据中声明')
 })
 it('所有变量均已声明时不展示底部警告文本', => {
 const wrapper = mount(PromptVariablePanel, {
 props: {
 body: '{{name}}',
 variablesSchema: { name: { required: true } },
 },
 })
 expect(wrapper.text).not.toContain('此变量未在元数据中声明')
 })
 it('section 标题 「变量」 始终可见', => {
 const wrapper = mount(PromptVariablePanel, {
 props: { body: '', variablesSchema: {} },
 })
 const h = wrapper.find('h4')
 expect(h.exists).toBe(true)
 expect(h.text).toBe('变量')
 })
})
