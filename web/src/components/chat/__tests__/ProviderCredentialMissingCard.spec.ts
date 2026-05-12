/**
 * Phase Plan Task 02 — ProviderCredentialMissingCard 组件测试。
 *
 * 覆盖 按角色分流 CTA：
 * A: system_admin → 主按钮 "去系统设置"（primary）
 * B: member → 主按钮 "去空间设置"（primary） + 次按钮 "去系统设置" disabled + tooltip
 * C: viewer → 同 B
 * D: 主 RouterLink `to` 指向正确路径（system_admin → /admin/providers；其他 → /projects/{id}/settings#providers）
 *
 * Analog: ProviderHealthBadge.spec.ts（Phase）+ PATTERNS §Pattern 1 。
 * 使用 RouterLink stub（不挂 vue-router 实例）：v-slot 透传 href 属性方便断言。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ProviderCredentialMissingCard from '~/components/chat/ProviderCredentialMissingCard.vue'
/** RouterLink stub：把 `to` 写到 data-to 属性便于断言。 */
const RouterLinkStub = {
 name: 'RouterLink',
 props: ['to'],
 template: '<a:data-to="to"><slot /></a>',
}
function makeProps(overrides: Record<string, unknown> = {}) {
 return {
 missingProvider: 'anthropic' as const,
 userRole: 'system_admin' as const,
 spaceId: 'proj-abc-123',
 ...overrides,
 }
}
describe('providerCredentialMissingCard', => {
 it('a: system_admin 角色渲染 "去系统设置" primary + "去空间设置" secondary（均可点击）', => {
 const wrapper = mount(ProviderCredentialMissingCard, {
 props: makeProps({ userRole: 'system_admin' }),
 global: { stubs: { RouterLink: RouterLinkStub } },
 })
 const text = wrapper.text
 expect(text).toContain('未配置')
 expect(text).toContain('Anthropic')
 expect(text).toContain('去系统设置')
 expect(text).toContain('去空间设置')
 // 两个 RouterLink：主按钮指向 /admin/providers，次按钮指向 /spaces/.../settings#providers
 const links = wrapper.findAll('a[data-to]')
 expect(links.length).toBeGreaterThanOrEqual(2)
 const tos = links.map(a => a.attributes('data-to'))
 expect(tos).toContain('/admin/providers')
 expect(tos).toContain('/spaces/proj-abc-123/settings#providers')
 // system_admin 角色不应出现 disabled 按钮
 const disabledButtons = wrapper.findAll('button[disabled]')
 expect(disabledButtons.length).toBe(0)
 })
 it('b: member 角色主按钮为 "去空间设置" + 次按钮 "去系统设置" disabled + tooltip 文案', => {
 const wrapper = mount(ProviderCredentialMissingCard, {
 props: makeProps({ userRole: 'member' }),
 global: { stubs: { RouterLink: RouterLinkStub } },
 })
 const text = wrapper.text
 expect(text).toContain('去空间设置')
 expect(text).toContain('去系统设置')
 // Tooltip 文案以 title / aria-label 属性承载（Tooltip 默认 closed 态不挂 DOM）
 const html = wrapper.html
 expect(html).toContain('需系统管理员权限')
 // 主按钮 RouterLink `to` 应为项目设置路径
 const links = wrapper.findAll('a[data-to]')
 const tos = links.map(a => a.attributes('data-to'))
 expect(tos).toContain('/spaces/proj-abc-123/settings#providers')
 // 非 system_admin 不应出现指向 /admin/providers 的 RouterLink
 expect(tos).not.toContain('/admin/providers')
 // 次按钮应 disabled（去系统设置）
 const disabledButtons = wrapper.findAll('button[disabled]')
 expect(disabledButtons.length).toBeGreaterThanOrEqual(1)
 // 被 disable 的按钮文案应为 "去系统设置"
 const disabledText = disabledButtons.map(b => b.text).join('|')
 expect(disabledText).toContain('去系统设置')
 })
 it('c: viewer 角色与 member 共享分流规则（次按钮 disabled）', => {
 const wrapper = mount(ProviderCredentialMissingCard, {
 props: makeProps({ userRole: 'viewer' }),
 global: { stubs: { RouterLink: RouterLinkStub } },
 })
 const text = wrapper.text
 expect(text).toContain('去空间设置')
 expect(text).toContain('去系统设置')
 const links = wrapper.findAll('a[data-to]')
 const tos = links.map(a => a.attributes('data-to'))
 expect(tos).toContain('/spaces/proj-abc-123/settings#providers')
 expect(tos).not.toContain('/admin/providers')
 const disabledButtons = wrapper.findAll('button[disabled]')
 expect(disabledButtons.length).toBeGreaterThanOrEqual(1)
 })
 it('d: 不同 Provider 映射到正确的中文品牌名（OpenAI / Gemini / Ollama）', => {
 for (const [provider, label] of [
 ['openai_chat', 'OpenAI'],
 ['openai_responses', 'OpenAI'],
 ['gemini', 'Gemini'],
 ['ollama', 'Ollama'],
 ] as const) {
 const wrapper = mount(ProviderCredentialMissingCard, {
 props: makeProps({ missingProvider: provider }),
 global: { stubs: { RouterLink: RouterLinkStub } },
 })
 expect(wrapper.text).toContain(label)
 }
 })
})
