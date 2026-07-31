/**
 * `PlanResearchLogGroup.vue` 渲染契约测试（110-07 / OBS-02）。
 *
 * 🔴 **不 stub `DeepAnalysisCard`**：本组的核心断言是「仓库名有没有真的进到卡片标题」
 * 与「展开策略有没有真的落到卡片上」，stub 掉被测对象会让这两条变成空断言。
 * 组件树挂到真实的 `DeepAnalysisCard` 为止，只有它内部的 `StructuredJsonView`
 * 是叶子（本组用例不展开任何工具行，因此不会被渲染）。
 */

import type { PlanResearchSession } from '~/types/chat'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PlanResearchLogGroup from '~/components/chat/PlanResearchLogGroup.vue'

const GROUP = '[data-test="plan-research-log-group"]'
const TOGGLE = '[data-test="plan-research-log-toggle"]'

/** 兜底路径专用：一个绝不能出现在 DOM 里的裸 UUID。 */
const BARE_UUID = '7c9e6679-7425-40de-944b-e07fc1f90ae7'

function makeSession(overrides: Partial<PlanResearchSession> = {}): PlanResearchSession {
  return {
    session_id: 'sub-1',
    plan_session_id: 'conv-sess-1',
    repository_id: 'repo-1',
    repository_name: 'example-app',
    status: 'COMPLETED',
    logs: [{ type: 'text', content: '开始调研入口逻辑', ts: 1 }],
    ...overrides,
  }
}

function mountGroup(sessions: PlanResearchSession[], repoNames?: Record<string, string>) {
  return mount(PlanResearchLogGroup, { props: { sessions, repoNames } })
}

describe('planResearchLogGroup 渲染契约', () => {
  beforeEach(() => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    expect(console.warn).not.toHaveBeenCalled()
    expect(console.error).not.toHaveBeenCalled()
    vi.restoreAllMocks()
  })

  it('两个仓渲染两张卡，标题分别是两个仓库名', () => {
    const wrapper = mountGroup([
      makeSession({ session_id: 'sub-1', repository_id: 'repo-1', repository_name: 'example-app' }),
      makeSession({ session_id: 'sub-2', repository_id: 'repo-2', repository_name: 'question-bank' }),
    ])
    const cards = wrapper.findAll('.da-card')
    expect(cards).toHaveLength(2)
    expect(cards[0].find('.da-title').text()).toBe('example-app')
    expect(cards[1].find('.da-title').text()).toBe('question-bank')
  })

  it('repository_name 缺失时走 repoNames 兜底', () => {
    const wrapper = mountGroup(
      [makeSession({ repository_id: BARE_UUID, repository_name: '' })],
      { [BARE_UUID]: 'mapped-repo' },
    )
    expect(wrapper.find('.da-title').text()).toBe('mapped-repo')
  })

  it('两级来源都缺失时标题为「未知仓库」，且整棵 DOM 不含裸 UUID', () => {
    const wrapper = mountGroup([
      makeSession({ session_id: 'sub-x', repository_id: BARE_UUID, repository_name: undefined }),
    ])
    expect(wrapper.find('.da-title').text()).toBe('未知仓库')
    // 🔴 「绝不回显裸 UUID」只有这条断言守得住：把兜底改成回显 repository_id 时，
    // 上面那条「等于未知仓库」会红，但把兜底改成「UUID 前 8 位 + …」它就不红了。
    expect(wrapper.html()).not.toContain(BARE_UUID)
    expect(wrapper.text()).not.toContain(BARE_UUID)
  })

  it('单仓时该卡默认展开，日志行可见', () => {
    const wrapper = mountGroup([
      makeSession({ logs: [{ type: 'text', content: '单仓调研日志', ts: 1 }] }),
    ])
    expect(wrapper.findAll('.da-logs')).toHaveLength(1)
    expect(wrapper.text()).toContain('单仓调研日志')
  })

  it('多仓时仅第一张展开，第二张的日志行不可见', () => {
    const wrapper = mountGroup([
      makeSession({ session_id: 'sub-1', repository_id: 'repo-1', logs: [{ type: 'text', content: '首仓日志', ts: 1 }] }),
      makeSession({ session_id: 'sub-2', repository_id: 'repo-2', logs: [{ type: 'text', content: '次仓日志', ts: 2 }] }),
      makeSession({ session_id: 'sub-3', repository_id: 'repo-3', logs: [{ type: 'text', content: '三仓日志', ts: 3 }] }),
    ])
    expect(wrapper.findAll('.da-card')).toHaveLength(3)
    // 日志区只存在于首张卡上
    expect(wrapper.findAll('.da-logs')).toHaveLength(1)
    expect(wrapper.text()).toContain('首仓日志')
    expect(wrapper.text()).not.toContain('次仓日志')
    expect(wrapper.text()).not.toContain('三仓日志')
  })

  it('空数组时整组不渲染，不占位也不写空态文案', () => {
    const wrapper = mountGroup([])
    expect(wrapper.find(GROUP).exists()).toBe(false)
    expect(wrapper.find('.da-card').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('组标题是「方案调研 · {n} 个仓库」，与深度分析在文案与图标两处都不同', () => {
    const wrapper = mountGroup([
      makeSession({ session_id: 'sub-1', repository_id: 'repo-1' }),
      makeSession({ session_id: 'sub-2', repository_id: 'repo-2' }),
    ])
    const toggle = wrapper.find(TOGGLE)
    expect(toggle.text()).toContain('方案调研 · 2 个仓库')
    // §C.3 的机械抓手：三条差异里有两条可以在 DOM 上直接读出来
    expect(wrapper.text()).not.toContain('深度分析')
    expect(wrapper.html()).toContain('icon-[lucide--search-code]')
    expect(wrapper.html()).not.toContain('icon-[lucide--layers]')
  })

  it('点组标题折叠整组，卡片消失且 aria-expanded 随之变化', async () => {
    const wrapper = mountGroup([makeSession()])
    const toggle = wrapper.find(TOGGLE)
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(toggle.attributes('aria-label')).toBe('收起方案调研日志')
    expect(wrapper.findAll('.da-card')).toHaveLength(1)

    await toggle.trigger('click')

    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.attributes('aria-label')).toBe('展开方案调研日志')
    expect(wrapper.findAll('.da-card')).toHaveLength(0)
    // 🔴 不消失：组标题行仍在，用户随时能再展开（OBS-02 要的是「可查」）
    expect(wrapper.find(GROUP).exists()).toBe(true)
    expect(wrapper.find(TOGGLE).exists()).toBe(true)
  })

  it.each([
    ['RUNNING', true],
    ['PENDING', true],
    ['running', true],
    ['COMPLETED', false],
    ['ERROR', false],
  ])('status=%s 时卡片运行态样式为 %s', (status, running) => {
    const wrapper = mountGroup([makeSession({ status })])
    expect(wrapper.find('.da-card').classes('da-card--running')).toBe(running)
  })

  it('logs 为空时沿用 DeepAnalysisCard 既有空态，本组件不另写文案', () => {
    const wrapper = mountGroup([makeSession({ status: 'COMPLETED', logs: [] })])
    expect(wrapper.find('.da-empty').text()).toBe('暂无执行记录')
    // 本组件自己的空态文案一个都不该出现
    expect(wrapper.text()).not.toContain('暂无日志')
    expect(wrapper.text()).not.toContain('暂无调研')
  })

  it('logs 缺失（老后端形状）时不抛错，交给卡片空态', () => {
    const broken = { ...makeSession(), logs: undefined } as unknown as PlanResearchSession
    const wrapper = mountGroup([broken])
    expect(wrapper.find(GROUP).exists()).toBe(true)
    expect(wrapper.find('.da-empty').exists()).toBe(true)
  })

  it('组件源码零 v-html、零 localStorage、不引用 DeepAnalysisGroup', () => {
    const src = readFileSync(resolve(__dirname, '../PlanResearchLogGroup.vue'), 'utf-8')
    const code = src.split('\n').filter(l => !l.trim().startsWith('*') && !l.trim().startsWith('//'))
    expect(code.join('\n')).not.toContain('v-html')
    expect(code.join('\n')).not.toContain('localStorage')
    // 🔴 §C.1：横向 swiper 会把「并行」藏起来，且它的 bar 标题写死无 prop
    expect(code.join('\n')).not.toContain('DeepAnalysisGroup')
  })
})
