/**
 * PromptPreviewPanel.vue 单元测试
 *
 * 覆盖路径：
 * 1. body 为空时预览按钮 disabled + title="请先编辑 Prompt 正文"
 * 2. 点击预览按钮调 usePromptsStore().previewPrompt(id, variables)
 * 3. 200 响应在结果区展示 rendered（<pre> 块）
 * 4. PromptVariableMissingError 特判：设置 missingVariables 透传给子 Form
 * 5. 其他错误展示 Alert 错误文本
 */

import type { PromptDetail } from '~/types/prompts'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
// PromptVariableMissingError 从真实模块 import，不 mock
import { PromptVariableMissingError } from '~/api/prompts'
import PromptPreviewPanel from '../PromptPreviewPanel.vue'

// mock store 必须在 vi.mock hoist 时声明（vi.mock 本身会被自动提升到文件顶端）
const previewPromptMock = vi.fn()
vi.mock('~/stores/prompts', () => ({
  usePromptsStore: () => ({
    previewPrompt: previewPromptMock,
  }),
}))

const handleErrorMock = vi.fn()
vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: handleErrorMock }),
}))

const mockPrompt: PromptDetail = {
  id: 'prompt-abc',
  slug: 'chat.system.developer',
  category: 'chat_agent',
  scope: 'system',
  project: null,
  title: '测试 Prompt',
  description: '',
  is_builtin: false,
  active_version: {
    id: 'ver-1',
    version: 1,
    body: '{{input_text}}',
    variables_schema: {},
    declared_variables: ['input_text'],
    change_note: '',
    created_by: 1,
    created_at: '2026-04-01T00:00:00Z',
  },
  declared_variables: ['input_text'],
  created_by: 1,
  created_at: '2026-04-01T00:00:00Z',
  updated_at: '2026-04-01T00:00:00Z',
}

async function flushAsync(): Promise<void> {
  // 等 microtask + 组件反应式更新
  await new Promise(resolve => setTimeout(resolve, 20))
}

describe('promptPreviewPanel.vue', () => {
  beforeEach(() => {
    previewPromptMock.mockReset()
    handleErrorMock.mockReset()
  })

  it('body 为空时预览按钮 disabled 且带有 title 提示', () => {
    const wrapper = mount(PromptPreviewPanel, {
      props: { prompt: mockPrompt, body: '' },
    })
    const button = wrapper.find('button')
    expect(button.attributes('disabled')).toBeDefined()
    expect(button.attributes('title')).toContain('请先编辑 Prompt 正文')
  })

  it('点击预览按钮调 store.previewPrompt', async () => {
    previewPromptMock.mockResolvedValueOnce({ rendered: 'hello world' })
    const wrapper = mount(PromptPreviewPanel, {
      props: { prompt: mockPrompt, body: 'hello' },
    })
    await wrapper.find('button').trigger('click')
    await flushAsync()
    expect(previewPromptMock).toHaveBeenCalledTimes(1)
    expect(previewPromptMock).toHaveBeenCalledWith('prompt-abc', expect.any(Object))
  })

  it('200 响应在结果区展示 rendered <pre> 块', async () => {
    previewPromptMock.mockResolvedValueOnce({ rendered: '渲染后的文本内容' })
    const wrapper = mount(PromptPreviewPanel, {
      props: { prompt: mockPrompt, body: '{{input_text}}' },
    })
    await wrapper.find('button').trigger('click')
    await flushAsync()
    const pre = wrapper.find('pre')
    expect(pre.exists()).toBe(true)
    expect(pre.text()).toBe('渲染后的文本内容')
  })

  it('捕获 PromptVariableMissingError 设置 missingVariables 透传给 Form', async () => {
    previewPromptMock.mockRejectedValueOnce(
      new PromptVariableMissingError('chat.system.developer', ['input_text']),
    )
    const wrapper = mount(PromptPreviewPanel, {
      props: { prompt: mockPrompt, body: '{{input_text}}' },
    })
    await wrapper.find('button').trigger('click')
    await flushAsync()
    const form = wrapper.findComponent({ name: 'PromptVariableForm' })
    expect(form.exists()).toBe(true)
    expect(form.props('missingVariables')).toEqual(['input_text'])
    // PromptVariableMissingError 不走全局 handleError
    expect(handleErrorMock).not.toHaveBeenCalled()
  })

  it('其他错误展示 Alert 错误文本', async () => {
    previewPromptMock.mockRejectedValueOnce(new Error('后端爆了'))
    const wrapper = mount(PromptPreviewPanel, {
      props: { prompt: mockPrompt, body: 'hello' },
    })
    await wrapper.find('button').trigger('click')
    await flushAsync()
    expect(wrapper.text()).toContain('渲染失败')
    expect(wrapper.text()).toContain('后端爆了')
    expect(handleErrorMock).toHaveBeenCalled()
  })
})
