/**
 * PromptMetadataForm.vue 单测
 *
 * 覆盖:
 * - 只读徽章映射:category / scope / is_builtin 文案与 variant 对齐 work item §Color
 * - is_builtin=false 时不渲染 `系统内置` 行(v-if 折叠)
 * - title 初始值从 prop 填充(模拟 edit 模式)
 * - updated_at 本地化时间戳包含年份 2026(不做完整格式断言,避免 locale drift)
 * - Label 文本对齐 work item §Copywriting 只读字段表
 */
import type { PromptDetail } from '~/types/prompts'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PromptMetadataForm from '../PromptMetadataForm.vue'
const mockPrompt: PromptDetail = {
 id: '11111111-1111-1111-1111-111111111111',
 slug: 'chat.system.developer',
 category: 'chat_agent',
 scope: 'system',
 project: null,
 title: '开发者助手',
 description: '默认对话提示',
 is_builtin: true,
 active_version: null,
 declared_variables:,
 created_by: 1,
 created_at: '2026-04-01T00:00:00Z',
 updated_at: '2026-04-10T00:00:00Z',
}
describe('promptMetadataForm', => {
 it('渲染只读分类徽章 "对话"', => {
 const wrapper = mount(PromptMetadataForm, {
 props: { prompt: mockPrompt, mode: 'edit' },
 })
 expect(wrapper.text).toContain('对话')
 })
 it('渲染只读范围徽章 "系统级"', => {
 const wrapper = mount(PromptMetadataForm, {
 props: { prompt: mockPrompt, mode: 'edit' },
 })
 expect(wrapper.text).toContain('系统级')
 })
 it('is_builtin=true 时显示 "系统内置" 徽章', => {
 const wrapper = mount(PromptMetadataForm, {
 props: { prompt: mockPrompt, mode: 'edit' },
 })
 expect(wrapper.text).toContain('系统内置')
 })
 it('is_builtin=false 时不显示 "系统内置" 行', => {
 const wrapper = mount(PromptMetadataForm, {
 props: { prompt: { ...mockPrompt, is_builtin: false }, mode: 'edit' },
 })
 const html = wrapper.html
 expect(html).not.toContain('系统内置')
 })
 it('title input 初始值填充', => {
 const wrapper = mount(PromptMetadataForm, {
 props: { prompt: mockPrompt, mode: 'edit' },
 })
 const titleInput = wrapper.find('input')
 expect((titleInput.element as HTMLInputElement).value).toBe('开发者助手')
 })
 it('description textarea 初始值填充', => {
 const wrapper = mount(PromptMetadataForm, {
 props: { prompt: mockPrompt, mode: 'edit' },
 })
 const textarea = wrapper.find('textarea')
 expect((textarea.element as HTMLTextAreaElement).value).toBe('默认对话提示')
 })
 it('只读 Label 文本对齐 work item 只读字段表', => {
 const wrapper = mount(PromptMetadataForm, {
 props: { prompt: mockPrompt, mode: 'edit' },
 })
 const text = wrapper.text
 expect(text).toContain('Slug')
 expect(text).toContain('分类')
 expect(text).toContain('范围')
 expect(text).toContain('最后更新')
 expect(text).toContain('标题')
 expect(text).toContain('描述')
 })
 it('updated_at 显示为本地化时间字符串(含年份 2026)', => {
 const wrapper = mount(PromptMetadataForm, {
 props: { prompt: mockPrompt, mode: 'edit' },
 })
 expect(wrapper.text).toContain('2026')
 })
 it('prompt=null 时不渲染只读元信息区', => {
 const wrapper = mount(PromptMetadataForm, {
 props: { prompt: null, mode: 'create' },
 })
 expect(wrapper.text).not.toContain('Slug')
 // title / description 字段仍应渲染(可写)
 expect(wrapper.find('input').exists).toBe(true)
 })
 it('category=ai_node 时渲染 "AI 节点" 文案', => {
 const wrapper = mount(PromptMetadataForm, {
 props: {
 prompt: { ...mockPrompt, category: 'ai_node' },
 mode: 'edit',
 },
 })
 expect(wrapper.text).toContain('AI 节点')
 })
})
