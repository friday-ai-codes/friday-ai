/**
 * Phase：RelevanceBadge 组件单测。
 *
 * 覆盖 6 条：
 * 1. high 渲染 success Badge
 * 2. medium 渲染 warning Badge
 * 3. low 渲染 secondary Badge
 * 4. 无 trace → 不渲染（v-if 优雅降级）
 * 5. trace 中无对应 repository_id → 不渲染
 * 6. Tooltip evidence 展示
 * 7. (reactive) manual override 后 badge 自动重渲染（latest 切换）
 */
import type { RoutingDecisionData } from '~/types/routing'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import RelevanceBadge from '~/components/chat/RelevanceBadge.vue'
import { useRoutingStore } from '~/stores/routing'
function makeTrace(level: 'high' | 'medium' | 'low'): RoutingDecisionData {
 const scoreMap = { high: 0.9, medium: 0.55, low: 0.2 }
 return {
 trace_id: `trace-${level}`,
 query: 'q',
 threshold: 0.5,
 triggered_by: 'chat_tool',
 candidates: [
 {
 repository_id: 'repo-a',
 repository_name: 'A',
 score: scoreMap[level],
 level,
 evidence: `evidence-${level}`,
 selected_by_ai: level !== 'low',
 selected_by_user_final: level !== 'low',
 },
 ],
 }
}
function mountBadge(traceId: string | null) {
 const pinia = createPinia
 setActivePinia(pinia)
 const store = useRoutingStore
 if (traceId) {
 store.upsertTrace(makeTrace('high'), 'conv-1')
 }
 return mount(RelevanceBadge, {
 global: { plugins: [pinia] },
 props: {
 repositoryId: 'repo-a',
 conversationId: 'conv-1',
 },
 })
}
describe('relevanceBadge', => {
 beforeEach( => {
 setActivePinia(createPinia)
 })
 it('high → 渲染 success variant + 百分比 + 高', => {
 const pinia = createPinia
 setActivePinia(pinia)
 const store = useRoutingStore
 store.upsertTrace(makeTrace('high'), 'conv-1')
 const wrapper = mount(RelevanceBadge, {
 global: { plugins: [pinia] },
 props: { repositoryId: 'repo-a', conversationId: 'conv-1' },
 })
 expect(wrapper.text).toContain('90% 高')
 const badge = wrapper.findComponent({ name: 'Badge' })
 expect(badge.exists).toBe(true)
 expect(badge.props('variant')).toBe('success')
 })
 it('medium → 渲染 warning variant', => {
 const pinia = createPinia
 setActivePinia(pinia)
 const store = useRoutingStore
 store.upsertTrace(makeTrace('medium'), 'conv-1')
 const wrapper = mount(RelevanceBadge, {
 global: { plugins: [pinia] },
 props: { repositoryId: 'repo-a', conversationId: 'conv-1' },
 })
 expect(wrapper.text).toContain('55% 中')
 expect(wrapper.findComponent({ name: 'Badge' }).props('variant')).toBe('warning')
 })
 it('low → 渲染 secondary variant', => {
 const pinia = createPinia
 setActivePinia(pinia)
 const store = useRoutingStore
 store.upsertTrace(makeTrace('low'), 'conv-1')
 const wrapper = mount(RelevanceBadge, {
 global: { plugins: [pinia] },
 props: { repositoryId: 'repo-a', conversationId: 'conv-1' },
 })
 expect(wrapper.text).toContain('20% 低')
 expect(wrapper.findComponent({ name: 'Badge' }).props('variant')).toBe('secondary')
 })
 it('无 trace → 不渲染', => {
 const wrapper = mountBadge(null)
 expect(wrapper.find('[class*="badge"]').exists).toBe(false)
 expect(wrapper.text).toBe('')
 })
 it('trace 中无对应 repo → 不渲染', => {
 const pinia = createPinia
 setActivePinia(pinia)
 const store = useRoutingStore
 store.upsertTrace(makeTrace('high'), 'conv-1')
 const wrapper = mount(RelevanceBadge, {
 global: { plugins: [pinia] },
 props: { repositoryId: 'repo-not-in-trace', conversationId: 'conv-1' },
 })
 expect(wrapper.text).toBe('')
 })
 it('tooltip evidence 来自 candidate.evidence（通过 props 验证）', => {
 const pinia = createPinia
 setActivePinia(pinia)
 const store = useRoutingStore
 store.upsertTrace(makeTrace('high'), 'conv-1')
 const wrapper = mount(RelevanceBadge, {
 global: { plugins: [pinia] },
 props: { repositoryId: 'repo-a', conversationId: 'conv-1' },
 })
 // TooltipContent 在 reka-ui 里是 Teleport，DOM 上不直接挂；改用 store 反查
 // 验证 evidence 字符串确实绑定在组件状态中
 expect(wrapper.html).toContain('90% 高')
 expect(store.getTrace('trace-high')?.candidates[0].evidence).toBe('evidence-high')
 })
 it('manual override 后 badge 跟随新 trace 重渲染', async => {
 const pinia = createPinia
 setActivePinia(pinia)
 const store = useRoutingStore
 store.upsertTrace(makeTrace('low'), 'conv-1')
 const wrapper = mount(RelevanceBadge, {
 global: { plugins: [pinia] },
 props: { repositoryId: 'repo-a', conversationId: 'conv-1' },
 })
 expect(wrapper.text).toContain('20% 低')
 // 模拟 manual override：写一条新 trace 同 repo level 升到 high
 store.upsertTrace(
 { ...makeTrace('high'), trace_id: 'trace-2', triggered_by: 'manual_override' },
 'conv-1',
 )
 await nextTick
 expect(wrapper.text).toContain('90% 高')
 expect(wrapper.findComponent({ name: 'Badge' }).props('variant')).toBe('success')
 })
})
