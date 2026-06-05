import type { MessagePart } from '~/types/chat'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { connectSSE } from '~/composables/useSSEStream'

function sseResponse(payload = 'data: {"type":"message_complete"}\n\n'): Response {
  const bytes = new TextEncoder().encode(payload)
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(bytes)
        controller.close()
      },
    }),
    { status: 200 },
  )
}

describe('useSSEStream multimodal request body', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('sends input_parts when image parts are provided', async () => {
    const imagePart: MessagePart = {
      type: 'image',
      id: 'p_img',
      index: 1,
      mime_type: 'image/png',
      size_bytes: 68,
      storage_ref: 'chat_images/pixel.png',
      detail: 'auto',
    }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(sseResponse())

    await connectSSE(
      'conv-1',
      '请分析这张图片',
      'developer',
      vi.fn(),
      new AbortController().signal,
      { inputParts: [imagePart] },
    )

    const init = fetchMock.mock.calls[0][1] as RequestInit
    const body = JSON.parse(String(init.body))
    expect(body.content).toBe('请分析这张图片')
    expect(body.input_parts).toEqual([imagePart])
  })
})
