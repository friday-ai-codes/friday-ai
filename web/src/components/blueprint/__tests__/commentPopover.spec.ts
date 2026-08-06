/**
 * 划线评论就地浮层测试（quick-260806-j1z，飞书文档式交互）。
 *
 * 覆盖：
 *  1. draft 模式：引用条 + 输入框渲染；空内容发送禁用；填入后点击发送 emit submit（已 trim）
 *  2. Enter 发送 / Shift+Enter 不发送（换行）
 *  3. Esc emit close；取消按钮 emit close
 *  4. thread 模式：内嵌 BlueprintThreadCard 且 answer 透传
 *
 * ⚠️ happy-dom 无布局引擎，定位坐标归 UAT；Teleport 用 stub 拍平就地渲染。
 */

import type { BlueprintThreadDetail } from '~/types/blueprint'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import BlueprintCommentPopover from '~/components/blueprint/BlueprintCommentPopover.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        blueprints: {
          annotation: {
            sidebarTitle: '批注',
            quotedSnapshot: '引用时的原文快照',
            inlineComposer: {
              title: '添加评论',
              placeholder: '评论…',
              send: '发送',
              cancel: '取消',
            },
          },
          thread: {
            kindAiClarification: 'AI 提问',
            kindAiReviewFinding: 'AI 审查',
            kindHumanComment: '人工评论',
            kindRepoConfirmation: '确认门',
            severityBlocker: '阻塞',
            severityWarning: '警告',
            severityInfo: '提示',
            severityNone: '未分级',
            groupOpen: '未决',
            groupAnswered: '已回答',
            groupClosed: '已关闭',
            composerPlaceholder: '写下你的回复…',
            composerSubmit: '提交回复',
            composerEmpty: '回复内容不可为空',
            optionsHint: '可直接选用下列候选答案',
            authorAi: 'AI',
          },
        },
      },
    },
  },
})

const RECT = { top: 100, bottom: 120, left: 40, right: 240, width: 200, height: 20 } as DOMRect

function makeThread(overrides: Partial<BlueprintThreadDetail> = {}): BlueprintThreadDetail {
  return {
    thread_id: 't1',
    kind: 'human_comment',
    severity: '',
    status: 'open',
    blocking: false,
    anchor_status: 'anchored',
    anchor: { block_id: 'b1', start_offset: 0, end_offset: 3, quoted_text: '原文' },
    return_stage: '',
    created_at: '2026-08-01T00:00:00Z',
    options: [],
    last_reminded_at: null,
    messages: [],
    ...overrides,
  }
}

function mountPopover(props: Record<string, unknown>) {
  return mount(BlueprintCommentPopover, {
    props: { rect: RECT, ...props } as never,
    global: { plugins: [i18n], stubs: { teleport: true } },
  })
}

describe('draft 模式（就地评论输入卡）', () => {
  it('1. 引用条与输入框渲染；空内容发送禁用；填入后发送 emit submit（trim）', async () => {
    const wrapper = mountPopover({ quotedText: '被评论的原文片段' })
    expect(wrapper.find('[data-testid="blueprint-comment-popover"]').attributes('data-popover-mode')).toBe('draft')
    expect(wrapper.find('[data-testid="blueprint-comment-quote"]').text()).toContain('被评论的原文片段')
    expect(wrapper.find('[data-testid="blueprint-comment-send"]').attributes('disabled')).toBeDefined()
    await wrapper.find('[data-testid="blueprint-comment-input"]').setValue('  这里改成异步  ')
    const send = wrapper.find('[data-testid="blueprint-comment-send"]')
    expect(send.attributes('disabled')).toBeUndefined()
    await send.trigger('click')
    expect(wrapper.emitted('submit')?.[0]).toEqual(['这里改成异步'])
  })

  it('2. Enter 发送；Shift+Enter 不发送', async () => {
    const wrapper = mountPopover({ quotedText: '片段' })
    const input = wrapper.find('[data-testid="blueprint-comment-input"]')
    await input.setValue('回复内容')
    await input.trigger('keydown.enter', { shiftKey: true })
    expect(wrapper.emitted('submit')).toBeUndefined()
    await input.trigger('keydown.enter')
    expect(wrapper.emitted('submit')?.[0]).toEqual(['回复内容'])
  })

  it('3. 取消按钮与 Esc 都 emit close', async () => {
    const wrapper = mountPopover({ quotedText: '片段' })
    await wrapper.find('[data-testid="blueprint-comment-cancel"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('close')).toHaveLength(2)
  })

  it('submitting 时发送禁用', async () => {
    const wrapper = mountPopover({ quotedText: '片段', submitting: true })
    await wrapper.find('[data-testid="blueprint-comment-input"]').setValue('内容')
    expect(wrapper.find('[data-testid="blueprint-comment-send"]').attributes('disabled')).toBeDefined()
  })
})

describe('thread 模式（就地线程卡）', () => {
  it('4. 内嵌 BlueprintThreadCard 且 answer 透传', async () => {
    const wrapper = mountPopover({ thread: makeThread() })
    expect(wrapper.find('[data-testid="blueprint-comment-popover"]').attributes('data-popover-mode')).toBe('thread')
    expect(wrapper.find('[data-testid="blueprint-thread-card"]').exists()).toBe(true)
    await wrapper.find('[data-testid="blueprint-thread-composer-input"]').setValue('就地回复')
    await wrapper.find('[data-testid="blueprint-thread-composer-submit"]').trigger('click')
    expect(wrapper.emitted('answer')?.[0]).toEqual(['t1', '就地回复'])
  })
})
