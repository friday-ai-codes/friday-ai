/**
 * Phase 115 的四条视觉 UAT（`115-VERIFICATION.md` frontmatter `human_verification`）。
 *
 * 这四条当初标 `human_verification` 的理由**全部是 happy-dom 的能力缺口**，不是真需要人来判断：
 *  1. mermaid 出图 —— 组件测试一律 `stubs: { MermaidDiagram: true }`，测不到真 SVG；
 *  2. 选区 popover 落点 —— happy-dom 无版面引擎，`Range.getBoundingClientRect()` 恒返零矩形；
 *  3. 左栏十段导航高亮跟随滚动 —— `AnchorNavLayout` 的 mount-only `IntersectionObserver` 需要真实版面；
 *  4. 响应式断点 —— happy-dom 不计算媒体查询。
 *
 * Chromium 有版面引擎、真 `getBoundingClientRect`、真 `IntersectionObserver`、真媒体查询，
 * 四条理由同时消解 ⇒ 在这里全部转成可判定断言。
 *
 * ⭐ **一律从用户入口驱动**：走 `/knowledge/blueprints/:id` 真实路由，用真实滚动 / 真实拖选 /
 * 真实改视口宽度，⛔ 不挂任何叶子组件 —— 组件层的 prop 契约已由 vitest 覆盖，这一层要兜的
 * 恰恰是「组件对了但版面上不成立」。
 *
 * ⚠️ 选择器一律写成 `[data-testid="…"]` 而**不是** `getByTestId()`：`playwright.config.ts` 把
 * `testIdAttribute` 设成了 `data-test`，而蓝图这批组件用的是 `data-testid`。
 */

import type { Locator, Page } from '@playwright/test'
import { expect, test } from '@playwright/test'
import { fulfillJson, installApi } from './support/api'
import {
  BLUEPRINT_ARTIFACT_ID,
  BLUEPRINT_SECTION_IDS,
  blueprintContent,
  blueprintDocument,
  blueprintEvents,
  blueprintSnapshot,
  blueprintThreads,
  flow,
  MERMAID_BROKEN_SOURCE,
} from './support/blueprintPayloads'

const VIEWER_URL = `/knowledge/blueprints/${BLUEPRINT_ARTIFACT_ID}`

/** `xl` 断点（Tailwind 默认 1280px）—— 与页面 `isWide` 的媒体查询字面量同值。 */
const XL = 1280
/** `md` 断点（Tailwind 默认 768px）—— 段导航「Select ↔ 横向 chips」的分界。 */
const MD = 768

/**
 * 段导航横条（头部 nav 插槽内的 chip 条）的 CSS 作用域。
 *
 * 布局整改（quick-260806）后左栏 `AnchorNavLayout` 不再被本页使用：段导航是
 * 随头部吸顶的横向 chip 条（`≥ md`），窄屏收成 Select 下拉。
 */
const ANCHOR_NAV = '[data-testid="blueprint-section-nav-chips"]'

interface ViewerOptions {
  /** 覆盖正文 `content`（默认十段齐全、`interaction_flows[0].mermaid` 是合法流程图）。 */
  content?: Record<string, unknown>
}

/**
 * 装好五个蓝图端点并打开查看器，等到十段容器全部就位。
 *
 * gate / 导出可用性两条**刻意回 404**：它们按 P-10 不进错误分档，404 只让对应挂载点不渲染，
 * 页面主链路照常 —— 这也顺带保证本文件的断言不被确认门面板挤动版面。
 */
async function openViewer(page: Page, options: ViewerOptions = {}): Promise<void> {
  await installApi(page, async ({ route, path, method }) => {
    if (method !== 'GET' || !path.includes(BLUEPRINT_ARTIFACT_ID))
      return false

    if (path.endsWith('/blueprint')) {
      await fulfillJson(route, blueprintDocument(
        options.content ? { content: options.content } : {},
      ))
      return true
    }
    if (path.endsWith('/blueprint/events')) {
      await fulfillJson(route, blueprintEvents())
      return true
    }
    // 节点快照（quick-260806 stepper）：无会话的 200 空结构 —— stepper 只按事件推状态，
    // 重跑面与版本树在本套视觉用例里不参与断言。
    if (path.endsWith('/blueprint/stages')) {
      await fulfillJson(route, {
        session_id: '',
        current_stage: '',
        session_status: '',
        run_label: '1',
        stage_rerun: null,
        stage_rerun_history: [],
        rerunnable_stages: [],
        stages: [],
        versions: [],
      })
      return true
    }
    if (path.endsWith('/blueprint-review/threads')) {
      await fulfillJson(route, blueprintThreads())
      return true
    }
    if (path.endsWith('/blueprint-review')) {
      await fulfillJson(route, blueprintSnapshot())
      return true
    }
    if (path.endsWith('/blueprint-gate') || path.includes('/export-feishu/')) {
      await fulfillJson(route, { detail: 'artifact 不存在' }, 404)
      return true
    }
    // 版本轨（既有交付物端点）：给一条当前版本，版本切换器不空。
    if (path === `/delivery/artifacts/${BLUEPRINT_ARTIFACT_ID}`) {
      await fulfillJson(route, { artifact_id: BLUEPRINT_ARTIFACT_ID, versions: [] })
      return true
    }
    return false
  })

  await page.goto(VIEWER_URL)
  await expect(page.locator('section[id]')).toHaveCount(BLUEPRINT_SECTION_IDS.length)
  // 正文落地后段内才从骨架切到实渲；等首段实渲再开始断言。
  await expect(page.locator('#requirement_spec [data-testid="blueprint-block"]').first()).toBeVisible()
}

// ─────────────────────────────────────────────────────────────────────────────
// UAT 1：mermaid 出图
// ─────────────────────────────────────────────────────────────────────────────

test.describe('UAT 115-1 mermaid 交互流程图在真实浏览器里出图', () => {
  test('合法源码渲染成 SVG 流程图，节点文字可见且不是源码原文', async ({ page }) => {
    await openViewer(page)

    const card = page.locator('[data-testid="blueprint-flow-card"]')
    await expect(card).toHaveCount(1)

    // ⭐ 断真 `<svg>`，⛔ 不是「组件收到了 code prop」（那层已由 vitest 覆盖）。
    const svg = card.locator('[data-testid="blueprint-block"] svg')
    await expect(svg).toHaveCount(1)
    await expect(svg).toBeVisible()

    // 出了图就必须有面积：mermaid 渲染失败时组件回退 <pre>，那条路径下这里会是 0。
    const box = await svg.boundingBox()
    expect(box).not.toBeNull()
    expect(box!.width).toBeGreaterThan(80)
    expect(box!.height).toBeGreaterThan(80)

    // 流程图的语义证据：节点文案出现在 SVG 内部，且 SVG 里真的有 path 连线。
    await expect(svg).toContainText('库存充足?')
    expect(await svg.locator('path').count()).toBeGreaterThan(0)

    // 出图态下不得同时留着源码 <pre>（`v-if="svg"` / `v-else` 二选一）。
    await expect(card.locator('pre')).toHaveCount(0)
    // 出图后「放大」入口才出现（`v-if="svg"`）。
    await expect(card.getByRole('button', { name: '放大' })).toBeVisible()
  })

  test('空源码不合成块 ⇒ 不留空 `<pre>`，也不留空的流程图容器', async ({ page }) => {
    await openViewer(page, {
      content: blueprintContent({
        interaction_flows: [
          flow({ id: 'flow_1', name: '无图流程' }), // 整个 mermaid 键缺席
          flow({ id: 'flow_2', name: '空串流程', mermaid: '   ' }), // 有键但全是空白
        ],
      }),
    })

    const cards = page.locator('[data-testid="blueprint-flow-card"]')
    await expect(cards).toHaveCount(2)

    // 两张卡都渲染了步骤表（证明段本身不是空的 ⇒ 下面的「零 pre」不是恒真）。
    await expect(page.locator('[data-testid="blueprint-flow-step"]')).toHaveCount(4)

    // ⭐ 核心断言（UAT 原文「空源码时不出现空 `<pre>`」）：一个 <pre> 都不许有。
    // `MermaidDiagram` 的 `v-else` 分支会把空 code 渲染成一个空 <pre>，所以「不出现」
    // 只能靠调用方（`InteractionFlowsSection.mermaidBlocks`）根本不合成这个块来保证。
    await expect(cards.locator('pre')).toHaveCount(0)
    await expect(cards.locator('[data-testid="blueprint-block"]')).toHaveCount(0)
    await expect(cards.locator('svg')).toHaveCount(0)
  })

  test('非法源码回退源码 `<pre>` + 提示（证明上一条的「零 pre」不是因为 pre 永不渲染）', async ({ page }) => {
    await openViewer(page, {
      content: blueprintContent({
        interaction_flows: [flow({ id: 'flow_1', name: '坏图流程', mermaid: MERMAID_BROKEN_SOURCE })],
      }),
    })

    const card = page.locator('[data-testid="blueprint-flow-card"]')
    await expect(card.locator('pre')).toHaveCount(1)
    await expect(card.locator('pre')).toContainText('graph TD')
    await expect(card).toContainText('无法渲染流程图，已展示源码')
    await expect(card.locator('[data-testid="blueprint-block"] svg')).toHaveCount(0)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// UAT 2：选区 popover 落点
// ─────────────────────────────────────────────────────────────────────────────

/** 在给定元素内拖选一段文字，返回选区在视口里的真实矩形与选中文本。 */
async function dragSelect(page: Page, target: Locator): Promise<{
  rect: { x: number, y: number, width: number, height: number }
  text: string
}> {
  const box = await target.boundingBox()
  if (!box)
    throw new Error('拖选目标没有版面盒子')

  const y = box.y + Math.min(10, box.height / 2)
  await page.mouse.move(box.x + 6, y)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.6, y, { steps: 12 })
  await page.mouse.up()

  return page.evaluate(() => {
    const selection = window.getSelection()!
    const r = selection.getRangeAt(0).getBoundingClientRect()
    return {
      rect: { x: r.x, y: r.y, width: r.width, height: r.height },
      text: selection.toString(),
    }
  })
}

test.describe('UAT 115-2 选区 popover 的落点与 Esc 行为', () => {
  test('popover 贴着选区出现、水平锚在选区上、且完全不遮挡被选文本', async ({ page }) => {
    await openViewer(page)

    const paragraph = page.locator('#requirement_spec [data-testid="blueprint-block"] p').first()
    const selected = await dragSelect(page, paragraph)
    expect(selected.text.length).toBeGreaterThan(4)
    // 真实版面引擎下选区矩形必须非零 —— 这正是 happy-dom 拿不到的那件东西。
    expect(selected.rect.width).toBeGreaterThan(0)
    expect(selected.rect.height).toBeGreaterThan(0)

    const popover = page.locator('[data-testid="blueprint-selection-popover"]')
    await expect(popover).toBeVisible()
    const pop = (await popover.boundingBox())!

    const sel = selected.rect
    // ① 不遮挡：两个矩形零交叠。
    const overlapX = Math.min(pop.x + pop.width, sel.x + sel.width) - Math.max(pop.x, sel.x)
    const overlapY = Math.min(pop.y + pop.height, sel.y + sel.height) - Math.max(pop.y, sel.y)
    expect(overlapX <= 0 || overlapY <= 0).toBe(true)

    // ② 贴着：竖直缝隙就是 `side-offset=8`，给 6px 余量吸收子像素。
    const gap = pop.y >= sel.y
      ? pop.y - (sel.y + sel.height)
      : sel.y - (pop.y + pop.height)
    expect(gap).toBeGreaterThanOrEqual(0)
    expect(gap).toBeLessThanOrEqual(14)

    // ③ ⭐ 锚在选区上而不是漂在视口角落：浮层中心与选区中心水平接近。
    //    零矩形退化（happy-dom 那种）会让浮层贴到左上角，这一条立刻转红。
    const popCenter = pop.x + pop.width / 2
    const selCenter = sel.x + sel.width / 2
    expect(Math.abs(popCenter - selCenter)).toBeLessThanOrEqual(24)

    // 可写蓝图 ⇒ 「发起评论」在场（`canComment = !readonly`）。
    await expect(page.locator('[data-testid="blueprint-selection-comment"]')).toBeVisible()
  })

  test('Esc 关闭浮层且保留选区（⛔ 不清 window.getSelection）', async ({ page }) => {
    await openViewer(page)

    const paragraph = page.locator('#requirement_spec [data-testid="blueprint-block"] p').first()
    const selected = await dragSelect(page, paragraph)

    const popover = page.locator('[data-testid="blueprint-selection-popover"]')
    await expect(popover).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(popover).toHaveCount(0)

    const after = await page.evaluate(() => window.getSelection()?.toString() ?? '')
    expect(after).toBe(selected.text)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// UAT 3：左栏十段导航高亮跟随滚动
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 左栏当前高亮项的下标。
 *
 * 判据取段导航高亮态独有的 `bg-primary/8`；同时校验那根指示条
 * （`v-if="activeSection === section.id"` 的绝对定位 span）与它同项 —— 两个来源不一致
 * 说明高亮态被改成了两套判定，直接抛错而不是静默取其一。
 */
async function activeNavIndex(page: Page): Promise<number> {
  return page.evaluate((navSelector) => {
    const buttons = Array.from(document.querySelectorAll<HTMLElement>(`${navSelector} button`))
    if (buttons.length === 0)
      throw new Error('段导航一个按钮都没找到')
    const byClass = buttons.findIndex(b => b.className.includes('bg-primary/8'))
    const byMarker = buttons.findIndex(b => b.querySelector('span.absolute'))
    if (byClass !== byMarker)
      throw new Error(`高亮态两个来源不一致：class=${byClass} marker=${byMarker}`)
    return byClass
  }, ANCHOR_NAV)
}

/** 把某个段滚到观察窗内（观察窗是视口的 15%~45%，见 `rootMargin`）。 */
async function scrollSectionIntoView(page: Page, sectionId: string): Promise<void> {
  await page.evaluate((id) => {
    const el = document.getElementById(id)
    if (!el)
      throw new Error(`段容器不存在：${id}`)
    window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 120, behavior: 'instant' as ScrollBehavior })
  }, sectionId)
}

test.describe('UAT 115-3 十段导航高亮跟随滚动', () => {
  test('十段全部挂上 observer：逐段滚动时高亮逐段推进，⛔ 不停在第一段', async ({ page }) => {
    await openViewer(page)

    const navButtons = page.locator(`${ANCHOR_NAV} button`)
    await expect(navButtons).toHaveCount(BLUEPRINT_SECTION_IDS.length)
    await expect(navButtons.first()).toBeVisible()

    // 初始停在第一段。
    expect(await activeNavIndex(page)).toBe(0)

    // ⭐ 逐段滚过去，记录每一段实际点亮的下标。
    const observed: number[] = []
    for (const [index, sectionId] of BLUEPRINT_SECTION_IDS.entries()) {
      await scrollSectionIntoView(page, sectionId)
      await expect
        .poll(() => activeNavIndex(page), { message: `段 ${sectionId} 未点亮左栏第 ${index} 项` })
        .toBe(index)
      observed.push(await activeNavIndex(page))
    }

    // 非恒真对照：真的走遍了十段，而不是「一直是 0」也能过。
    expect(observed).toEqual([...BLUEPRINT_SECTION_IDS.keys()])
  })

  test('回滚到顶部高亮退回第一段（双向跟随，不是单调前进的假象）', async ({ page }) => {
    await openViewer(page)

    await scrollSectionIntoView(page, 'must_haves')
    await expect.poll(() => activeNavIndex(page)).toBe(BLUEPRINT_SECTION_IDS.indexOf('must_haves'))

    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior }))
    await expect.poll(() => activeNavIndex(page)).toBe(0)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// UAT 4：响应式断点
// ─────────────────────────────────────────────────────────────────────────────

/** 当前**可见**的线程侧栏实例数（常驻栏 + 抽屉两处一起数）。 */
async function visibleSidebarCount(page: Page): Promise<number> {
  const column = page.locator('[data-testid="blueprint-sidebar-column"]:visible')
  const sheet = page.locator('[data-testid="blueprint-sidebar-sheet"]:visible')
  return (await column.count()) + (await sheet.count())
}

test.describe('UAT 115-4 三栏在 xl / md 两档断点下的收拢', () => {
  test('≥ xl：常驻线程侧栏可见，抽屉整块不在 DOM ⇒ 侧栏实例恰好一份', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await openViewer(page)

    await expect(page.locator('[data-testid="blueprint-sidebar-column"]')).toBeVisible()
    // ⭐ 不是「藏起来」而是**根本不渲染**（reka-ui 的焦点陷阱会锁进不可见容器）。
    await expect(page.locator('[data-testid="blueprint-sidebar-sheet"]')).toHaveCount(0)
    expect(await visibleSidebarCount(page)).toBe(1)

    // ⭐ 宽屏的批注入口是顶栏折叠开关（「查看批注」按钮 `xl:hidden`，只服务窄屏抽屉）。
    //    收起 → 常驻栏整块摘除；再展开 → 恢复恰好一份，⛔ 任何时刻不出现第二份。
    await page.locator('[data-testid="blueprint-header-sidebar-toggle"]').click()
    expect(await visibleSidebarCount(page)).toBe(0)
    await page.locator('[data-testid="blueprint-header-sidebar-toggle"]').click()
    expect(await visibleSidebarCount(page)).toBe(1)
  })

  test('< xl：常驻栏被 CSS 收起，抽屉承接 ⇒ 打开后仍恰好一份', async ({ page }) => {
    await page.setViewportSize({ width: XL - 1, height: 900 })
    await openViewer(page)

    // 常驻栏还在 DOM 里（`hidden xl:flex`），但不可见。
    await expect(page.locator('[data-testid="blueprint-sidebar-column"]')).toBeHidden()
    expect(await visibleSidebarCount(page)).toBe(0)

    await page.locator('[data-testid="blueprint-header-open-annotations"]').click()
    await expect(page.locator('[data-testid="blueprint-sidebar-sheet"]')).toBeVisible()
    // ⭐ 落点核心：抽屉开着时常驻栏依旧不可见 ⇒ 任何宽度下可见实例都 ≤ 1。
    await expect(page.locator('[data-testid="blueprint-sidebar-column"]')).toBeHidden()
    expect(await visibleSidebarCount(page)).toBe(1)
  })

  test('断点两侧连续切换：宽 → 窄 → 宽，可见侧栏实例始终不超过一份', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await openViewer(page)
    expect(await visibleSidebarCount(page)).toBe(1)

    // 拉窄：常驻栏收起；页面 `watch(isWide)` 会顺手收掉抽屉 ⇒ 不会「自己弹回来」。
    await page.setViewportSize({ width: 1024, height: 900 })
    await expect(page.locator('[data-testid="blueprint-sidebar-column"]')).toBeHidden()
    expect(await visibleSidebarCount(page)).toBeLessThanOrEqual(1)

    await page.locator('[data-testid="blueprint-header-open-annotations"]').click()
    await expect(page.locator('[data-testid="blueprint-sidebar-sheet"]')).toBeVisible()
    expect(await visibleSidebarCount(page)).toBe(1)

    // 拉回宽屏：抽屉必须整块消失（`v-if="!isWide"`），常驻栏接手。
    await page.setViewportSize({ width: 1440, height: 900 })
    await expect(page.locator('[data-testid="blueprint-sidebar-sheet"]')).toHaveCount(0)
    await expect(page.locator('[data-testid="blueprint-sidebar-column"]')).toBeVisible()
    expect(await visibleSidebarCount(page)).toBe(1)
  })

  test('< md：段导航收成 Select 下拉，≥ md 换横向 chips（两档互斥、恰好一份段导航）', async ({ page }) => {
    await page.setViewportSize({ width: MD - 1, height: 900 })
    await openViewer(page)

    await expect(page.locator(ANCHOR_NAV)).toBeHidden()
    await expect(page.locator('[data-testid="blueprint-section-nav-select"]')).toBeVisible()

    // ⭐「收拢」的可判定内核：收拢不成立时多栏会把正文顶出视口宽度，产生横向滚动条。
    const overflow = await page.evaluate(() => {
      const el = document.documentElement
      return el.scrollWidth - el.clientWidth
    })
    expect(overflow).toBeLessThanOrEqual(1)

    // 对照：≥ md 时两档互换，⛔ 不会同时在场。
    await page.setViewportSize({ width: 1024, height: 900 })
    await expect(page.locator(ANCHOR_NAV)).toBeVisible()
    await expect(page.locator('[data-testid="blueprint-section-nav-select"]')).toBeHidden()
  })
})
