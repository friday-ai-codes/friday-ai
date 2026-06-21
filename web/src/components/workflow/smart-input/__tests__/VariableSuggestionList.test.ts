/**
 * VariableSuggestionList.vue 单元测试
 *
 * 回归锁定：弹窗「显示顺序」（输入组在前，再各节点组）必须与「点击/键盘取值顺序」
 * (flatItems) 完全一致。历史 bug：flatItems 按 variables 原始顺序展开，而显示与
 * getVariableFlatIndex 按分组顺序计算下标，导致选中错位——例如点「输入变量」组的
 * input.name，却插入了原始顺序里排在最前的节点变量 work_item_id。
 */

import type { SuggestionItem } from '../extensions/VariableSuggestion'
import type { DesignTimeVariable } from '~/composables/useDesignTimeVariables'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import VariableSuggestionList from '../VariableSuggestionList.vue'

function makeVar(overrides: Partial<DesignTimeVariable> & Pick<DesignTimeVariable, 'key' | 'path' | 'nodeId' | 'nodeLabel'>): DesignTimeVariable {
  return {
    label: `${overrides.nodeLabel} - ${overrides.key}`,
    outputLabel: overrides.key,
    type: 'string',
    description: '',
    ...overrides,
  }
}

// 关键：原始顺序里「节点变量」排在「输入变量」之前，复刻 useDesignTimeVariables
// 先塞上游节点 nodes.* 再塞直接上游 input.* 的真实顺序。
const workItemId = makeVar({ key: 'work_item_id', path: 'nodes.CK6.work_item_id', nodeId: 'ck6', nodeLabel: '飞书事件' })
const projectKey = makeVar({ key: 'project_key', path: 'nodes.CK6.project_key', nodeId: 'ck6', nodeLabel: '飞书事件' })
const inputName = makeVar({ key: 'name', path: 'input.name', nodeId: 'xwj', nodeLabel: '获取工作项' })
const inputDesc = makeVar({ key: 'description', path: 'input.description', nodeId: 'xwj', nodeLabel: '获取工作项' })

function makeWrapper(command = vi.fn()) {
  const items: SuggestionItem[] = [
    { type: 'variable', data: workItemId },
    { type: 'variable', data: projectKey },
    { type: 'variable', data: inputName },
    { type: 'variable', data: inputDesc },
  ]
  return { wrapper: mount(VariableSuggestionList, { props: { items, command } }), command }
}

describe('variableSuggestionList.vue', () => {
  it('输入组渲染在节点组之前', () => {
    const { wrapper } = makeWrapper()
    const text = wrapper.text()
    expect(text.indexOf('输入变量')).toBeGreaterThanOrEqual(0)
    expect(text.indexOf('输入变量')).toBeLessThan(text.indexOf('飞书事件'))
  })

  it('点击「输入变量」组首项插入的是 input.name 而非错位的节点变量', async () => {
    const { wrapper, command } = makeWrapper()

    // 找到展示 input.name 路径的那个按钮并点击
    const target = wrapper.findAll('button').find(b => b.text().includes('input.name'))
    expect(target).toBeTruthy()
    await target!.trigger('click')

    expect(command).toHaveBeenCalledTimes(1)
    const arg = command.mock.calls[0][0] as SuggestionItem
    expect(arg.type).toBe('variable')
    expect((arg.data as DesignTimeVariable).path).toBe('input.name')
  })

  it('点击「输入变量」组第二项插入的是 input.description', async () => {
    const { wrapper, command } = makeWrapper()
    const target = wrapper.findAll('button').find(b => b.text().includes('input.description'))
    await target!.trigger('click')
    const arg = command.mock.calls[0][0] as SuggestionItem
    expect((arg.data as DesignTimeVariable).path).toBe('input.description')
  })

  it('键盘 Enter 选中首个可见项（input.name），下标与显示一致', () => {
    const { wrapper, command } = makeWrapper()
    // 无函数时，flatItems[0] 应为显示顺序的首个变量 = input.name
    const enterEvent = new KeyboardEvent('keydown', { key: 'Enter' })
    ;(wrapper.vm as unknown as { onKeyDown: (e: KeyboardEvent) => boolean }).onKeyDown(enterEvent)
    const arg = command.mock.calls[0][0] as SuggestionItem
    expect((arg.data as DesignTimeVariable).path).toBe('input.name')
  })
})
