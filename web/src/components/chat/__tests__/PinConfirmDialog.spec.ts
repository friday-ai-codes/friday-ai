/**
 * — PinConfirmDialog 组件测试（ 切换 Provider 弹窗）
 *
 * 覆盖 Behaviors D / E / F：
 *   D: 渲染 UI-SPEC §Copywriting 硬锁标题
 *   E: 点击"确认切换"emit('confirm') + loading 态
 *   F: 点击"取消"emit('cancel') + update:open(false)
 */
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import PinConfirmDialog from '~/components/chat/PinConfirmDialog.vue'

function makeProps(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    open: true,
    oldProviderName: 'Anthropic（默认）',
    oldModel: 'claude-3-5-sonnet-20241022',
    newProviderName: 'OpenAI（Chat）',
    newModel: 'gpt-4o-mini',
    messageCount: 12,
    ...overrides,
  }
}

/** 清理 Dialog teleport 内容（reka-ui 将内容渲染到 document.body，用例间要重置）。 */
function cleanupBody() {
  document.body.innerHTML = ''
}

describe('pinConfirmDialog', () => {
  afterEach(cleanupBody)

  it('open=true 时渲染 UI-SPEC §Copywriting 硬锁标题', async () => {
    mount(PinConfirmDialog, {
      props: makeProps(),
      attachTo: document.body,
    })
    await nextTick()
    await flushPromises()
    expect(document.body.textContent).toContain(
      '切换 Provider 将固定当前 Provider 到本对话',
    )
  })

  it('正文包含原 / 新 Provider diff 与 messageCount', async () => {
    mount(PinConfirmDialog, {
      props: makeProps({ messageCount: 7 }),
      attachTo: document.body,
    })
    await nextTick()
    await flushPromises()
    const text = document.body.textContent ?? ''
    expect(text).toContain('7')
    expect(text).toContain('Anthropic（默认）')
    expect(text).toContain('OpenAI（Chat）')
    expect(text).toContain('claude-3-5-sonnet-20241022')
    expect(text).toContain('gpt-4o-mini')
  })

  it('点击"确认切换"触发 emit("confirm")', async () => {
    const wrapper = mount(PinConfirmDialog, {
      props: makeProps(),
      attachTo: document.body,
    })
    await nextTick()
    await flushPromises()
    const confirmBtn = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find(b => b.textContent?.includes('确认切换'))
    expect(confirmBtn).toBeDefined()
    confirmBtn!.click()
    await nextTick()
    expect(wrapper.emitted('confirm')).toBeTruthy()
  })

  it('点击"取消"触发 emit("cancel") + update:open(false)', async () => {
    const wrapper = mount(PinConfirmDialog, {
      props: makeProps(),
      attachTo: document.body,
    })
    await nextTick()
    await flushPromises()
    const cancelBtn = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find(b => b.textContent?.trim() === '取消')
    expect(cancelBtn).toBeDefined()
    cancelBtn!.click()
    await nextTick()
    expect(wrapper.emitted('cancel')).toBeTruthy()
    expect(wrapper.emitted('update:open')?.[0]).toEqual([false])
  })

  it('open=false 时不渲染标题', async () => {
    mount(PinConfirmDialog, {
      props: makeProps({ open: false }),
      attachTo: document.body,
    })
    await nextTick()
    await flushPromises()
    expect(document.body.textContent).not.toContain(
      '切换 Provider 将固定当前 Provider 到本对话',
    )
  })

  it('组件未使用 backdrop-blur（Clean Card 合规）', async () => {
    mount(PinConfirmDialog, {
      props: makeProps(),
      attachTo: document.body,
    })
    await nextTick()
    await flushPromises()
    expect(document.body.innerHTML).not.toContain('backdrop-blur')
  })
})
