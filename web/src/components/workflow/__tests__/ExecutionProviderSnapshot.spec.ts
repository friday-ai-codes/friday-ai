/**
 * Phase Plan Task 2 — ExecutionProviderSnapshot 组件测试。
 *
 * 覆盖 详情页快照展示契约：
 * A: snapshot 有值 → 折叠态渲染 provider 中文名 + model + "Provider 快照" 标题
 * B: snapshot = null → 显示 "未快照" Badge + 说明文案；Replay 按钮 disabled
 * C: snapshot 有值 + canReplay=true → Replay 按钮可点击，点击触发 replay emit
 * D: snapshot = null → Replay disabled + tooltip 文案（title/aria-label 承载）
 *
 * Analog: ProviderCredentialMissingCard.spec.ts（Phase Plan）+
 * Pattern 2 （ExecutionProviderSnapshot analog）。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ExecutionProviderSnapshot from '~/components/workflow/execution/ExecutionProviderSnapshot.vue'
interface NodeSnapshot {
 provider_type: 'anthropic' | 'openai_responses' | 'openai_chat' | 'gemini' | 'ollama'
 model: string
 source: 'node' | 'conversation' | 'project' | 'system'
 credential_id: string | null
}
function makeSnap(overrides: Partial<NodeSnapshot> = {}): NodeSnapshot {
 return {
 provider_type: 'anthropic',
 model: 'claude-3-5-sonnet-20241022',
 source: 'project',
 credential_id: 'cred-123',
 ...overrides,
 }
}
describe('executionProviderSnapshot', => {
 it('a: snapshot 有值 → 折叠态显示 "Provider 快照" 标题 + provider 中文名 + model', => {
 const wrapper = mount(ExecutionProviderSnapshot, {
 props: {
 nodeId: 'node-a1',
 snapshot: makeSnap({ provider_type: 'anthropic', model: 'claude-3-5-sonnet-20241022' }),
 canReplay: true,
 },
 })
 const text = wrapper.text
 expect(text).toContain('Provider 快照')
 expect(text).toContain('Anthropic')
 expect(text).toContain('claude-3-5-sonnet-20241022')
 // 折叠态不应提前渲染 "未快照" Badge
 expect(text).not.toContain('未快照')
 })
 it('b: snapshot = null → 渲染 "未快照" Badge + 说明文案', => {
 const wrapper = mount(ExecutionProviderSnapshot, {
 props: {
 nodeId: 'node-b1',
 snapshot: null,
 canReplay: true,
 },
 })
 const text = wrapper.text
 expect(text).toContain('未快照')
 expect(text).toContain('本节点未记录 Provider 快照')
 // Replay 按钮 disabled（snapshot=null 时无法稳定 Replay）
 const disabledButtons = wrapper.findAll('button[disabled]')
 expect(disabledButtons.length).toBeGreaterThanOrEqual(1)
 })
 it('c: snapshot + canReplay=true → Replay 按钮可点击且点击触发 replay emit', async => {
 const wrapper = mount(ExecutionProviderSnapshot, {
 props: {
 nodeId: 'node-c1',
 snapshot: makeSnap,
 canReplay: true,
 },
 })
 // 找到 Replay 按钮（文案 "使用此快照重放"）
 const replayButtons = wrapper.findAll('button').filter(
 btn => btn.text.includes('使用此快照重放'),
 )
 expect(replayButtons.length).toBe(1)
 const replayBtn = replayButtons[0]
 expect(replayBtn.attributes('disabled')).toBeUndefined
 await replayBtn.trigger('click')
 expect(wrapper.emitted).toHaveProperty('replay')
 expect(wrapper.emitted.replay).toHaveLength(1)
 })
 it('d: snapshot = null → Replay disabled + tooltip 文案 "历史 Execution 未记录快照"（title/aria-label 承载）', => {
 const wrapper = mount(ExecutionProviderSnapshot, {
 props: {
 nodeId: 'node-d1',
 snapshot: null,
 canReplay: true,
 },
 })
 // happy-dom 下 TooltipContent Portal 默认不挂载；tooltip 文案通过
 // title / aria-label / wrapper.html 承载（与 Plan 一致的 模式）
 const html = wrapper.html
 expect(html).toContain('历史 Execution 未记录快照')
 const disabledButtons = wrapper.findAll('button[disabled]')
 expect(disabledButtons.length).toBeGreaterThanOrEqual(1)
 // 禁用按钮文案包含 "使用此快照重放"
 const disabledTexts = disabledButtons.map(b => b.text).join('|')
 expect(disabledTexts).toContain('使用此快照重放')
 })
 it('e: 不同 Provider 映射到正确的中文品牌名', => {
 for (const [provider, label] of [
 ['anthropic', 'Anthropic'],
 ['openai_responses', 'OpenAI'],
 ['openai_chat', 'OpenAI'],
 ['gemini', 'Gemini'],
 ['ollama', 'Ollama'],
 ] as const) {
 const wrapper = mount(ExecutionProviderSnapshot, {
 props: {
 nodeId: `node-${provider}`,
 snapshot: makeSnap({ provider_type: provider }),
 canReplay: false,
 },
 })
 expect(wrapper.text).toContain(label)
 }
 })
})
