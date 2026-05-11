/**
 * Phase Plan — SymbolNode 单测
 * 验证：自定义 Vue Flow 节点正确渲染 name 和 symbol_type
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SymbolNode from '../SymbolNode.vue'
vi.mock('@vue-flow/core', => ({
 Handle: { template: '<div class="handle-stub" />', props: ['type', 'position'] },
 Position: { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' },
}))
vi.mock('~/components/ui/badge', => ({
 Badge: { template: '<span class="badge-stub"><slot /></span>', props: ['variant'] },
}))
vi.mock('~/components/ui/tooltip', => ({
 Tooltip: { template: '<div><slot /></div>' },
 TooltipTrigger: { template: '<div><slot /></div>' },
 TooltipContent: { template: '<div><slot /></div>' },
 TooltipProvider: { template: '<div><slot /></div>' },
}))
describe('SymbolNode', => {
 const defaultData = {
 name: 'myFunc',
 symbol_type: 'FUNCTION',
 file_path: 'src/a.py',
 line_start: 1,
 line_end: 10,
 signature: 'def myFunc',
 }
 it('A: 渲染 data.name 文本', => {
 const wrapper = mount(SymbolNode, {
 props: { data: defaultData },
 })
 expect(wrapper.text).toContain('myFunc')
 })
 it('B: 渲染 data.symbol_type 徽章文本', => {
 const wrapper = mount(SymbolNode, {
 props: { data: defaultData },
 })
 expect(wrapper.text).toContain('FUNCTION')
 })
 it('C: 渲染签名文本', => {
 const wrapper = mount(SymbolNode, {
 props: { data: defaultData },
 })
 expect(wrapper.text).toContain('def myFunc')
 })
 it('D: 外壳包含 w-[240px] 宽度类', => {
 const wrapper = mount(SymbolNode, {
 props: { data: defaultData },
 })
 expect(wrapper.html).toContain('w-[240px]')
 })
})
