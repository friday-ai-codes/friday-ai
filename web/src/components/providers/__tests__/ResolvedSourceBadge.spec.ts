/**
 * Phase Plan Task 2 — ResolvedSourceBadge 组件测试。
 *
 * 覆盖 / 契约：
 * A: source="node" → hue icon lucide--layers + text-violet-600 + 标签 "节点配置"
 * B: source="conversation" → icon lucide--message-circle + text-blue-600 + "对话固定"
 * C: source="project" → icon lucide--folder-lock + text-teal-600 + "项目覆盖"
 * D: source="system" → icon lucide--globe + text-slate-500 + "系统默认"
 * E: tooltip 展开完整链表（wrapper.html 承载），winning 层含 ✓，被覆盖层 line-through
 * F: Badge 本身 variant="outline"（work item §Dimension 3 硬锁 — hue 仅 icon，Badge 不叠色）
 *
 * Analog: ProviderHealthBadge.spec（同目录，Phase）+ Plan 三重承载模式（title / aria-label）。
 */
import type { ChainEntry, SourceLayer } from '~/types/providerCredential'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ResolvedSourceBadge from '~/components/providers/ResolvedSourceBadge.vue'
function makeChain(winning: SourceLayer): ChainEntry {
 return [
 {
 layer: 'node',
 provider_type: winning === 'node' ? 'anthropic': null,
 model: null,
 credential_id: winning === 'node' ? 'cred-node': null,
 active: winning === 'node',
 },
 {
 layer: 'conversation',
 provider_type: winning === 'conversation' ? 'anthropic': null,
 model: null,
 credential_id: winning === 'conversation' ? 'cred-conv': null,
 active: winning === 'conversation',
 },
 {
 layer: 'project',
 provider_type: winning === 'project' ? 'anthropic': null,
 model: null,
 credential_id: winning === 'project' ? 'cred-proj': null,
 active: winning === 'project',
 },
 {
 layer: 'system',
 provider_type: winning === 'system' ? 'anthropic': null,
 model: null,
 credential_id: winning === 'system' ? 'cred-sys': null,
 active: winning === 'system',
 },
 ]
}
describe('resolvedSourceBadge', => {
 it('A: source="node" → 渲染 "节点配置" 标签 + violet hue icon', => {
 const wrapper = mount(ResolvedSourceBadge, {
 props: { source: 'node', chain: makeChain('node') },
 })
 const html = wrapper.html
 expect(html).toContain('节点配置')
 expect(html).toContain('icon-[lucide--layers]')
 expect(html).toContain('text-violet-600')
 })
 it('B: source="conversation" → 渲染 "对话固定" + blue hue icon', => {
 const wrapper = mount(ResolvedSourceBadge, {
 props: { source: 'conversation', chain: makeChain('conversation') },
 })
 const html = wrapper.html
 expect(html).toContain('对话固定')
 expect(html).toContain('icon-[lucide--message-circle]')
 expect(html).toContain('text-blue-600')
 })
 it('C: source="project" → 渲染 "项目覆盖" + teal hue icon', => {
 const wrapper = mount(ResolvedSourceBadge, {
 props: { source: 'project', chain: makeChain('project') },
 })
 const html = wrapper.html
 expect(html).toContain('项目覆盖')
 expect(html).toContain('icon-[lucide--folder-lock]')
 expect(html).toContain('text-teal-600')
 })
 it('D: source="system" → 渲染 "系统默认" + slate hue icon', => {
 const wrapper = mount(ResolvedSourceBadge, {
 props: { source: 'system', chain: makeChain('system') },
 })
 const html = wrapper.html
 expect(html).toContain('系统默认')
 expect(html).toContain('icon-[lucide--globe]')
 expect(html).toContain('text-slate-500')
 })
 it('E: chain 展开含 4 层中文标签；winning 层含 ✓；被覆盖层 line-through（html 断言）', => {
 // 造一个 conversation 赢 + project 有值但被覆盖的 chain
 const chain: ChainEntry = [
 { layer: 'node', provider_type: null, model: null, credential_id: null, active: false },
 {
 layer: 'conversation',
 provider_type: 'anthropic',
 model: null,
 credential_id: 'cred-conv',
 active: true,
 },
 {
 layer: 'project',
 provider_type: 'anthropic',
 model: null,
 credential_id: 'cred-proj',
 active: false,
 },
 { layer: 'system', provider_type: null, model: null, credential_id: null, active: false },
 ]
 const wrapper = mount(ResolvedSourceBadge, {
 props: { source: 'conversation', chain },
 })
 const html = wrapper.html
 // 四个中文 label 均出现（tooltip + main 共享 labelMap）
 expect(html).toContain('节点配置')
 expect(html).toContain('对话固定')
 expect(html).toContain('项目覆盖')
 expect(html).toContain('系统默认')
 // winning 层 ✓（lucide--check）存在
 expect(html).toContain('icon-[lucide--check]')
 // project 层虽存在值但未赢 → line-through
 expect(html).toContain('line-through')
 })
 it('F: Badge 本身使用 variant="outline"（work item §Dimension 3 锁定 hue 仅 icon）', => {
 const wrapper = mount(ResolvedSourceBadge, {
 props: { source: 'node', chain: makeChain('node') },
 })
 const html = wrapper.html
 // outline variant 渲染出 text-foreground（主 Badge 非 success/destructive hue）
 // 反证：不应出现非 outline 的色块（emerald/destructive 背景）
 expect(html).not.toContain('bg-emerald-500/10')
 expect(html).not.toContain('bg-destructive')
 // 组件不使用 backdrop-blur（Clean Card 纠偏）
 expect(html).not.toContain('backdrop-blur')
 })
})
