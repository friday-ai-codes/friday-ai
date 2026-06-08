import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

const setupFeishuMock = vi.fn()
vi.mock('~/api/setup', () => ({
  setupFeishu: (...args: unknown[]) => setupFeishuMock(...args),
}))

const SetupFeishuStep = (await import('~/components/setup/SetupFeishuStep.vue')).default

beforeEach(() => {
  setupFeishuMock.mockReset()
})

describe('setupFeishuStep', () => {
  it('submits app_id + app_secret and emits done on success', async () => {
    setupFeishuMock.mockResolvedValueOnce({ feishu_configured: true })
    const wrapper = mount(SetupFeishuStep)
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('cli_test')
    await inputs[1].setValue('secret-x')
    await flushPromises()
    await wrapper.find('form').trigger('submit')

    await vi.waitFor(() => expect(setupFeishuMock).toHaveBeenCalledTimes(1))
    expect(setupFeishuMock.mock.calls[0][0]).toEqual({ app_id: 'cli_test', app_secret: 'secret-x' })
    await vi.waitFor(() => expect(wrapper.emitted('done')).toBeTruthy())
  })

  it('emits skip without calling the endpoint', async () => {
    const wrapper = mount(SetupFeishuStep)
    const skipBtn = wrapper.findAll('button').find(b => b.text().includes('setup.feishu.skip'))!
    await skipBtn.trigger('click')
    expect(wrapper.emitted('skip')).toBeTruthy()
    expect(setupFeishuMock).not.toHaveBeenCalled()
  })

  it('shows backend error and does not emit done on failure', async () => {
    setupFeishuMock.mockRejectedValueOnce(new Error('飞书配置保存失败'))
    const wrapper = mount(SetupFeishuStep)
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('cli_test')
    await inputs[1].setValue('bad')
    await flushPromises()
    await wrapper.find('form').trigger('submit')

    await vi.waitFor(() => expect(setupFeishuMock).toHaveBeenCalledTimes(1))
    await vi.waitFor(() => expect(wrapper.text()).toContain('飞书配置保存失败'))
    expect(wrapper.emitted('done')).toBeFalsy()
  })
})
