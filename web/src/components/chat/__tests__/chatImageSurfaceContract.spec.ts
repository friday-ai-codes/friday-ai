import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

function readSource(path: string): string {
  return readFileSync(`${process.cwd()}/src/${path}`, 'utf8')
}

describe('chat image surface source contract', () => {
  it('chatInput wires paste/drop/file picker, upload, preview and removal', () => {
    const source = readSource('components/chat/ChatInput.vue')

    expect(source).toContain('@paste')
    expect(source).toContain('@drop.prevent')
    expect(source).toContain('type="file"')
    expect(source).toContain('accept="image/png,image/jpeg,image/gif,image/webp"')
    expect(source).toContain('aria-label="添加图片"')
    expect(source).toContain('uploadChatImage')
    expect(source).toContain('pendingImages')
    expect(source).toContain('removePendingImage')
  })

  it('chatMessageBubble renders user image parts without reading Message.content base64', () => {
    const source = readSource('components/chat/ChatMessageBubble.vue')

    expect(source).toContain('userImageParts')
    expect(source).toContain('image-preview-grid')
    expect(source).toContain('storage_ref')
    expect(source).not.toContain('data:image/')
  })
})
