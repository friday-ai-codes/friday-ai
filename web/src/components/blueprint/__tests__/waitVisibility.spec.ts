/**
 * 归属回跳与等待态可见性的组件测试（Phase 117，LINK-01 / WAIT-03）。
 *
 * 守六件事：
 *  1. ⭐ 顶栏出「所属项目」面包屑并链到 `/projects/{id}`（LINK-01 的落点是**顶栏**，
 *     不是页尾关联段 —— 后者要滚到最底，回跳等于不可达）。
 *  2. ⭐ 无归属时面包屑**不存在于 DOM**（⛔ 不出灰按钮、⛔ 不出 `#` 死链）。
 *  3. ⭐ `project_name` 为空（项目已删/脏数据）时文案回落「未命名项目」，
 *     **绝不回落成 UUID** —— 一串 uuid 对人零信息量。
 *  4. ⭐ 归属 id 缺顶层键时回落 `content.meta.project_id`（权威位置始终是后者）。
 *  5. ⭐ 到期线程出「已到期」徽标 + 说明，且**状态徽标仍是「未决」** ——
 *     到期只停提醒，不等于已处置（后端 `status`/`blocking` 一字不动的对称面）。
 *  6. 等待态一行给出「等了多久 · 催过几次 · 上次何时」；未到期线程无到期徽标。
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import BlueprintThreadCard from '~/components/blueprint/BlueprintThreadCard.vue'
import BlueprintViewerHeader from '~/components/blueprint/BlueprintViewerHeader.vue'

vi.mock('~/api/blueprints', () => ({
  getBlueprintExportAvailability: vi.fn(),
  exportBlueprintToFeishu: vi.fn(),
  default: {
    getBlueprintExportAvailability: vi.fn(),
    exportBlueprintToFeishu: vi.fn(),
  },
}))

const CRUMB = '[data-testid="blueprint-header-project-crumb"]'
const EXPIRED_BADGE = '[data-testid="blueprint-thread-expired-badge"]'
const EXPIRED_HINT = '[data-testid="blueprint-thread-expired-hint"]'
const WAITING = '[data-testid="blueprint-thread-waiting"]'

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
          export: { unconfirmedBanner: '未经确认', action: '导出到飞书' },
          viewer: {
            live: '实时更新中',
            projectCrumb: '所属项目',
            projectCrumbAria: '返回所属项目 {name}',
            projectUnnamed: '未命名项目',
          },
          annotation: {
            showClosed: '显示已关闭批注',
            sidebarExpand: '展开批注栏',
            sidebarCollapse: '收起批注栏',
            sidebarToggle: '批注 {n}',
            sidebarToggleEmpty: '批注',
            sidebarToggleAria: '批注 {n}',
            orphaned: '原文已变更',
            degraded: '定位已降级',
            quotedSnapshot: '引用时的原文',
          },
          review: { approve: '通过方案', reject: '驳回修订', reviewRound: '第 {n} 轮审查' },
          status: { pending_review: '待人类审查', needs_clarification: '需要澄清' },
          version: { switcher: '版本', current: '当前' },
          thread: {
            kindAiClarification: 'AI 提问',
            kindAiReviewFinding: 'AI 审查',
            kindHumanComment: '人工评论',
            kindRepoConfirmation: '确认门',
            severityBlocker: '阻塞',
            severityWarning: '警告',
            severityInfo: '提示',
            severityNone: '—',
            groupOpen: '未决',
            groupAnswered: '已回答',
            groupClosed: '已关闭',
            authorAi: 'AI',
            reminded: '上次提醒：{time}',
            remindedWithCount: '已提醒 {n} 次 · 上次 {time}',
            waitingSince: '已等待 {days} 天',
            expiredBadge: '已到期',
            expiredHint: '已提醒 {n} 次仍无人应答，系统不再提醒；该问题仍未解决，随时可以回复。',
            gotoGate: '前往确认门',
          },
        },
      },
    },
  },
})

/** RouterLink 打桩成 `<a :href>`：本组件测试只验「链去哪」，不装整个 router。 */
const RouterLinkStub = {
  props: ['to'],
  template: '<a :href="typeof to === \'string\' ? to : to?.path"><slot /></a>',
}

function mountHeader(doc: Record<string, unknown> | null) {
  return mount(BlueprintViewerHeader, {
    // 用例刻意造**缺键 / 多余键**的 doc（旧数据、脏数据分支）⇒ 断言用不完整对象是必要的
    props: { currentStatus: 'pending_review', doc: doc as never },
    global: { plugins: [i18n], stubs: { RouterLink: RouterLinkStub } },
  })
}

function makeDoc(overrides: Record<string, unknown> = {}) {
  return {
    version_id: 'v1',
    version_no: 1,
    is_current: true,
    produced_by_ref: '',
    created_at: '2026-08-05T00:00:00+00:00',
    content: { meta: { title: '高三提分专项跨仓技术蓝图' } },
    quality: { citation_coverage: 1, ai_rejection_rate: null, human_edit_volume: null, clarification_rounds: null },
    knowledge_entity_id: 'blueprint:x',
    project_id: 'p-123',
    project_name: '高三提分专项',
    ...overrides,
  }
}

function daysAgo(days: number): string {
  return new Date(Date.now() - days * 86400000).toISOString()
}

function makeThread(overrides: Record<string, unknown> = {}) {
  return {
    thread_id: 't-1',
    kind: 'ai_clarification',
    severity: '',
    status: 'open',
    blocking: true,
    anchor_status: 'anchored',
    anchor: null,
    return_stage: '',
    created_at: daysAgo(9),
    options: [],
    last_reminded_at: daysAgo(1),
    reminder_count: 3,
    expired_at: daysAgo(1),
    messages: [],
    ...overrides,
  }
}

function mountCard(overrides: Record<string, unknown> = {}) {
  return mount(BlueprintThreadCard, {
    props: { thread: makeThread(overrides) as never },
    global: { plugins: [i18n] },
  })
}

describe('link-01 顶栏归属回跳', () => {
  it('⭐ 出面包屑并链到项目工作区，文案是项目名', () => {
    const wrapper = mountHeader(makeDoc())
    const crumb = wrapper.find(CRUMB)

    expect(crumb.exists()).toBe(true)
    expect(crumb.attributes('href')).toBe('/projects/p-123')
    expect(crumb.text()).toContain('高三提分专项')
  })

  it('⭐ 无归属 ⇒ 面包屑不存在于 DOM（不出死链）', () => {
    const wrapper = mountHeader(makeDoc({ project_id: null, project_name: '', content: { meta: {} } }))
    expect(wrapper.find(CRUMB).exists()).toBe(false)
  })

  it('⭐ 项目名为空时回落「未命名项目」，绝不回落成 UUID', () => {
    const wrapper = mountHeader(makeDoc({ project_name: '' }))
    const crumb = wrapper.find(CRUMB)

    expect(crumb.text()).toContain('未命名项目')
    expect(crumb.text()).not.toContain('p-123')
  })

  it('顶层键缺失时回落 content.meta.project_id（权威位置）', () => {
    const wrapper = mountHeader(
      makeDoc({ project_id: undefined, content: { meta: { project_id: 'p-meta' } } }),
    )
    expect(wrapper.find(CRUMB).attributes('href')).toBe('/projects/p-meta')
  })

  it('doc 为 null（首屏加载）⇒ 不渲染面包屑', () => {
    expect(mountHeader(null).find(CRUMB).exists()).toBe(false)
  })
})

describe('wait-03 等待态与到期可见性', () => {
  it('⭐ 到期线程出徽标与说明，但状态徽标仍是「未决」（到期 ≠ 已处置）', () => {
    const wrapper = mountCard()

    expect(wrapper.find(EXPIRED_BADGE).text()).toContain('已到期')
    expect(wrapper.find(EXPIRED_HINT).text()).toContain('仍未解决')
    // ⭐ 变异守卫：若哪次改动把「已到期」并进状态标签表，这条转红
    expect(wrapper.text()).toContain('未决')
  })

  it('等待态一行给出等待天数与提醒次数', () => {
    const line = mountCard().find(WAITING)

    expect(line.text()).toContain('已等待 9 天')
    expect(line.text()).toContain('已提醒 3 次')
  })

  it('未到期线程无到期徽标与说明', () => {
    const wrapper = mountCard({ expired_at: '', reminder_count: 1 })

    expect(wrapper.find(EXPIRED_BADGE).exists()).toBe(false)
    expect(wrapper.find(EXPIRED_HINT).exists()).toBe(false)
    expect(wrapper.find(WAITING).text()).toContain('已提醒 1 次')
  })

  it('已作答/已关闭线程不展示等待天数（等了多久无意义）', () => {
    const answered = mountCard({ status: 'answered', expired_at: '', last_reminded_at: null })
    expect(answered.find(WAITING).exists()).toBe(false)

    const resolved = mountCard({ status: 'resolved', expired_at: '', last_reminded_at: null })
    expect(resolved.find(WAITING).exists()).toBe(false)
  })

  it('⭐ 线程状态 open 但后端未给到期字段（旧数据）⇒ 不出到期面', () => {
    const wrapper = mountCard({ expired_at: undefined, reminder_count: undefined, last_reminded_at: null })

    expect(wrapper.find(EXPIRED_BADGE).exists()).toBe(false)
    expect(wrapper.find(WAITING).text()).toContain('已等待 9 天')
  })
})
