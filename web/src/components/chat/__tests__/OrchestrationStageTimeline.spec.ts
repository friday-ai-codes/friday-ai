/**
 * 110-06：OrchestrationStageTimeline.vue 单元测试。
 *
 * 🔴 挂载**真实组件，并连真实 `SubStepTimeline` 一起挂载**，只 stub 到 `Badge` 这一层
 * UI 原语。理由是 109-REVIEW HI-01 的教训：那次用 stub 顶掉了内嵌的真实组件，于是
 * 「透传的 props 够不够真实组件跑起来」在 240 行全绿的 spec 里完全不可见。本 spec 若
 * stub 掉 `SubStepTimeline`，「`interactive=false` 是否真的生效」「失败行是否真的有
 * `role="alert"`」两条就全是空断言。
 *
 * 折叠逻辑之外的规则（六态、可选步、七套摘要、计数幂等、闭集回退）已由 110-05 的
 * composable spec 穷举覆盖，本 spec **只测 DOM 与交互**，不重复。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import OrchestrationStageTimeline from '~/components/chat/OrchestrationStageTimeline.vue'
import SubStepTimeline from '~/components/execution/dag/SubStepTimeline.vue'
import { useChatStore } from '~/stores/chat'

/** 兜底用例的开关：为 true 时让 `buildOrchestrationTimeline` 抛。 */
const throwOnBuild = vi.hoisted(() => ({ value: false }))

vi.mock('~/composables/useOrchestrationTimeline', async (importOriginal) => {
  const actual = await importOriginal<typeof import('~/composables/useOrchestrationTimeline')>()
  return {
    ...actual,
    buildOrchestrationTimeline: (input: any) => {
      if (throwOnBuild.value)
        throw new Error('build blew up')
      return actual.buildOrchestrationTimeline(input)
    },
  }
})

const StubBadge = defineComponent({
  name: 'Badge',
  props: ['variant'],
  setup(props, { slots }) {
    return () => h('span', { 'data-test': 'badge', 'data-variant': props.variant }, slots.default?.())
  },
})

const SESSION = 'sess-1'
const OTHER_SESSION = 'sess-2'

const CARD = '[data-test="orchestration-stage-timeline"]'
const TOGGLE = '[data-test="timeline-toggle"]'
const COUNT = '[data-test="timeline-step-count"]'
const TITLE = '[data-test="timeline-title"]'
/** 步骤行选择器：与 `SubStepTimeline.spec.ts` 同一套（三个类均未改动）。 */
const ROW = '.relative.flex.items-start.gap-2'

type Snapshot = Record<string, any>

function snapshot(overrides: Snapshot = {}): Snapshot {
  return {
    session_id: SESSION,
    status: 'running',
    current_stage: 'recall',
    has_classify: false,
    segment_count: null,
    events: [],
    events_truncated: false,
    ...overrides,
  }
}

function event(name: string, ts: string, payload: Record<string, unknown> = {}) {
  return { event: name, ts, payload }
}

function seedBucket(
  sessionId: string,
  bucket: { snapshot?: Snapshot | null, events?: Array<ReturnType<typeof event>> } = {},
) {
  const store = useChatStore()
  store.orchestrationSessions[sessionId] = {
    sessionId,
    snapshot: (bucket.snapshot ?? null) as any,
    events: (bucket.events ?? []) as any,
    eventsTruncated: false,
  }
  return store
}

function mountTimeline(sessionId: string, options: Record<string, any> = {}) {
  return mount(OrchestrationStageTimeline as any, {
    props: { sessionId },
    global: { stubs: { Badge: StubBadge } },
    ...options,
  })
}

/** 正文区是否渲染：正文里唯一的东西就是真实的 `SubStepTimeline`。 */
/**
 * 正文区对用户是否可见。
 *
 * 🔴 判据是**可见性**而不是存在性：正文用 `v-show` 常驻（否则按钮上的 `aria-controls`
 * 在收起态会指向一个已从 DOM 移除的节点）。若这里退回 `.exists()`，「已折叠」这一组
 * 断言会全部恒真、把折叠逻辑坏掉也测不出来。
 */
function bodyRendered(wrapper: ReturnType<typeof mountTimeline>): boolean {
  const body = wrapper.findComponent(SubStepTimeline)
  if (!body.exists())
    return false
  const host = wrapper.find('[data-test="timeline-toggle"]').attributes('aria-controls')
  const style = host ? wrapper.find(`[id="${host}"]`).attributes('style') : undefined
  return !(style ?? '').includes('display: none')
}

let errorSpy: ReturnType<typeof vi.spyOn>
let warnSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  throwOnBuild.value = false
  setActivePinia(createPinia())
  errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
})

afterEach(() => {
  expect(errorSpy).not.toHaveBeenCalled()
  expect(warnSpy).not.toHaveBeenCalled()
  vi.restoreAllMocks()
})

describe('orchestrationStageTimeline · 渲染条件（§A.5 三条）', () => {
  it('桶不存在 ⇒ 整块不渲染，且不打 warn / error', () => {
    useChatStore()
    const wrapper = mountTimeline(SESSION)
    expect(wrapper.find(CARD).exists()).toBe(false)
  })

  it('桶存在但 events 空且 snapshot 为 null ⇒ 不渲染（不画全 pending 的空壳）', () => {
    seedBucket(SESSION, { snapshot: null, events: [] })
    const wrapper = mountTimeline(SESSION)
    expect(wrapper.find(CARD).exists()).toBe(false)
  })

  it('桶里有 1 条事件（快照尚未到达）⇒ 渲染', () => {
    seedBucket(SESSION, { snapshot: null, events: [event('decomposed', '2026-01-01T00:00:00Z')] })
    const wrapper = mountTimeline(SESSION)
    expect(wrapper.find(CARD).exists()).toBe(true)
  })

  it('只有快照、没有事件 ⇒ 渲染', () => {
    seedBucket(SESSION, { snapshot: snapshot() })
    const wrapper = mountTimeline(SESSION)
    expect(wrapper.find(CARD).exists()).toBe(true)
  })

  it('sessionId 传空串 ⇒ 不渲染、不抛', () => {
    seedBucket(SESSION, { snapshot: snapshot() })
    expect(() => mountTimeline('')).not.toThrow()
    expect(mountTimeline('').find(CARD).exists()).toBe(false)
  })

  it('根节点带 role=group 与 aria-label，class 含 card / mt-2 / animate-fade-in', () => {
    seedBucket(SESSION, { snapshot: snapshot() })
    const card = mountTimeline(SESSION).find(CARD)
    expect(card.attributes('role')).toBe('group')
    expect(card.attributes('aria-label')).toBe('方案编排进度')
    expect(card.classes()).toEqual(expect.arrayContaining(['card', 'mt-2', 'animate-fade-in']))
  })
})

describe('orchestrationStageTimeline · 卡头三态与步数', () => {
  it('在途 ⇒ 标题「正在生成技术方案」', () => {
    seedBucket(SESSION, { snapshot: snapshot({ status: 'running' }) })
    expect(mountTimeline(SESSION).find(TITLE).text()).toBe('正在生成技术方案')
  })

  it('done ⇒ 标题「方案编排已完成」（时间线自身就是完成信号）', () => {
    seedBucket(SESSION, { snapshot: snapshot({ status: 'done', current_stage: 'merge' }) })
    expect(mountTimeline(SESSION).find(TITLE).text()).toBe('方案编排已完成')
  })

  it('failed ⇒ 标题「方案编排失败」', () => {
    seedBucket(SESSION, {
      snapshot: snapshot({
        status: 'failed',
        current_stage: 'merge',
        failure: { stage: 'merge', reason_code: 'merge_validation_exhausted' },
      }),
    })
    expect(mountTimeline(SESSION).find(TITLE).text()).toBe('方案编排失败')
  })

  it('步数是纯文本计数「2/6 步」，不是 Badge —— 卡内 Badge 数量不因它增加', () => {
    seedBucket(SESSION, { snapshot: snapshot({ status: 'running', current_stage: 'recall' }) })
    const wrapper = mountTimeline(SESSION)
    const count = wrapper.find(COUNT)
    expect(count.text()).toBe('2/6 步')
    // 计数节点自身不是 Badge，且整卡零 Badge（本 fixture 无降级角标）
    expect(count.attributes('data-test')).not.toBe('badge')
    expect(wrapper.findAll('[data-test="badge"]')).toHaveLength(0)
  })
})

describe('orchestrationStageTimeline · 终态收敛（一次性语义）', () => {
  it('初次即 done ⇒ 正文区不渲染（已折叠），卡头仍在', () => {
    seedBucket(SESSION, { snapshot: snapshot({ status: 'done', current_stage: 'merge' }) })
    const wrapper = mountTimeline(SESSION)
    expect(wrapper.find(CARD).exists()).toBe(true)
    expect(bodyRendered(wrapper)).toBe(false)
    expect(wrapper.find(TOGGLE).attributes('aria-expanded')).toBe('false')
  })

  it('在途 → done ⇒ 自动折叠一次', async () => {
    const store = seedBucket(SESSION, { snapshot: snapshot({ status: 'running' }) })
    const wrapper = mountTimeline(SESSION)
    expect(bodyRendered(wrapper)).toBe(true)

    store.orchestrationSessions[SESSION].snapshot = snapshot({ status: 'done', current_stage: 'merge' }) as any
    await nextTick()
    expect(bodyRendered(wrapper)).toBe(false)
  })

  it('🔴 自动折叠 → 用户手动展开 → 再来一次 done 更新 ⇒ 仍保持展开（只折一次）', async () => {
    const store = seedBucket(SESSION, { snapshot: snapshot({ status: 'running' }) })
    const wrapper = mountTimeline(SESSION)

    store.orchestrationSessions[SESSION].snapshot = snapshot({ status: 'done', current_stage: 'merge' }) as any
    await nextTick()
    expect(bodyRendered(wrapper)).toBe(false)

    await wrapper.find(TOGGLE).trigger('click')
    expect(bodyRendered(wrapper)).toBe(true)

    // 又一次快照 / 事件到达（仍是 done）——不得把用户展开的选择抢走
    store.orchestrationSessions[SESSION].events.push(event('merged', '2026-01-01T00:00:09Z') as any)
    await nextTick()
    store.orchestrationSessions[SESSION].snapshot = snapshot({
      status: 'done',
      current_stage: 'merge',
      segment_count: 3,
    }) as any
    await nextTick()

    expect(bodyRendered(wrapper)).toBe(true)
    expect(wrapper.find(TOGGLE).attributes('aria-expanded')).toBe('true')
  })

  it('failed ⇒ 保持展开，且后续更新不会把它折起来', async () => {
    const failed = {
      status: 'failed',
      current_stage: 'merge',
      failure: { stage: 'merge', reason_code: 'merge_validation_exhausted' },
    }
    const store = seedBucket(SESSION, { snapshot: snapshot(failed) })
    const wrapper = mountTimeline(SESSION)
    expect(bodyRendered(wrapper)).toBe(true)

    store.orchestrationSessions[SESSION].snapshot = snapshot({ ...failed, segment_count: 4 }) as any
    await nextTick()
    expect(bodyRendered(wrapper)).toBe(true)
    expect(wrapper.find(TOGGLE).attributes('aria-expanded')).toBe('true')
  })

  it('sessionId 变化 ⇒ 折叠态与一次性 flag 重置（换到在途会话即展开）', async () => {
    seedBucket(SESSION, { snapshot: snapshot({ status: 'done', current_stage: 'merge' }) })
    seedBucket(OTHER_SESSION, { snapshot: snapshot({ session_id: OTHER_SESSION, status: 'running' }) })

    const wrapper = mountTimeline(SESSION)
    expect(bodyRendered(wrapper)).toBe(false)

    await wrapper.setProps({ sessionId: OTHER_SESSION })
    expect(bodyRendered(wrapper)).toBe(true)
    expect(wrapper.find(TITLE).text()).toBe('正在生成技术方案')
  })

  it('折叠态不做任何持久化：组件卸载重挂后按新会话状态重算', () => {
    seedBucket(SESSION, { snapshot: snapshot({ status: 'running' }) })
    const first = mountTimeline(SESSION)
    expect(bodyRendered(first)).toBe(true)
    first.unmount()

    const second = mountTimeline(SESSION)
    expect(bodyRendered(second)).toBe(true)
  })
})

describe('orchestrationStageTimeline · 可访问性', () => {
  it('卡内 [aria-live] 恰 1 个，文本等于 composable 的 liveMessage 且不含「/」', () => {
    seedBucket(SESSION, { snapshot: snapshot({ status: 'running', current_stage: 'research' }) })
    const wrapper = mountTimeline(SESSION)

    const live = wrapper.findAll('[aria-live]')
    expect(live).toHaveLength(1)
    expect(live[0].attributes('role')).toBe('status')
    expect(live[0].attributes('aria-live')).toBe('polite')
    expect(live[0].classes()).toContain('sr-only')
    expect(live[0].text()).toBe('当前阶段：并行调研')
    // 🔴 绝不把调研的 {done}/{total} 写进播报区（五个仓完成会连播五次）
    expect(live[0].text()).not.toContain('/')
  })

  it('done / failed 两个终态的播报文本同样不含「/」', async () => {
    const store = seedBucket(SESSION, { snapshot: snapshot({ status: 'done', current_stage: 'merge' }) })
    const wrapper = mountTimeline(SESSION)
    expect(wrapper.find('[aria-live]').text()).toBe('方案编排已完成')
    expect(wrapper.find('[aria-live]').text()).not.toContain('/')

    store.orchestrationSessions[SESSION].snapshot = snapshot({
      status: 'failed',
      current_stage: 'merge',
      failure: { stage: 'merge', reason_code: 'clarification_timeout_no_answer' },
    }) as any
    await nextTick()
    expect(wrapper.find('[aria-live]').text()).toBe('编排失败：融合 — 澄清超时且无人应答')
    expect(wrapper.find('[aria-live]').text()).not.toContain('/')
  })

  it('折叠按钮的 aria-expanded 随折叠切换，aria-controls 指向真实存在的节点', async () => {
    seedBucket(SESSION, { snapshot: snapshot({ status: 'running' }) })
    const wrapper = mountTimeline(SESSION)
    const toggle = wrapper.find(TOGGLE)

    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(toggle.attributes('aria-label')).toBe('收起编排进度')
    const bodyId = toggle.attributes('aria-controls')
    expect(bodyId).toBeTruthy()
    expect(wrapper.find(`[id="${bodyId}"]`).exists()).toBe(true)

    await toggle.trigger('click')
    expect(wrapper.find(TOGGLE).attributes('aria-expanded')).toBe('false')
    expect(wrapper.find(TOGGLE).attributes('aria-label')).toBe('展开编排进度')
    // 折叠后按钮**不被卸载**
    expect(wrapper.find(TOGGLE).exists()).toBe(true)
    // 🔴 正文区也不被卸载：v-show 而非 v-if，否则 aria-controls 在收起态指向一个
    // 已从 DOM 移除的节点（悬空）。这条断言此前锁的正是那个错误行为。
    expect(wrapper.find(`[id="${bodyId}"]`).exists()).toBe(true)
    expect(wrapper.find(`[id="${bodyId}"]`).attributes('style')).toContain('display: none')
  })

  it('🔴 失败摘要行有 role=alert，且 aria-live 属性不存在（一个事实播一次）', () => {
    seedBucket(SESSION, {
      snapshot: snapshot({
        status: 'failed',
        current_stage: 'merge',
        failure: { stage: 'merge', reason_code: 'merge_validation_exhausted' },
      }),
    })
    const wrapper = mountTimeline(SESSION)

    const alerts = wrapper.findAll('[role="alert"]')
    expect(alerts).toHaveLength(1)
    expect(alerts[0].text()).toBe('融合校验多次未通过')
    expect(alerts[0].attributes('aria-live')).toBeUndefined()
    // 卡内 aria-live 仍只有播报区那一处
    expect(wrapper.findAll('[aria-live]')).toHaveLength(1)
  })

  // 两条断言故意拆成两个 it：合成一个的话先失败的那条会挡住另一条，
  // 「点不动」与「看起来点不动」哪一条真的被守住就成了运气。
  it('步骤行非交互 ①：行 class 不含 cursor-pointer', () => {
    seedBucket(SESSION, { snapshot: snapshot({ status: 'running', current_stage: 'recall' }) })
    const rows = mountTimeline(SESSION).findAll(ROW)
    expect(rows.length).toBe(6)
    for (const row of rows)
      expect(row.classes()).not.toContain('cursor-pointer')
  })

  it('步骤行非交互 ②：点击任一步骤行都不 emit', async () => {
    seedBucket(SESSION, { snapshot: snapshot({ status: 'running', current_stage: 'recall' }) })
    const wrapper = mountTimeline(SESSION)

    const rows = wrapper.findAll(ROW)
    await rows[0].trigger('click')
    await rows[2].trigger('click')
    expect(wrapper.findComponent(SubStepTimeline).emitted('stepClick')).toBeUndefined()
    expect(wrapper.emitted('stepClick')).toBeUndefined()
  })

  it('卡内可聚焦元素恰 1 个（唯一 tab stop 是折叠按钮）', () => {
    seedBucket(SESSION, { snapshot: snapshot({ status: 'running' }) })
    const wrapper = mountTimeline(SESSION)
    const focusable = wrapper.findAll('button, a[href], input, select, textarea, [tabindex]')
    expect(focusable).toHaveLength(1)
    expect(focusable[0].attributes('data-test')).toBe('timeline-toggle')
  })

  it('自动折叠不移动焦点：焦点在折叠按钮上时，折叠后仍在该按钮', async () => {
    const store = seedBucket(SESSION, { snapshot: snapshot({ status: 'running' }) })
    const wrapper = mountTimeline(SESSION, { attachTo: document.body })

    const button = wrapper.find(TOGGLE).element as HTMLButtonElement
    button.focus()
    expect(document.activeElement).toBe(button)

    store.orchestrationSessions[SESSION].snapshot = snapshot({ status: 'done', current_stage: 'merge' }) as any
    await nextTick()

    expect(bodyRendered(wrapper)).toBe(false)
    expect(document.activeElement).toBe(button)
    wrapper.unmount()
  })
})

describe('orchestrationStageTimeline · 零自由文本 / 零泄漏', () => {
  it('未受控 reason_code ⇒ DOM 含「未知原因」且不含原始取值', () => {
    seedBucket(SESSION, {
      snapshot: snapshot({
        status: 'failed',
        current_stage: 'merge',
        failure: { stage: 'merge', reason_code: 'weird_unmapped' },
      }),
    })
    const wrapper = mountTimeline(SESSION)
    expect(wrapper.text()).toContain('未知原因')
    expect(wrapper.html()).not.toContain('weird_unmapped')
  })

  it('payload 里塞满自由文本（后端净化失效的最坏情形）⇒ 一个字都不上屏', () => {
    seedBucket(SESSION, {
      snapshot: snapshot({ status: 'running', current_stage: 'research' }),
      events: [
        event('clarification.asked', '2026-01-01T00:00:01Z', {
          clarification_id: 'c-1',
          question: 'FREE_TEXT_QUESTION_XYZ',
        }),
        event('repo.research.started', '2026-01-01T00:00:02Z', { repo_id: 'r-1' }),
        event('repo.research.completed', '2026-01-01T00:00:03Z', {
          repo_id: 'r-1',
          summary: 'FREE_TEXT_SUMMARY_XYZ',
          candidate_files: ['FREE_TEXT_FILE_XYZ'],
        }),
        event('repo.research.failed', '2026-01-01T00:00:04Z', {
          repo_id: 'r-2',
          error: 'FREE_TEXT_ERROR_XYZ',
        }),
      ],
    })
    const html = mountTimeline(SESSION).html()
    expect(html).not.toContain('FREE_TEXT_QUESTION_XYZ')
    expect(html).not.toContain('FREE_TEXT_SUMMARY_XYZ')
    expect(html).not.toContain('FREE_TEXT_FILE_XYZ')
    expect(html).not.toContain('FREE_TEXT_ERROR_XYZ')
  })

  /**
   * §D.1 修订（RELY-03 缺口闭环）。
   *
   * 本用例原先断言「全文**不含**降级解释句」——依据是那句话归 `RoutingDecisionPanel`。
   * 该组件 2026-05-29 起就没有挂载点，而编排链路上没有第二块显示候选与置信度的面，
   * 于是这条断言实际锁住的是「用户只能看到两个字」。角标标位置、横幅说人话，两者
   * 现在都在本卡；「候选仓列表 / 分数 / 进入编码」仍然归他处，那半边断言保留。
   */
  it('🔴 degraded=true ⇒ 路由行有 warning 角标，且卡内给出降级解释句', () => {
    seedBucket(SESSION, {
      snapshot: snapshot({ status: 'running', current_stage: 'research' }),
      events: [
        event('repo.routing', '2026-01-01T00:00:01Z', {
          candidates: [{ repository_id: 'r-1' }, { repository_id: 'r-2' }],
          degraded: true,
          degrade_reason: 'timeout',
        }),
      ],
    })
    const wrapper = mountTimeline(SESSION)

    const badges = wrapper.findAll('[data-test="badge"]')
    expect(badges).toHaveLength(1)
    expect(badges[0].text()).toBe('降级')
    expect(badges[0].attributes('data-variant')).toBe('warning')

    const banner = wrapper.find('[data-test="timeline-degraded-banner"]')
    expect(banner.exists()).toBe(true)
    expect(banner.attributes('role')).toBe('alert')
    expect(banner.text()).toContain('本次未经 LLM 推理，置信度仅供参考')
    expect(banner.text()).toContain('降级原因：上游超时')
    // 卡内**只有**这一个 live region（§A.6）：横幅不得再挂 aria-live
    expect(banner.attributes('aria-live')).toBeUndefined()

    // 归他处的事实仍然不进本卡
    expect(wrapper.text()).not.toContain('进入编码')
  })

  it('🔴 degraded 缺席（v1_fallback 之外的普通路径）⇒ 无角标也无横幅', () => {
    seedBucket(SESSION, {
      snapshot: snapshot({ status: 'running', current_stage: 'research' }),
      events: [
        event('repo.routing', '2026-01-01T00:00:01Z', {
          candidates: [{ repository_id: 'r-1' }],
        }),
      ],
    })
    const wrapper = mountTimeline(SESSION)
    expect(wrapper.findAll('[data-test="badge"]')).toHaveLength(0)
    expect(wrapper.find('[data-test="timeline-degraded-banner"]').exists()).toBe(false)
  })

  it('🔴 闭集外的 degrade_reason 回退「未知原因」，绝不回显原始值', () => {
    seedBucket(SESSION, {
      snapshot: snapshot({ status: 'running', current_stage: 'research' }),
      events: [
        event('repo.routing', '2026-01-01T00:00:01Z', {
          candidates: [{ repository_id: 'r-1' }],
          degraded: true,
          degrade_reason: 'TimeoutError: upstream leaked SECRET_XYZ',
        }),
      ],
    })
    const banner = mountTimeline(SESSION).find('[data-test="timeline-degraded-banner"]')
    expect(banner.text()).toContain('降级原因：未知原因')
    expect(banner.text()).not.toContain('SECRET_XYZ')
    expect(banner.text()).not.toContain('TimeoutError')
  })

  it('组件源码零 v-html', () => {
    const source = readFileSync(
      resolve(__dirname, '../OrchestrationStageTimeline.vue'),
      'utf-8',
    )
    const offending = source
      .split('\n')
      .filter(line => line.includes('v-html'))
      .filter(line => !/^\s*(?:\/\/|\*|<!--)/.test(line))
    expect(offending).toEqual([])
  })
})

describe('orchestrationStageTimeline · 兜底（观测不反噬业务）', () => {
  it('buildOrchestrationTimeline 抛异常 ⇒ 整块不渲染、不上抛、不打 warn', () => {
    seedBucket(SESSION, { snapshot: snapshot({ status: 'running' }) })
    throwOnBuild.value = true

    let wrapper: ReturnType<typeof mountTimeline> | null = null
    expect(() => {
      wrapper = mountTimeline(SESSION)
    }).not.toThrow()
    expect(wrapper!.find(CARD).exists()).toBe(false)
  })
})
