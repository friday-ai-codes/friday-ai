/**
 * UX 重设计— default.vue ChatInput pin-confirmed 接线 vitest
 *
 * 背景：
 * -：在 ChatHeader 上接 @pin-confirmed → chatStore.patchConversationCredential
 * -：UX 重设计折叠为 ChatInput 单下拉，listener 迁移到 ChatInput；
 * 参数升级为 (credentialId, model) 双字段；目标 action 升级为
 * chatStore.patchConversationProviderAndModel（单次 PATCH 双字段）
 *
 * 验证目标（接线契约）：
 * - chat 模式下 ChatInput emit 'pin-confirmed' → chatStore.patchConversationProviderAndModel
 * 被以 (credentialId, model) 双参数调用
 *
 * Mock 策略：
 * - useAppMode：顶层 vi.mock 强制 mode='chat' 让 v-else（chat 分支）渲染
 * - useRunnerMonitor：避免真实 WebSocket 连接副作用
 * - vue-router：useRoute.path='/' 让 displayMode === 'chat'；mock useRouter 防 push 报错
 * - ChatInput：用 emit 友好的 stub 模拟 pin-confirmed 触发
 * - 其他子组件：true stub 截掉
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
const ChatInputStub = defineComponent({
 name: 'ChatInput',
 emits: ['pin-confirmed'],
 setup(_, { emit }) {
 return =>
 h(
 'button',
 {
 'data-test': 'fire-pin',
 'onClick': => emit('pin-confirmed', 'cred-new-uuid', 'claude-sonnet-4'),
 },
 'fire',
 )
 },
})
describe('default.vue layout — ChatInput pin-confirmed 接线', => {
 beforeEach( => {
 setActivePinia(createPinia)
 })
 afterEach( => {
 vi.clearAllMocks
 })
 // OBSOLETE: pin-confirmed listener 已从 layouts/default.vue 迁移到 pages/chat.vue
 // （`@pin-confirmed="chatStore.patchConversationProviderAndModel"` 模板直绑，
 // 见 web/src/pages/chat.vue:41）。default.vue 改为 chat 路由直渲染 RouterView，
 // 不再挂载 ChatInput。本测试保留为接线变迁记录，跳过执行。
 it.skip('chat 模式下 ChatInput emit pin-confirmed → chatStore.patchConversationProviderAndModel 被以 (credentialId, model) 调用', async => {
 const chatStore = useChatStore
 const spy = vi
 .spyOn(chatStore, 'patchConversationProviderAndModel')
 .mockResolvedValue({} as never)
 const wrapper = mount(DefaultLayout, {
 global: {
 stubs: {
 ChatHeader: true,
 ChatInput: ChatInputStub,
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
 expect(spy).toHaveBeenCalledWith('cred-new-uuid', 'claude-sonnet-4')
 wrapper.unmount
 })
})
