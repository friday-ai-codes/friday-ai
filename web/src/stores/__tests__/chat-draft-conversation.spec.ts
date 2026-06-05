import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

function readSource(path: string): string {
  return readFileSync(`${process.cwd()}/src/${path}`, 'utf8')
}

describe('chat draft conversation contract', () => {
  it('new conversation action stays local and does not create a backend id', () => {
    const source = readSource('stores/chat.ts')
    const createAction = source.slice(
      source.indexOf('async function createNewConversation()'),
      source.indexOf('async function removeConversation'),
    )

    expect(createAction).not.toContain('createConversation(')
    expect(createAction).toContain('syncConversationToURL(null)')
  })

  it('sendMessage materializes a local draft only when the user sends', () => {
    const source = readSource('stores/chat.ts')
    const sendAction = source.slice(
      source.indexOf('async function sendMessage'),
      source.indexOf('async function retryLastMessage'),
    )

    expect(sendAction).toContain('await createConversation')
    expect(sendAction).toContain('pendingConversation')
    expect(sendAction).toContain('deleteConversation')
  })

  it('chat input and welcome prompts do not pre-create conversations before sending', () => {
    const inputSource = readSource('components/chat/ChatInput.vue')
    const welcomeSource = readSource('components/chat/ChatWelcome.vue')

    expect(inputSource).not.toContain('await chatStore.createNewConversation()')
    expect(welcomeSource).not.toContain('await chatStore.createNewConversation()')
  })
})
