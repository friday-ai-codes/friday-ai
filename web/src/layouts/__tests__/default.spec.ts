/**
 * UAT 第 3 项 hotfix— default.vue ChatHeader 接线 vitest
 *
 * 背景：原 default.vue:84 裸挂载 <ChatHeader />，pin 全链路在 chat 路径下断链。
 *
 * 验证目标（接线契约）：
 * - chat 模式下 ChatHeader 接收完整 props（隐式由 mount 成功 + 模板编译通过）
 * - ChatHeader emit 'pin-confirmed' → chatStore.patchConversationCredential 被调用
 * 且参数 = emit 的 credentialId
 *
 * Mock 策略：
 * - useAppMode：顶层 vi.mock 强制 mode='chat' 让 v-else（chat 分支）渲染
 * - useRunnerMonitor：避免真实 WebSocket 连接副作用
 * - vue-router：useRoute.path='/' 让 displayMode === 'chat'；mock useRouter 防 push 报错
 * - ChatHeader：用 emit 友好的 stub 模拟 pin-confirmed 触发
 * - 其他子组件：true stub 截掉，避免 Provider 下拉 / Tooltip 链式渲染
 */
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import DefaultLayout from '~/layouts/default.vue'
import { useChatStore } from '~/stores/chat'
vi.mock('~/composables/useAppMode', => ({
 useAppMode: => ({
 mode: ref('chat'),
 chatInitialized: ref(true),
 setMode: vi.fn,
 }),
}))
vi.mock('~/composables/useRunnerMonitor', => ({
 useRunnerMonitor: => ({ connect: vi.fn }),
}))
vi.mock('vue-router', => ({
 useRoute: => ({ path: '/', meta: {} }),
 useRouter: => ({ push: vi.fn }),
 RouterView: { name: 'RouterView', render: => null },
}))
const ChatHeaderStub = defineComponent({
 name: 'ChatHeader',
 emits: ['pin-confirmed'],
 setup(_, { emit }) {
 return =>
 h(
 'button',
 {
 'data-test': 'fire-pin',
 'onClick': => emit('pin-confirmed', 'cred-new-uuid'),
 },
 'fire',
 )
 },
})
describe('default.vue layout — UAT 第 3 项 ChatHeader 接线', => {
 beforeEach( => {
 setActivePinia(createPinia)
 })
 afterEach( => {
 vi.clearAllMocks
 })
 it('chat 模式下 ChatHeader emit pin-confirmed → chatStore.patchConversationCredential 被以 credentialId 调用', async => {
 const chatStore = useChatStore
 const spy = vi
 .spyOn(chatStore, 'patchConversationCredential')
 .mockResolvedValue({} as never)
 const wrapper = mount(DefaultLayout, {
 global: {
 stubs: {
 ChatHeader: ChatHeaderStub,
 ChatInput: true,
 ChatMessageArea: true,
 AppSidebar: true,
 SystemHealthPopover: true,
 Toaster: true,
 RouterView: true,
 Transition: false,
 },
 },
 })
 await nextTick
 const fireBtn = wrapper.find('[data-test="fire-pin"]')
 expect(fireBtn.exists).toBe(true)
 await fireBtn.trigger('click')
 await nextTick
 expect(spy).toHaveBeenCalledTimes(1)
 expect(spy).toHaveBeenCalledWith('cred-new-uuid')
 wrapper.unmount
 })
})
