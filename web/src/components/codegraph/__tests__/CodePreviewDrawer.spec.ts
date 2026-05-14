/**
 * Phase Plan — CodePreviewDrawer 单测
 * 验证：Sheet open 透传 / chunkId 反查命中渲染 <pre> + header file_path:line /
 * 未命中（chunkId=null / searchResult=null / L3 不存在 / chunk_id 不匹配 /
 * content 空字符串）一律展示 fallback 文案 /
 * v-model:open 双向绑定 emit update:open。
 */
import type { PlaygroundSearchResponse } from '~/api/codegraph'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CodePreviewDrawer from '../CodePreviewDrawer.vue'
vi.mock('~/components/ui/sheet', => ({
 Sheet: {
 name: 'Sheet',
 template: `
 <div class="sheet-stub":data-open="open">
 <button type="button" class="sheet-close-trigger" @click="$emit('update:open', false)">close</button>
 <slot />
 </div>
 `,
 props: ['open'],
 emits: ['update:open'],
 },
 SheetContent: { template: '<div class="sheet-content-stub"><slot /></div>' },
 SheetHeader: { template: '<div class="sheet-header-stub"><slot /></div>' },
 SheetTitle: { template: '<div class="sheet-title-stub"><slot /></div>' },
 SheetDescription: { template: '<div class="sheet-desc-stub"><slot /></div>' },
}))
vi.mock('~/components/ui/scroll-area', => ({
 ScrollArea: { template: '<div class="scroll-area-stub"><slot /></div>' },
}))
const FALLBACK_TEXT = '代码片段未在当前查询命中范围内，无法预览'
function makeSearchResultWithChunk(
 chunk: Record<string, unknown>,
): PlaygroundSearchResponse {
 return {
 query: 'test',
 repository_ids: ['r1'],
 layers: [
 {
 layer: 'L1',
 status: 'ok',
 result_count: 0,
 items:,
 error: null,
 extra: null,
 },
 {
 layer: 'L3',
 status: 'ok',
 result_count: 1,
 items: [chunk],
 error: null,
 extra: null,
 },
 ],
 final_context: '',
 total_tokens: 0,
 }
}
describe('codePreviewDrawer', => {
 it('a: props.open=false → Sheet stub 接收 data-open="false"，不抛错', => {
 const wrapper = mount(CodePreviewDrawer, {
 props: { open: false, chunkId: null, searchResult: null },
 })
 expect(wrapper.find('.sheet-stub').attributes('data-open')).toBe('false')
 })
 it('b: chunkId=null → body 渲染 fallback 文案', => {
 const wrapper = mount(CodePreviewDrawer, {
 props: { open: true, chunkId: null, searchResult: null },
 })
 expect(wrapper.text).toContain(FALLBACK_TEXT)
 })
 it('c: searchResult=null → body 渲染 fallback 文案', => {
 const wrapper = mount(CodePreviewDrawer, {
 props: { open: true, chunkId: 'abc', searchResult: null },
 })
 expect(wrapper.text).toContain(FALLBACK_TEXT)
 })
 it('d: L3 items 命中 chunk_id + content → 渲染 <pre> 含 content；header 含 file_path:line', => {
 const result = makeSearchResultWithChunk({
 chunk_id: 'abc',
 file_path: 'a/b.py',
 line_start: 1,
 line_end: 10,
 content: 'def foo: pass',
 })
 const wrapper = mount(CodePreviewDrawer, {
 props: { open: true, chunkId: 'abc', searchResult: result },
 })
 const html = wrapper.html
 expect(html).toContain('<pre')
 expect(wrapper.text).toContain('def foo: pass')
 expect(wrapper.text).toContain('a/b.py:1-10')
 expect(wrapper.text).not.toContain(FALLBACK_TEXT)
 })
 it('e: 命中 chunk_id 但 content 为空字符串 → fallback', => {
 const result = makeSearchResultWithChunk({
 chunk_id: 'abc',
 file_path: 'a/b.py',
 line_start: 1,
 line_end: 10,
 content: '',
 })
 const wrapper = mount(CodePreviewDrawer, {
 props: { open: true, chunkId: 'abc', searchResult: result },
 })
 expect(wrapper.text).toContain(FALLBACK_TEXT)
 })
 it('f: searchResult.layers 不含 L3 → fallback', => {
 const result: PlaygroundSearchResponse = {
 query: 'test',
 repository_ids: ['r1'],
 layers: [
 {
 layer: 'L1',
 status: 'ok',
 result_count: 0,
 items:,
 error: null,
 extra: null,
 },
 ],
 final_context: '',
 total_tokens: 0,
 }
 const wrapper = mount(CodePreviewDrawer, {
 props: { open: true, chunkId: 'abc', searchResult: result },
 })
 expect(wrapper.text).toContain(FALLBACK_TEXT)
 })
 it('g: hop2 chunkId（L3 items 不含）→ fallback', => {
 const result = makeSearchResultWithChunk({
 chunk_id: 'l3-chunk',
 file_path: 'a/b.py',
 line_start: 1,
 line_end: 10,
 content: 'def foo: pass',
 })
 const wrapper = mount(CodePreviewDrawer, {
 props: {
 open: true,
 chunkId: 'hop2-chunk-id-not-in-L3',
 searchResult: result,
 },
 })
 expect(wrapper.text).toContain(FALLBACK_TEXT)
 })
 it('h: v-model:open 双向绑定：Sheet 内部触发 update:open=false → 父组件接收事件', async => {
 const wrapper = mount(CodePreviewDrawer, {
 props: { open: true, chunkId: null, searchResult: null },
 })
 // 模拟 reka-ui Sheet 内部 Esc / overlay click 路径 → 触发 update:open
 await wrapper.find('.sheet-close-trigger').trigger('click')
 expect(wrapper.emitted('update:open')).toBeTruthy
 expect(wrapper.emitted('update:open')?.[0]).toEqual([false])
 })
 it('i: 命中 chunk 但 line_start/end 全 null → header 仅显示 file_path（不含:?-?）', => {
 const result = makeSearchResultWithChunk({
 chunk_id: 'abc',
 file_path: 'a/b.py',
 line_start: null,
 line_end: null,
 content: 'code',
 })
 const wrapper = mount(CodePreviewDrawer, {
 props: { open: true, chunkId: 'abc', searchResult: result },
 })
 const text = wrapper.text
 expect(text).toContain('a/b.py')
 expect(text).not.toContain('a/b.py:?-?')
 })
})
