/**
 * 「未经确认」常驻横幅 + 飞书导出按钮的组件测试（Phase 116-05，VIEW-05）。
 *
 * 守七件事：
 *  1. ⭐ 抑制白名单三态（`confirmed` / `implementing` / `implemented`）**不出**横幅。
 *  2. ⭐ 其余八态 + 未知串 + **空串**都出横幅（白名单是闭合集合，方向 fail-safe）。
 *  3. ⭐ 白名单变异：去掉任一成员 ⇒ 用例 1 对应那条转红（变异实跑记录见 SUMMARY）。
 *  4. ⭐ 横幅**不可关闭**：横幅内不存在任何按钮/dismiss 控件。
 *  5. ⭐ 导出按钮按 availability **隐藏**：`false` / `undefined` ⇒ 按钮**不存在于 DOM**
 *     （⛔ 断言的不是 disabled）；`true` ⇒ 存在。
 *  6. ⭐ 组件**只 emit 不发请求**：点击 ⇒ emit `export` 一次，且两个 api 函数零调用。
 *  7. 前后端判据逐字对齐：组件里的三个状态字面量与后端 `_SUPPRESS_WATERMARK_STATUSES`
 *     的成员相同（读后端源码提取比对）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import BlueprintViewerHeader from '~/components/blueprint/BlueprintViewerHeader.vue'

vi.mock('~/api/blueprints', () => ({
  getBlueprintExportAvailability: vi.fn(),
  exportBlueprintToFeishu: vi.fn(),
  default: {
    getBlueprintExportAvailability: vi.fn(),
    exportBlueprintToFeishu: vi.fn(),
  },
}))

const BANNER = '[data-testid="blueprint-unconfirmed-banner"]'
const EXPORT_BUTTON = '[data-testid="blueprint-header-export"]'

const CONFIRMED_STATUSES = ['confirmed', 'implementing', 'implemented']
const UNCONFIRMED_STATUSES = [
  'researching',
  'drafting',
  'ai_reviewing',
  'needs_clarification',
  'pending_review',
  'archived',
  'failed',
  'superseded',
  'totally_unknown',
  '',
]

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        blueprints: {
          statusUnknown: '未知状态',
          export: {
            unconfirmedBanner: '未经确认 —— 本方案尚未经人工终审，导出物同样会带此标注',
            action: '导出到飞书',
            success: '已导出到飞书文档',
            openDoc: '打开文档',
            unavailable: '飞书文档服务暂时不可用，请稍后重试',
          },
          viewer: { live: '实时更新中' },
          annotation: {
            showClosed: '显示已关闭批注',
            sidebarExpand: '展开批注栏',
            sidebarCollapse: '收起批注栏',
            sidebarToggle: '批注 {n}',
            sidebarToggleEmpty: '批注',
            sidebarToggleAria: '批注 {n}',
            countBlocker: '阻塞 {n}',
            countClarification: '待澄清 {n}',
            countOrphaned: '失锚 {n}',
          },
          review: {
            approve: '通过方案',
            reject: '驳回修订',
            disabledReadonly: '当前状态下不可执行该操作',
            disabledReason: '当前状态为「{status}」，需等待进入待人类审查',
            reviewRound: '第 {n} 轮审查',
          },
          status: {
            confirmed: '已确认',
            implementing: '实施中',
            implemented: '实施完成',
            pending_review: '待人类审查',
          },
          version: { switcher: '版本', current: '当前' },
        },
      },
    },
  },
})

function mountHeader(props: Record<string, unknown> = {}) {
  return mount(BlueprintViewerHeader, {
    props: { currentStatus: 'pending_review', ...props },
    global: { plugins: [i18n] },
  })
}

describe('「未经确认」常驻横幅', () => {
  it.each(CONFIRMED_STATUSES)('已确认态 %s 不出横幅', (status) => {
    expect(mountHeader({ currentStatus: status }).find(BANNER).exists()).toBe(false)
  })

  it.each(UNCONFIRMED_STATUSES)('未确认态 %s 出横幅', (status) => {
    const wrapper = mountHeader({ currentStatus: status })
    expect(wrapper.find(BANNER).exists()).toBe(true)
    expect(wrapper.find(BANNER).text()).toContain('未经确认')
  })

  it('⭐ 横幅不可关闭：横幅内不存在任何按钮/dismiss 控件', () => {
    const wrapper = mountHeader({ currentStatus: 'pending_review' })
    expect(wrapper.find(BANNER).exists()).toBe(true)
    expect(wrapper.find(`${BANNER} button`).exists()).toBe(false)
    expect(wrapper.find(`${BANNER} [aria-label*="关闭"]`).exists()).toBe(false)
  })

  it('⭐ 前后端白名单逐字对齐（读后端源码提取比对）', () => {
    const backend = readFileSync(
      resolve(process.cwd(), '../server/services/process_runtime/blueprint_render.py'),
      'utf8',
    )
    // ⚠️ 定位的是**定义处**而不是 docstring 里的提及（后者出现得更早）。
    const start = backend.indexOf('_SUPPRESS_WATERMARK_STATUSES: frozenset')
    expect(start).toBeGreaterThan(0)
    const block = backend.slice(start, backend.indexOf(')', start))
    const members = [...block.matchAll(/"([a-z_]+)",/g)].map(match => match[1])
    expect(members.sort()).toEqual([...CONFIRMED_STATUSES].sort())

    const component = readFileSync(
      resolve(process.cwd(), 'src/components/blueprint/BlueprintViewerHeader.vue'),
      'utf8',
    )
    for (const status of CONFIRMED_STATUSES)
      expect(component).toContain(`'${status}'`)
  })
})

describe('飞书导出按钮', () => {
  it('availability 为 false ⇒ 按钮不存在于 DOM（⛔ 不是 disabled）', () => {
    const wrapper = mountHeader({ exportAvailable: false })
    expect(wrapper.find(EXPORT_BUTTON).exists()).toBe(false)
  })

  it('availability 未传（查询未回来）⇒ 按钮同样不存在于 DOM', () => {
    const wrapper = mountHeader({})
    expect(wrapper.find(EXPORT_BUTTON).exists()).toBe(false)
  })

  it('availability 为 true ⇒ 按钮存在', () => {
    const wrapper = mountHeader({ exportAvailable: true })
    expect(wrapper.find(EXPORT_BUTTON).exists()).toBe(true)
  })

  it('disabled 只表达「导出在途」，⛔ 不表达「不可用」', () => {
    const inflight = mountHeader({ exportAvailable: true, exporting: true })
    expect(inflight.find(EXPORT_BUTTON).attributes('disabled')).toBeDefined()
    const idle = mountHeader({ exportAvailable: true, exporting: false })
    expect(idle.find(EXPORT_BUTTON).attributes('disabled')).toBeUndefined()
  })

  it('⭐ 组件只 emit 不发请求', async () => {
    const blueprintsApi = await import('~/api/blueprints')
    const wrapper = mountHeader({ exportAvailable: true })

    await wrapper.find(EXPORT_BUTTON).trigger('click')

    expect(wrapper.emitted('export')).toHaveLength(1)
    expect(blueprintsApi.exportBlueprintToFeishu).toHaveBeenCalledTimes(0)
    expect(blueprintsApi.getBlueprintExportAvailability).toHaveBeenCalledTimes(0)
  })

  it('⛔ 组件源码里零 api 调用（防后人把请求塞回组件）', () => {
    const component = readFileSync(
      resolve(process.cwd(), 'src/components/blueprint/BlueprintViewerHeader.vue'),
      'utf8',
    )
    expect(component).not.toContain('exportBlueprintToFeishu')
    expect(component).not.toContain('getBlueprintExportAvailability')
  })
})

/**
 * ⭐ UI-REVIEW M-1 回归：「批注 {n}」的 n 取页面传入的 `annotationTotal`，
 * ⛔ **不是**三个语义计数相加。
 *
 * 三者口径不正交：`blocker` 含失锚、`clarification` 已排除失锚 ⇒ 相加会重复计数失锚的
 * 未决 blocker，同时把人工评论 / 已作答 / 已关闭线程一条不落地漏掉。
 */
describe('窄屏「批注 {n}」按钮的计数口径（M-1）', () => {
  const OPEN_BUTTON = '[data-testid="blueprint-header-open-annotations"]'

  it('⭐ 显示的是 annotationTotal，⛔ 不是三个语义计数之和', () => {
    const wrapper = mountHeader({
      counts: { blocker: 1, clarification: 1, orphaned: 1 },
      annotationTotal: 7,
    })
    expect(wrapper.find(OPEN_BUTTON).text()).toContain('批注 7')
    // 非恒真对照：老实现会显示 3。
    expect(wrapper.find(OPEN_BUTTON).text()).not.toContain('批注 3')
  })

  it('⭐ 三个语义计数全为 0 但仍有批注（人工评论 / 已关闭）⇒ 按钮照常报数', () => {
    const wrapper = mountHeader({
      counts: { blocker: 0, clarification: 0, orphaned: 0 },
      annotationTotal: 4,
    })
    expect(wrapper.find(OPEN_BUTTON).text()).toContain('批注 4')
  })

  it('总数为 0 ⇒ 只显示「批注」（§16：不显示 0）', () => {
    const wrapper = mountHeader({
      counts: { blocker: 3, clarification: 0, orphaned: 0 },
      annotationTotal: 0,
    })
    expect(wrapper.find(OPEN_BUTTON).text().trim()).toBe('批注')
  })

  it('⛔ 组件源码里不再自算总数（防后人把三者相加塞回来）', () => {
    const component = readFileSync(
      resolve(process.cwd(), 'src/components/blueprint/BlueprintViewerHeader.vue'),
      'utf8',
    )
    expect(component).not.toContain('counts.blocker + ')
  })
})

/**
 * ⭐ UI-REVIEW L-10：§5.2 的 `< md` 行写的是「计数徽标折成**一行可横向滚动**」。
 *
 * 顶栏是 `sticky`，让徽标参与外层 `flex-wrap` 会在窄屏把整条顶栏撑高，
 * 直接挤压它下方的正文可视区。⚠️ happy-dom 无布局引擎 ⇒ ⛔ 不量高度，只断言类名与结构。
 */
describe('窄屏计数徽标不换行（L-10）', () => {
  const COUNTS = '[data-testid="blueprint-header-counts"]'

  it('三个计数徽标包在同一个 flex-nowrap + overflow-x-auto 容器里', () => {
    const wrapper = mountHeader({ counts: { blocker: 1, clarification: 2, orphaned: 3 } })
    const row = wrapper.find(COUNTS)
    expect(row.exists()).toBe(true)
    expect(row.classes()).toContain('flex-nowrap')
    expect(row.classes()).toContain('overflow-x-auto')
    expect(row.findAll('[data-count]')).toHaveLength(3)
  })

  it('非恒真对照：三个计数全为 0 ⇒ 容器本身也不渲染（⛔ 不留一条空白横条）', () => {
    const wrapper = mountHeader({ counts: { blocker: 0, clarification: 0, orphaned: 0 } })
    expect(wrapper.find(COUNTS).exists()).toBe(false)
  })
})
