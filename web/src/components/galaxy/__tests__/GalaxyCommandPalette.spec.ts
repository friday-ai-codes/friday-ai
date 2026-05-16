/**
 * Phase Plan — GalaxyCommandPalette.vue 组件测试
 * Teleport to="body" 需要在 document.body 中查找元素
 */
import type { GalaxySearchResult } from '~/api/galaxy'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import GalaxyCommandPalette from '../GalaxyCommandPalette.vue'
// 控制 mock 状态的响应式 refs
const mockResults = ref<GalaxySearchResult>
const mockLoading = ref(false)
const mockError = ref<string | null>(null)
const mockSearch = vi.fn
const mockSetCorpus = vi.fn
const mockSearchLocal = vi.fn( => )
vi.mock('~/composables/useGalaxySearch', => ({
 useGalaxySearch: vi.fn( => ({
 query: ref(''),
 results: mockResults,
 loading: mockLoading,
 error: mockError,
 search: mockSearch,
 searchLocal: mockSearchLocal,
 setCorpus: mockSetCorpus,
 })),
}))
function makeResult(overrides: Partial<GalaxySearchResult> = {}): GalaxySearchResult {
 return {
 id: 'symbol:abc',
 type: 'symbol',
 label: 'MyFunction',
 file_path: 'src/utils.ts',
 repository_id: 'repo-1',
 degree: 5,
 ...overrides,
 }
}
describe('GalaxyCommandPalette', => {
 let wrapper: ReturnType<typeof mount>
 beforeEach( => {
 vi.clearAllMocks
 mockResults.value =
 mockLoading.value = false
 mockError.value = null
 })
 afterEach( => {
 wrapper?.unmount
 })
 it('modelValue=true 时在 body 中渲染 dialog', async => {
 wrapper = mount(GalaxyCommandPalette, {
 props: { modelValue: true },
 attachTo: document.body,
 })
 await flushPromises
 expect(document.querySelector('[role="dialog"]')).toBeTruthy
 })
 it('modelValue=false 时不渲染 dialog', async => {
 wrapper = mount(GalaxyCommandPalette, {
 props: { modelValue: false },
 attachTo: document.body,
 })
 await flushPromises
 expect(document.querySelector('[role="dialog"]')).toBeFalsy
 })
 it('显示搜索结果列表', async => {
 mockResults.value = [
 makeResult({ id: 'a', label: 'UserService' }),
 makeResult({ id: 'b', label: 'OrderService' }),
 ]
 wrapper = mount(GalaxyCommandPalette, {
 props: { modelValue: true },
 attachTo: document.body,
 })
 await flushPromises
 const items = document.querySelectorAll('[role="option"]')
 expect(items).toHaveLength(2)
 expect(items[0].textContent).toContain('UserService')
 })
 it('点击结果项 emit node-select', async => {
 const result = makeResult({ id: 'a', label: 'UserService' })
 mockResults.value = [result]
 wrapper = mount(GalaxyCommandPalette, {
 props: { modelValue: true },
 attachTo: document.body,
 })
 await flushPromises
 const item = document.querySelector('[role="option"]') as HTMLElement
 item.click
 await flushPromises
 expect(wrapper.emitted('node-select')).toBeTruthy
 expect(wrapper.emitted('node-select')![0]).toEqual([result])
 })
 it('点击结果项后 emit update:modelValue false', async => {
 mockResults.value = [makeResult]
 wrapper = mount(GalaxyCommandPalette, {
 props: { modelValue: true },
 attachTo: document.body,
 })
 await flushPromises
 const item = document.querySelector('[role="option"]') as HTMLElement
 item.click
 await flushPromises
 expect(wrapper.emitted('update:modelValue')).toBeTruthy
 expect(wrapper.emitted('update:modelValue')![0]).toEqual([false])
 })
 it('loading=true 时显示 spinner 图标', async => {
 mockLoading.value = true
 wrapper = mount(GalaxyCommandPalette, {
 props: { modelValue: true },
 attachTo: document.body,
 })
 await flushPromises
 const spinner = document.querySelector('.animate-spin')
 expect(spinner).toBeTruthy
 })
 it('无输入时显示初始空状态', async => {
 mockResults.value =
 wrapper = mount(GalaxyCommandPalette, {
 props: { modelValue: true },
 attachTo: document.body,
 })
 await flushPromises
 const body = document.querySelector('[role="dialog"]')
 expect(body?.textContent).toContain('输入节点名称或文件路径搜索')
 })
})
