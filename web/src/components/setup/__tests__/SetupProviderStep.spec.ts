import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// i18n：返回 key 本身，断言用 key / 真实文案均可（这里用结构断言为主）
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

const setupProviderMock = vi.fn()
vi.mock('~/api/setup', () => ({
  setupProvider: (...args: unknown[]) => setupProviderMock(...args),
}))

const SetupProviderStep = (await import('~/components/setup/SetupProviderStep.vue')).default

beforeEach(() => {
  setupProviderMock.mockReset()
})

describe('setupProviderStep', () => {
  it('renders the 5 model presets', () => {
    const wrapper = mount(SetupProviderStep)
    const text = wrapper.text()
    expect(text).toContain('DeepSeek')
    expect(text).toContain('MiMo（小米）')
    expect(text).toContain('Kimi（Moonshot）')
    expect(text).toContain('Anthropic 官方')
    expect(text).toContain('自定义兼容端点')
  })

  it('selecting a preset auto-fills base_url and loads its preset models', async () => {
    const wrapper = mount(SetupProviderStep)
    const anthropicBtn = wrapper
      .findAll('button')
      .find(b => b.text().includes('Anthropic 官方'))!
    await anthropicBtn.trigger('click')
    await flushPromises()

    const inputs = wrapper.findAll('input')
    // 顺序：baseUrl, apiKey, 手动添加模型
    expect((inputs[0].element as HTMLInputElement).value).toBe('https://api.anthropic.com')
    // Anthropic 预设模型加载为可选列表
    expect(wrapper.text()).toContain('claude-sonnet-4-5')
  })

  it('submits config to setupProvider and emits done on success', async () => {
    setupProviderMock.mockResolvedValueOnce({
      id: 'c1',
      is_default: true,
      claude_code_bound: true,
    })
    const wrapper = mount(SetupProviderStep)
    const inputs = wrapper.findAll('input')
    // 默认预设(deepseek) 已填 base_url 并加载预设模型，仅需填 api key
    await inputs[1].setValue('sk-ant-test-key')
    await flushPromises()
    await wrapper.find('form').trigger('submit')

    await vi.waitFor(() => expect(setupProviderMock).toHaveBeenCalledTimes(1))
    const payload = setupProviderMock.mock.calls[0][0]
    expect(payload.api_key).toBe('sk-ant-test-key')
    expect(payload.base_url).toBe('https://api.deepseek.com/anthropic')
    // 默认选中预设首个模型
    expect(payload.model).toBe('deepseek-v4-pro')
    expect(payload.default_model).toBe('deepseek-v4-pro')
    await vi.waitFor(() => expect(wrapper.emitted('done')).toBeTruthy())
  })

  it('shows backend actionable error and does not emit done on failure', async () => {
    setupProviderMock.mockRejectedValueOnce(
      new Error('连接或鉴权失败：401。请检查 API Key'),
    )
    const wrapper = mount(SetupProviderStep)
    const inputs = wrapper.findAll('input')
    await inputs[1].setValue('bad-key')
    await flushPromises()
    await wrapper.find('form').trigger('submit')

    await vi.waitFor(() => expect(setupProviderMock).toHaveBeenCalledTimes(1))
    await vi.waitFor(() => expect(wrapper.text()).toContain('请检查 API Key'))
    expect(wrapper.emitted('done')).toBeFalsy()
  })

  it('emits skip when the skip button is clicked', async () => {
    const wrapper = mount(SetupProviderStep)
    const skipBtn = wrapper
      .findAll('button')
      .find(b => b.text().includes('setup.nav.skip'))!
    await skipBtn.trigger('click')
    expect(wrapper.emitted('skip')).toBeTruthy()
  })
})
