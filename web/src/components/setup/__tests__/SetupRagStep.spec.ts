import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

const setupRagMock = vi.fn()
vi.mock('~/api/setup', () => ({
  setupRag: (...args: unknown[]) => setupRagMock(...args),
}))

const SetupRagStep = (await import('~/components/setup/SetupRagStep.vue')).default

beforeEach(() => {
  setupRagMock.mockReset()
})

describe('setupRagStep', () => {
  it('submits qdrant_url and optional fields, emits done', async () => {
    setupRagMock.mockResolvedValueOnce({ rag_configured: true, written_keys: ['qdrant_url'] })
    const wrapper = mount(SetupRagStep)
    // 默认已填 qdrantUrl=http://qdrant:6333，直接提交
    await wrapper.find('form').trigger('submit')

    await vi.waitFor(() => expect(setupRagMock).toHaveBeenCalledTimes(1))
    expect(setupRagMock.mock.calls[0][0]).toEqual({ qdrant_url: 'http://qdrant:6333' })
    await vi.waitFor(() => expect(wrapper.emitted('done')).toBeTruthy())
  })

  it('includes optional api key and dimension when provided', async () => {
    setupRagMock.mockResolvedValueOnce({ rag_configured: true, written_keys: [] })
    const wrapper = mount(SetupRagStep)
    const inputs = wrapper.findAll('input')
    // 顺序：qdrantUrl, qdrantApiKey, embeddingApiUrl, embeddingApiKey, embeddingModel, embeddingDimension
    await inputs[1].setValue('qkey')
    await inputs[5].setValue('1024')
    await flushPromises()
    await wrapper.find('form').trigger('submit')

    await vi.waitFor(() => expect(setupRagMock).toHaveBeenCalledTimes(1))
    const payload = setupRagMock.mock.calls[0][0]
    expect(payload.qdrant_api_key).toBe('qkey')
    expect(payload.embedding_dimension).toBe(1024)
  })

  it('emits skip without calling the endpoint', async () => {
    const wrapper = mount(SetupRagStep)
    const skipBtn = wrapper.findAll('button').find(b => b.text().includes('setup.rag.skip'))!
    await skipBtn.trigger('click')
    expect(wrapper.emitted('skip')).toBeTruthy()
    expect(setupRagMock).not.toHaveBeenCalled()
  })
})
