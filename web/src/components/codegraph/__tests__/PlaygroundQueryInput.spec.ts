/**
 * Phase Plan — PlaygroundQueryInput 单测
 * 验证：执行按钮 emit('search')，在 Chat 中提问按钮 emit('chat-prefill')
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import PlaygroundQueryInput from '../PlaygroundQueryInput.vue'
vi.mock('~/api/repositories', => ({
 repositoriesApi: {
 list: vi.fn.mockResolvedValue([
 { id: 'repo-1', name: '仓库 A' },
 { id: 'repo-2', name: '仓库 B' },
 ]),
 },
}))
const stubComponents = {
 Textarea: defineComponent({
 props: ['modelValue', 'placeholder'],
 emits: ['update:modelValue'],
 template: '<textarea:placeholder="placeholder":value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
 }),
 Slider: defineComponent({
 props: ['modelValue', 'min', 'max', 'step'],
 emits: ['update:modelValue'],
 template: '<input type="range" />',
 }),
 Button: defineComponent({
 props: ['disabled', 'variant'],
 template: '<button:disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
 }),
}
function mountInput(loading = false) {
 return mount(PlaygroundQueryInput, {
 props: { loading },
 global: { stubs: stubComponents },
 })
}
describe('PlaygroundQueryInput', => {
 beforeEach( => {
 vi.clearAllMocks
 })
 it('A: 点击"执行检索"按钮 emit search 事件（含 query/repositoryIds/maxTokens）', async => {
 const wrapper = mountInput
 await flushPromises
 // 填写查询
 const textarea = wrapper.find('textarea')
 await textarea.setValue('如何实现认证？')
 // 点击执行
 const buttons = wrapper.findAll('button')
 const searchBtn = buttons.find(b => b.text.includes('执行检索'))
 expect(searchBtn).toBeTruthy
 await searchBtn!.trigger('click')
 const emitted = wrapper.emitted('search')
 expect(emitted).toBeTruthy
 expect(emitted!.length).toBeGreaterThan(0)
 const [params] = emitted![0] as [{ query: string, repositoryIds: string, maxTokens: number }]
 expect(params.query).toBe('如何实现认证？')
 expect(Array.isArray(params.repositoryIds)).toBe(true)
 expect(typeof params.maxTokens).toBe('number')
 })
 it('B: 点击"在 Chat 中提问"按钮 emit chat-prefill 事件（含 query）', async => {
 const wrapper = mountInput
 await flushPromises
 const textarea = wrapper.find('textarea')
 await textarea.setValue('分层检索如何工作？')
 const buttons = wrapper.findAll('button')
 const chatBtn = buttons.find(b => b.text.includes('在 Chat 中提问'))
 expect(chatBtn).toBeTruthy
 await chatBtn!.trigger('click')
 const emitted = wrapper.emitted('chat-prefill')
 expect(emitted).toBeTruthy
 const [params] = emitted![0] as [{ query: string, repositoryIds: string }]
 expect(params.query).toBe('分层检索如何工作？')
 })
 it('C: query 为空时执行按钮被 disabled', async => {
 const wrapper = mountInput
 await flushPromises
 const buttons = wrapper.findAll('button')
 const searchBtn = buttons.find(b => b.text.includes('执行检索'))
 expect(searchBtn?.attributes('disabled')).toBeDefined
 })
 it('D: loading=true 时执行按钮被 disabled', async => {
 const wrapper = mountInput(true)
 await flushPromises
 const buttons = wrapper.findAll('button')
 const searchBtn = buttons.find(b => b.text.includes('执行检索'))
 expect(searchBtn?.attributes('disabled')).toBeDefined
 })
})
