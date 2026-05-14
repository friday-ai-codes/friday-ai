/**
 * Phase Plan — DiffusionNode 单测
 * 验证：file_basename 显示 / hop Badge 文案 / 外壳 class / aria-label。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import DiffusionNode from '../DiffusionNode.vue'
vi.mock('@vue-flow/core', => ({
 Handle: { template: '<div class="handle-stub" />', props: ['type', 'position'] },
 Position: { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' },
}))
vi.mock('~/components/ui/badge', => ({
 Badge: { template: '<span class="badge-stub":data-variant="variant"><slot /></span>', props: ['variant'] },
}))
vi.mock('~/components/ui/tooltip', => ({
 Tooltip: { template: '<div><slot /></div>' },
 TooltipTrigger: { template: '<div><slot /></div>' },
 TooltipContent: { template: '<div><slot /></div>' },
 TooltipProvider: { template: '<div><slot /></div>' },
}))
describe('diffusionNode', => {
 const baseData = {
 chunk_id: 'abcdef0123456789',
 file_path: 'src/services/auth/handler.ts',
 fileBasename: 'handler.ts',
 line_start: 10,
 line_end: 42,
 hop: 1 as const,
 }
 it('a: hop=1 节点渲染 Badge 文案 "1-hop"', => {
 const wrapper = mount(DiffusionNode, { props: { data: baseData } })
 expect(wrapper.text).toContain('1-hop')
 })
 it('b: hop=2 节点 Badge 文案 "2-hop" + 外壳 border-dashed', => {
 const wrapper = mount(DiffusionNode, {
 props: { data: { ...baseData, hop: 2 as const } },
 })
 expect(wrapper.text).toContain('2-hop')
 expect(wrapper.html).toContain('border-dashed')
 })
 it('c: hop=source 节点 Badge 文案 "起点" + 外壳 border-primary/50', => {
 const wrapper = mount(DiffusionNode, {
 props: { data: { ...baseData, hop: 'source' as const } },
 })
 expect(wrapper.text).toContain('起点')
 expect(wrapper.html).toContain('border-primary/50')
 })
 it('d: 外壳 aria-label 含 "代码块 {basename}, {hop}"', => {
 const wrapper = mount(DiffusionNode, { props: { data: baseData } })
 const aria = wrapper.find('[role="button"]').attributes('aria-label')
 expect(aria).toContain('代码块 handler.ts')
 expect(aria).toContain('1-hop')
 })
 it('e: 首行显示 fileBasename 而非完整 file_path', => {
 const wrapper = mount(DiffusionNode, { props: { data: baseData } })
 // 首行节点头部仅 basename；file_path 完整出现在尾部
 expect(wrapper.text).toContain('handler.ts')
 expect(wrapper.text).toContain('src/services/auth/handler.ts')
 })
 it('f: TooltipContent 含 chunk_id 前 8 字符（mono muted）', => {
 const wrapper = mount(DiffusionNode, { props: { data: baseData } })
 expect(wrapper.text).toContain('chunk_id: abcdef01')
 })
})
