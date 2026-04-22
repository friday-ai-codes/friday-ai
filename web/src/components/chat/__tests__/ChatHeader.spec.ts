/**
 * Phase Plan Task 02 — ChatHeader frozen / active / WAITING 态测试
 *
 * 覆盖 Behaviors G / H + useConversationFrozen 单测 A/B/C：
 * - G: ChatHeader 渲染 frozen 对话 → Provider 下拉 disabled 属性为 true
 * - H: ChatHeader 渲染 active 对话 → 默认不打开 pin 弹窗
 * - useConversationFrozen 三态判定
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { computed, nextTick, ref } from 'vue'
import ChatHeader from '~/components/chat/ChatHeader.vue'
import { useConversationFrozen } from '~/composables/useConversationFrozen'
import { useProviderCredentialStore } from '~/stores/providerCredential'
function cleanupBody {
 document.body.innerHTML = ''
}
describe('useConversationFrozen', => {
 it('A: status=completed → isFrozen=true, reason 含 "已完成"', => {
 const status = ref<'completed'>('completed')
 const waiting = ref(false)
 const frozen = useConversationFrozen(status, waiting)
 expect(frozen.value.isFrozen).toBe(true)
 expect(frozen.value.reason).toContain('已完成')
 })
 it('B: status=running + waitingForInput=true → isFrozen=true, reason 含 "等待输入"', => {
 const status = ref<'running'>('running')
 const waiting = ref(true)
 const frozen = useConversationFrozen(status, waiting)
 expect(frozen.value.isFrozen).toBe(true)
 expect(frozen.value.reason).toContain('等待输入')
 })
 it('C: status=running + waitingForInput=false → isFrozen=false, reason=""', => {
 const status = ref<'running'>('running')
 const waiting = ref(false)
 const frozen = useConversationFrozen(status, waiting)
 expect(frozen.value.isFrozen).toBe(false)
 expect(frozen.value.reason).toBe('')
 })
 it('status=stopped / error 同样 frozen', => {
 const status = ref<'stopped' | 'error'>('stopped')
 const frozen = useConversationFrozen(status, ref(false))
 expect(frozen.value.isFrozen).toBe(true)
 status.value = 'error'
 expect(frozen.value.isFrozen).toBe(true)
 expect(frozen.value.reason).toContain('异常')
 })
 it('status=draft → isFrozen=false', => {
 const status = ref<'draft'>('draft')
 const frozen = useConversationFrozen(status, ref(false))
 expect(frozen.value.isFrozen).toBe(false)
 })
 it('响应式：status 从 running 切到 completed 后立即 frozen', async => {
 const status = ref<'running' | 'completed'>('running')
 const frozen = useConversationFrozen(status, ref(false))
 const tracker = computed( => frozen.value.isFrozen)
 expect(tracker.value).toBe(false)
 status.value = 'completed'
 await nextTick
 expect(tracker.value).toBe(true)
 })
})
describe('chatHeader (Phase)', => {
 beforeEach( => {
 setActivePinia(createPinia)
 })
 afterEach(cleanupBody)
 it('G: frozen(completed) 对话渲染后 Provider 下拉区块标记为 frozen', async => {
 const wrapper = mount(ChatHeader, {
 props: {
 conversationStatus: 'completed',
 currentCredentialId: null,
 currentModel: '',
 messageCount: 3,
 conversationId: 'conv-1',
 waitingForInput: false,
 },
 attachTo: document.body,
 global: { stubs: { ProviderCredentialDropdown: true, PinConfirmDialog: true } },
 })
 await nextTick
 const frozenWrapper = wrapper.find('[data-frozen="true"]')
 expect(frozenWrapper.exists).toBe(true)
 wrapper.unmount
 })
 it('H: active(running) 对话默认不打开 pin 弹窗', async => {
 const wrapper = mount(ChatHeader, {
 props: {
 conversationStatus: 'running',
 currentCredentialId: 'cred-old',
 currentModel: 'claude-3-5',
 messageCount: 5,
 conversationId: 'conv-1',
 waitingForInput: false,
 },
 attachTo: document.body,
 global: { stubs: { ProviderCredentialDropdown: true, PinConfirmDialog: true } },
 })
 await nextTick
 // frozen 属性应为 false
 const frozenWrapper = wrapper.find('[data-frozen="false"]')
 expect(frozenWrapper.exists).toBe(true)
 wrapper.unmount
 })
 it('WAITING 态（waitingForInput=true）即使 running 也标记 frozen', async => {
 const wrapper = mount(ChatHeader, {
 props: {
 conversationStatus: 'running',
 currentCredentialId: null,
 currentModel: '',
 messageCount: 0,
 conversationId: 'conv-1',
 waitingForInput: true,
 },
 attachTo: document.body,
 global: { stubs: { ProviderCredentialDropdown: true, PinConfirmDialog: true } },
 })
 await nextTick
 const frozenWrapper = wrapper.find('[data-frozen="true"]')
 expect(frozenWrapper.exists).toBe(true)
 wrapper.unmount
 })
 // ==========================================================================
 // Phase Plan：ChatHeader.oldCredential watch(immediate) 赋值（230 修复）
 //
 // 修复前：oldCredential ref 声明但从不赋值 → PinConfirmDialog 恒显示占位文案 "当前 Provider"。
 // 修复后：watch( => props.currentCredentialId, { immediate: true }) +
 // providerStore.getCredentialById 同步赋值 → PinConfirmDialog 收到真实 name。
 // 降级链保留（模板 L189 fallback）：store 未 load → '当前 Provider'；currentCredentialId null → '未指定'。
 // ==========================================================================
 it('I: props.currentCredentialId 命中 store 时，oldCredential 应被赋值（渲染真实 Provider 名）', async => {
 setActivePinia(createPinia)
 const store = useProviderCredentialStore
 // 直接写 store.credentials —— 跳过 fetch（fetchCredentials 含 30s TTL，且本用例不依赖 API）
 store.credentials = [
 {
 id: 'cred-42',
 provider_type: 'anthropic',
 name: 'my-anth-prod',
 scope: 'system',
 scope_id: null,
 is_active: true,
 last_health_check_at: null,
 last_health_check_status: '',
 last_health_check_error: '',
 available_models:,
 api_key_last4: '',
 has_api_key: true,
 created_at: '2026-04-22T00:00:00Z',
 updated_at: '2026-04-22T00:00:00Z',
 },
 ]
 const wrapper = mount(ChatHeader, {
 props: {
 conversationStatus: 'running',
 currentCredentialId: 'cred-42',
 currentModel: 'claude-3-5',
 messageCount: 1,
 conversationId: 'conv-1',
 waitingForInput: false,
 },
 attachTo: document.body,
 global: {
 stubs: {
 ProviderCredentialDropdown: true,
 PinConfirmDialog: {
 props: ['oldProviderName'],
 template: '<div data-test="pin-dialog":data-old-name="oldProviderName" />',
 },
 },
 },
 })
 await nextTick
 await flushPromises
 const el = wrapper.find('[data-test="pin-dialog"]')
 expect(el.exists).toBe(true)
 expect(el.attributes('data-old-name')).toBe('my-anth-prod')
 wrapper.unmount
 })
 it('J: store 未 load 时，fallback 到"当前 Provider"占位文案', async => {
 setActivePinia(createPinia)
 // credentials 保持空 → getCredentialById 返 null → 模板 fallback
 const wrapper = mount(ChatHeader, {
 props: {
 conversationStatus: 'running',
 currentCredentialId: 'cred-missing',
 currentModel: '',
 messageCount: 0,
 conversationId: 'conv-1',
 waitingForInput: false,
 },
 attachTo: document.body,
 global: {
 stubs: {
 ProviderCredentialDropdown: true,
 PinConfirmDialog: {
 props: ['oldProviderName'],
 template: '<div data-test="pin-dialog":data-old-name="oldProviderName" />',
 },
 },
 },
 })
 await nextTick
 const el = wrapper.find('[data-test="pin-dialog"]')
 expect(el.attributes('data-old-name')).toBe('当前 Provider')
 wrapper.unmount
 })
})
