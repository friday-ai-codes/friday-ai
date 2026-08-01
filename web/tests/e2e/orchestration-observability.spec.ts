/**
 * UAT 110-1 / 110-2 / 110-4 / 110-5 / 110-6 / 110-7 / 110-8：编排过程可观测。
 *
 * 两条链分开取证，这是本文件的设计要点：
 * - 「直播链」用例（110-1 / 110-4 / 110-6）把**运行时快照链整个饿死**（runtime 恒回
 *   `active:false` 且不带 `orchestration`），于是界面上出现的每一格进度都只可能来自
 *   SSE `process_event`。若 `get_stream_writer()` 那条链静默失效，这些用例会红。
 * - 「快照链」用例（110-2 / 110-5 / 110-7 / 110-8）反过来只喂 runtime，不发 SSE。
 *
 * 已知残留：Playwright 的 `route.fulfill` 无法分帧下发，SSE 响应体是一次性交付的，
 * 因此本文件证明的是「事件到达即渲染、且早于任何一次轮询」，**不是**网络级的逐帧
 * 时序。真实分帧节奏仍需一次人工实跑，见 .planning/UAT-AUTOMATION-REPORT.md。
 */
import type { Page } from '@playwright/test'
import { expect, test } from '@playwright/test'
import { installApi } from './support/api'
import {
  CONVERSATION_ID,
  conversationDetail,
  idleRuntime,
  orchestrationMessage,
  orchestrationSnapshot,
  PLAN_SESSION_ID,
  planResearchDoneResult,
  planResearchSession,
  recallEvent,
  routingEvent,
  transition,
  userMessage,
} from './support/payloads'

// ---------------------------------------------------------------------------
// SSE 直播链
// ---------------------------------------------------------------------------

/** 后端 `format_sse` 的平铺信封：`{"type": event.type, **event.data}`。 */
function processEvent(event: string, payload: Record<string, unknown> = {}) {
  return {
    type: 'process_event',
    event,
    session_id: PLAN_SESSION_ID,
    ts: new Date(Date.parse('2026-08-01T00:00:00Z') + Math.random()).toISOString(),
    payload,
    run_id: 'run-e2e-1',
  }
}

function sseBody(events: Array<Record<string, unknown>>): string {
  return events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('')
}

/**
 * 打开会话并发一条消息，SSE 回放给定事件序列。
 * runtime 恒空 ⇒ 界面上出现的任何进度都只可能来自 SSE。
 */
async function sendWithSse(page: Page, events: Array<Record<string, unknown>>) {
  const api = await installApi(page, async ({ route, path, method }) => {
    if (method === 'GET' && path === `/chat/conversations/${CONVERSATION_ID}`) {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify(conversationDetail([])),
      })
      return true
    }
    if (method === 'GET' && path.endsWith('/runtime')) {
      // 🔴 快照链全程什么都不给：时间线要么由 SSE 点亮，要么一格都不亮。
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(idleRuntime()) })
      return true
    }
    if (method === 'POST' && path.endsWith('/stream')) {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-cache' },
        body: sseBody(events),
      })
      return true
    }
    return false
  })

  await page.goto(`/chat?conversation=${CONVERSATION_ID}`)
  const box = page.getByPlaceholder('给 Friday 发消息...')
  await expect(box).toBeVisible()
  await box.fill('给登录页加图形验证码')
  const sendButton = page.getByRole('button', { name: '发送' })
  await expect(sendButton).toBeEnabled()
  const startedAt = Date.now()
  await sendButton.click()
  return { api, startedAt }
}

/**
 * 编排工具的 tool_use part 开始。
 *
 * 🔴 必须走 `part_started` 而不是旧的 `tool_use_start`：`getChatPartsProtocol()`
 * 默认返回 `'new'`，此时 `handleSSEEvent` 会把 `tool_use_start` 直接丢掉。
 * 用错事件名的话时间线根本没有宿主 tool item，用例会以「什么都没渲染」失败 ——
 * 那是 fixture 形状错，不是产品缺陷。
 */
const TOOL_USE_START = {
  type: 'part_started',
  index: 0,
  run_id: 'run-e2e-1',
  part: {
    id: 'p-orch',
    index: 0,
    type: 'tool_use',
    tool_call_id: 'call-orch',
    name: 'start_plan_research',
    input: { requirement: '给登录页加图形验证码' },
    status: 'running',
  },
}

/** 时间线上某一步的行（SubStepTimeline 的 role=listitem）。 */
function step(page: Page, name: string) {
  return page.getByTestId('orchestration-stage-timeline')
    .getByRole('listitem')
    .filter({ hasText: name })
    .first()
}

test.describe('UAT 110-1 SSE 直播链：阶段推进随事件到达，不是 2 秒轮询节拍', () => {
  test('一次事件流内四个阶段全部推进完毕，且快照链全程为空', async ({ page }) => {
    const { api, startedAt } = await sendWithSse(page, [
      TOOL_USE_START,
      processEvent('decomposed'),
      processEvent('repo.routing', routingEvent('2026-08-01T00:00:01Z').payload),
      processEvent('routed'),
      processEvent('knowledge.recalling', recallEvent('2026-08-01T00:00:02Z', 12).payload),
      processEvent('recalled'),
      processEvent('classified'),
    ])

    // 澄清是第 5 步：四次转移之后指针停在这里
    await expect(step(page, '澄清')).toContainText('进行中')
    const elapsed = Date.now() - startedAt

    // 前四步全部完成 —— 若走 2 秒轮询节拍，四格至少要 6 秒才走得完
    for (const name of ['拆分', '路由', '召回'])
      await expect(step(page, name)).toContainText('已完成')
    expect(elapsed).toBeLessThan(2000)

    // 摘要来自事件 payload，进一步证明数据源是 SSE 而不是快照
    await expect(step(page, '路由')).toContainText('命中 2 个候选仓')
    await expect(step(page, '召回')).toContainText('召回 12 条相关知识')

    // 快照链确实没帮上忙：runtime 只在切会话时被调用过一次，且不含 orchestration
    expect(api.countOf('GET', '/runtime')).toBeLessThanOrEqual(1)
  })
})

test.describe('UAT 110-4 前半程失败：时间线立即标红，不需要刷新才自愈', () => {
  test('打断召回后该步标红并显示「未知原因」，标题转失败态', async ({ page }) => {
    await sendWithSse(page, [
      TOOL_USE_START,
      processEvent('decomposed'),
      processEvent('routed'),
      processEvent('process.session.failed'),
    ])

    await expect(page.getByTestId('timeline-title')).toHaveText('方案编排失败')

    const recall = step(page, '召回')
    await expect(recall).toContainText('失败')
    await expect(recall).toContainText('未知原因')

    // 不再持续显示「正在生成技术方案」
    await expect(page.getByText('正在生成技术方案')).toHaveCount(0)
  })

  test('未失败时同一条链路保持在途态（负向对照）', async ({ page }) => {
    await sendWithSse(page, [
      TOOL_USE_START,
      processEvent('decomposed'),
      processEvent('routed'),
    ])

    await expect(page.getByTestId('timeline-title')).toHaveText('正在生成技术方案')
    await expect(step(page, '召回')).toContainText('进行中')
    await expect(step(page, '召回')).not.toContainText('未知原因')
  })
})

test.describe('UAT 110-6 live region 播报节奏', () => {
  test('卡内 aria-live 恰 1 个，各仓完成不改播报内容', async ({ page }) => {
    await sendWithSse(page, [
      TOOL_USE_START,
      processEvent('decomposed'),
      processEvent('routed'),
      processEvent('recalled'),
      processEvent('classified'),
      processEvent('clarified'),
      // 五仓并行：起五个、依次完成
      ...['r1', 'r2', 'r3', 'r4', 'r5'].map(id =>
        processEvent('repo.research.started', { repo_id: id })),
      ...['r1', 'r2', 'r3', 'r4', 'r5'].map(id =>
        processEvent('repo.research.completed', { repo_id: id })),
    ])

    const card = page.getByTestId('orchestration-stage-timeline')
    await expect(card).toBeVisible()
    await expect(card.locator('[aria-live]')).toHaveCount(1)

    const live = page.getByTestId('timeline-live')
    await expect(live).toHaveText('当前阶段：并行调研')

    // 五仓完成确实被处理了（摘要里看得到），但播报文本没有跟着连播五次
    await expect(step(page, '并行调研')).toContainText('5/5 个仓库完成')
    await expect(live).toHaveText('当前阶段：并行调研')

    // 步数计数不得进入 live region（它每完成一仓就变一次）
    await expect(live).not.toContainText('步')
  })
})

// ---------------------------------------------------------------------------
// 运行时快照链
// ---------------------------------------------------------------------------

interface SnapshotOptions {
  active?: boolean
  snapshot?: Record<string, unknown>
  sessions?: unknown[]
}

/** 打开一条已产出编排结果的会话，进度只由 runtime 快照喂。 */
async function openWithRuntime(page: Page, options: SnapshotOptions) {
  const api = await installApi(page, async ({ route, path, method }) => {
    if (method === 'GET' && path === `/chat/conversations/${CONVERSATION_ID}`) {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify(conversationDetail([
          userMessage('msg-user', '给登录页加图形验证码'),
          orchestrationMessage(planResearchDoneResult()),
        ])),
      })
      return true
    }
    if (method === 'GET' && path.endsWith('/runtime')) {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify(idleRuntime({
          active: options.active ?? false,
          orchestration: options.snapshot ?? orchestrationSnapshot(),
          plan_research_sessions: options.sessions ?? [],
        })),
      })
      return true
    }
    return false
  })

  await page.goto(`/chat?conversation=${CONVERSATION_ID}`)
  await expect(page.getByTestId('orchestration-stage-timeline')).toBeVisible()
  return api
}

test.describe('UAT 110-2 plan_session_id 与 tool result session_id 的跨进程相等性', () => {
  test('两者逐字相等时，日志组出现在编排气泡内', async ({ page }) => {
    await openWithRuntime(page, {
      sessions: [
        planResearchSession('r-in', 'onion-web', 'RUNNING'),
        planResearchSession('r-out', 'sso-gateway', 'RUNNING'),
      ],
    })

    const group = page.getByTestId('plan-research-log-group')
    await expect(group).toBeVisible()
    await expect(page.getByTestId('plan-research-log-toggle')).toContainText('方案调研 · 2 个仓库')
    // 卡标题是仓库名，且没有裸 UUID 上屏
    await expect(group).toContainText('onion-web')
    await expect(group).toContainText('sso-gateway')
    await expect(group).not.toContainText(PLAN_SESSION_ID)
  })

  test('两者不等时日志组不出现（这是「时间线在跑、日志组永不出现」的第一嫌疑）', async ({ page }) => {
    await openWithRuntime(page, {
      sessions: [
        planResearchSession('r-in', 'onion-web', 'RUNNING', `${PLAN_SESSION_ID}x`),
        planResearchSession('r-out', 'sso-gateway', 'RUNNING', `${PLAN_SESSION_ID}x`),
      ],
    })

    // 时间线照常渲染 —— 说明会话本身是通的，缺的只是绑定键相等
    await expect(page.getByTestId('orchestration-stage-timeline')).toBeVisible()
    await expect(page.getByTestId('plan-research-log-group')).toHaveCount(0)
  })
})

test.describe('UAT 110-5 调研日志组折叠按钮的可访问名（WCAG 2.5.3）', () => {
  test('可访问名先组标题后动作，且 aria-controls 指向真实存在的节点', async ({ page }) => {
    await openWithRuntime(page, {
      sessions: [
        planResearchSession('r-in', 'onion-web', 'RUNNING'),
        planResearchSession('r-out', 'sso-gateway', 'RUNNING'),
        planResearchSession('r-3', 'pay-core', 'RUNNING'),
      ],
    })

    const toggle = page.getByTestId('plan-research-log-toggle')
    // 展开态：可见文案「方案调研 · 3 个仓库」必须**包含**在可访问名里（Label in Name）
    await expect(toggle).toHaveAccessibleName('方案调研 · 3 个仓库，收起方案调研日志')
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')

    // aria-controls 不悬空（收起态用的是 v-show，节点常驻）
    const controlsResolves = async () => page.evaluate(() => {
      const btn = document.querySelector('[data-test="plan-research-log-toggle"]')
      const id = btn?.getAttribute('aria-controls')
      return !!(id && document.getElementById(id))
    })
    expect(await controlsResolves()).toBe(true)

    await toggle.click()
    await expect(toggle).toHaveAccessibleName('方案调研 · 3 个仓库，展开方案调研日志')
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(await controlsResolves()).toBe(true)
  })
})

test.describe('UAT 110-7 skipped / unknown 空心点的形状差异', () => {
  /** 中断态快照：会话 running 但 runtime 不活跃 ⇒ 指针那步 unknown、澄清步 skipped。 */
  const INTERRUPTED = {
    active: false,
    snapshot: orchestrationSnapshot({
      status: 'running',
      current_stage: 'research',
      events: [
        transition('decomposed', '2026-08-01T00:00:01Z'),
        transition('routed', '2026-08-01T00:00:02Z'),
        transition('recalled', '2026-08-01T00:00:03Z'),
        transition('classified', '2026-08-01T00:00:04Z'),
        transition('clarified', '2026-08-01T00:00:05Z'),
      ],
    }),
  }

  for (const scheme of ['light', 'dark'] as const) {
    test(`${scheme} 主题下空心点与实心点在 DOM/计算样式层面确实不同`, async ({ browser }) => {
      const context = await browser.newContext({ colorScheme: scheme })
      const page = await context.newPage()
      await openWithRuntime(page, INTERRUPTED)

      // 文字侧的区分（不靠颜色也能读出来）
      await expect(step(page, '澄清')).toContainText('已跳过')
      await expect(step(page, '并行调研')).toContainText('进度未知')

      const dotStyle = async (name: string) => step(page, name)
        .locator('div.rounded-full')
        .first()
        .evaluate((el) => {
          const s = getComputedStyle(el)
          return { bg: s.backgroundColor, borderWidth: s.borderTopWidth, borderColor: s.borderTopColor }
        })

      const skipped = await dotStyle('澄清')
      const unknown = await dotStyle('并行调研')
      const completed = await dotStyle('拆分')

      // 空心：透明底 + 有边框
      for (const hollow of [skipped, unknown]) {
        expect(hollow.bg).toBe('rgba(0, 0, 0, 0)')
        expect(Number.parseFloat(hollow.borderWidth)).toBeGreaterThan(0)
      }
      // 实心：不透明底 + 无边框
      expect(completed.bg).not.toBe('rgba(0, 0, 0, 0)')
      expect(Number.parseFloat(completed.borderWidth)).toBe(0)

      await context.close()
    })
  }
})

test.describe('UAT 110-8 编排完成后的版面收敛', () => {
  const DONE = orchestrationSnapshot({
    status: 'done',
    current_stage: 'merge',
    events: [
      transition('decomposed', '2026-08-01T00:00:01Z'),
      transition('routed', '2026-08-01T00:00:02Z'),
      transition('recalled', '2026-08-01T00:00:03Z'),
      transition('clarified', '2026-08-01T00:00:04Z'),
      transition('research_complete', '2026-08-01T00:00:05Z'),
      transition('merged', '2026-08-01T00:00:06Z'),
    ],
  })
  const SETTLED_SESSIONS = [
    planResearchSession('r-in', 'onion-web', 'COMPLETED'),
    planResearchSession('r-out', 'sso-gateway', 'COMPLETED'),
  ]

  test('时间线收敛成一行、日志组自动收起、结果卡留在视口内', async ({ page }) => {
    await openWithRuntime(page, { snapshot: DONE, sessions: SETTLED_SESSIONS })

    // 时间线：标题转完成态、正文收起（卡头一行还在，不是整块消失）
    await expect(page.getByTestId('timeline-title')).toHaveText('方案编排已完成')
    await expect(page.getByTestId('timeline-toggle')).toHaveAttribute('aria-expanded', 'false')
    await expect(page.getByTestId('orchestration-stage-timeline')).toBeVisible()

    // 日志组：整组自动收起，但按钮本身仍在（可查）
    const logToggle = page.getByTestId('plan-research-log-toggle')
    await expect(logToggle).toBeVisible()
    await expect(logToggle).toHaveAttribute('aria-expanded', 'false')

    // 结果卡在视口内
    const card = page.getByTestId('orchestrated-plan-card')
    await expect(card).toBeInViewport()
  })

  test('用户手动展开日志组后，不被后到的轮询快照再次收走', async ({ page }) => {
    // active:true ⇒ 2 秒轮询持续到达；这正是「被抢回去」的那个触发条件
    await openWithRuntime(page, { active: true, snapshot: DONE, sessions: SETTLED_SESSIONS })

    const logToggle = page.getByTestId('plan-research-log-toggle')
    await expect(logToggle).toHaveAttribute('aria-expanded', 'false')
    await logToggle.click()
    await expect(logToggle).toHaveAttribute('aria-expanded', 'true')

    // 等两轮以上轮询（2s 一拍）
    await page.waitForTimeout(5000)
    await expect(logToggle).toHaveAttribute('aria-expanded', 'true')

    // 时间线同理：手动展开后不被自动折叠抢回
    const timelineToggle = page.getByTestId('timeline-toggle')
    await timelineToggle.click()
    await expect(timelineToggle).toHaveAttribute('aria-expanded', 'true')
    await page.waitForTimeout(3000)
    await expect(timelineToggle).toHaveAttribute('aria-expanded', 'true')
  })
})
