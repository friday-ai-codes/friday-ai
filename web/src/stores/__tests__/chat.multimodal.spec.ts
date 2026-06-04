import type { MessagePart } from '~/types/chat'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { connectSSE } from '~/composables/useSSEStream'
import { useChatStore } from '~/stores/chat'
vi.mock('~/composables/useSSEStream', => ({
 connectSSE: vi.fn(async => {}),
 getCurrentRunId: vi.fn( => null),
}))
describe('chat store multimodal sendMessage', => {
 beforeEach( => {
 Object.defineProperty(window, 'localStorage', {
 value: {
 getItem: vi.fn( => null),
 setItem: vi.fn,
 removeItem: vi.fn,
 clear: vi.fn,
 },
 configurable: true,
 })
 setActivePinia(createPinia)
 vi.mocked(connectSSE).mockReset
 vi.mocked(connectSSE).mockResolvedValue(undefined)
 })
 it('optimistically renders text plus image parts and passes inputParts to SSE', async => {
 const imagePart: MessagePart = {
 type: 'image',
 id: 'p_img',
 index: 0,
 mime_type: 'image/png',
 size_bytes: 68,
 storage_ref: 'chat_images/pixel.png',
 detail: 'auto',
 }
 const store = useChatStore
 store.currentConversationId = 'conv-existing'
 await store.sendMessage('请看这里', undefined, [imagePart])
 expect(store.messages[0]).toMatchObject({
 role: 'user',
 content: '请看这里',
 })
 expect(store.messages[0].parts?.map(p => p.type)).toEqual(['text', 'image'])
 expect(store.messages[0].parts?.[1]).toMatchObject({ type: 'image', index: 1 })
 expect(connectSSE).toHaveBeenCalledWith(
 'conv-existing',
 '请看这里',
 store.selectedRole,
 expect.any(Function),
 expect.any(AbortSignal),
 expect.objectContaining({
 inputParts: expect.arrayContaining([
 expect.objectContaining({ type: 'image', index: 1 }),
 ]),
 }),
 )
 })
})
