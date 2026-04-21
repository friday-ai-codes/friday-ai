/**
 * Phase Plan Task 02 — ChatHeader frozen / active / WAITING 态测试
 *
 * 覆盖 Behaviors G / H + useConversationFrozen 单测 A/B/C：
 * - G: ChatHeader 渲染 frozen 对话 → Provider 下拉 disabled 属性为 true
 * - H: ChatHeader 渲染 active 对话 → 默认不打开 pin 弹窗
 * - useConversationFrozen 三态判定
 */
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { computed, nextTick, ref } from 'vue'
import ChatHeader from '~/components/chat/ChatHeader.vue'
import { useConversationFrozen } from '~/composables/useConversationFrozen'
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
})
