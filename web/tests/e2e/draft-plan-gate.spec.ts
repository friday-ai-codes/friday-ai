/**
 * UAT 109-3 / 109-4：草稿方案的三块标注 + 阻断式确认弹层，以及 lark_md 方言
 * 在界面 markdown 下的呈现。
 *
 * 入口是真实链路：编排产出卡片 →「进入编码」→ 惰性投影 → 内嵌 TechPlanCard →
 * 选目标仓 →「确认编码」→ 弹层。不单挂 TechPlanCard。
 */
import type { Page } from '@playwright/test'
import { expect, test } from '@playwright/test'
import { installApi } from './support/api'
import {
  CONVERSATION_ID,
  conversationDetail,
  idleRuntime,
  orchestrationMessage,
  planResearchDoneResult,
  projectionResponse,
  userMessage,
} from './support/payloads'

interface Options {
  provenance?: string
  /** 收集 POST /chat/coding-plans/{id}/sessions/ 的请求体。 */
  sessionPayloads?: unknown[]
}

async function openOrchestratedPlan(page: Page, options: Options = {}) {
  const sessionPayloads = options.sessionPayloads ?? []

  await installApi(page, async ({ route, path, method }) => {
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
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(idleRuntime()) })
      return true
    }
    if (method === 'POST' && path === '/chat/coding-plans/from-artifact-version') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify(projectionResponse({ provenance: options.provenance ?? 'draft' })),
      })
      return true
    }
    if (method === 'POST' && path.endsWith('/sessions')) {
      sessionPayloads.push(JSON.parse(route.request().postData() ?? '{}'))
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          created: [{ session_id: 's-1', repository_id: 'r-in', branch_name: 'feat/captcha' }],
          failed: [],
        }),
      })
      return true
    }
    return false
  })

  await page.goto(`/chat?conversation=${CONVERSATION_ID}`)
  await expect(page.getByTestId('orchestrated-plan-card')).toBeVisible()
  await page.getByTestId('enter-coding').click()
  await expect(page.getByTestId('projected-hint')).toBeVisible()
  return { sessionPayloads }
}

test.describe('UAT 109-3 草稿标注与阻断式确认弹层', () => {
  test('草稿横幅在方案正文之前，且徽标折叠后仍可见', async ({ page }) => {
    await openOrchestratedPlan(page)

    const banner = page.getByTestId('unresearched-banner')
    await expect(banner).toBeVisible()
    await expect(banner).toContainText('本方案未经代码调研')
    await expect(banner).toHaveAttribute('role', 'alert')

    const badge = page.getByText('未经调研', { exact: true })
    await expect(badge).toBeVisible()

    // 横幅位置：在正文之前（用文档顺序断言，而不是靠肉眼）。
    // markdown 渲染器是异步初始化的，先等正文出现再比较顺序。
    await expect(page.locator('.prose').first()).toBeVisible()
    const bannerFirst = await page.evaluate(() => {
      const b = document.querySelector('[data-test="unresearched-banner"]')
      const prose = document.querySelector('.prose')
      if (!b || !prose)
        return null
      return !!(b.compareDocumentPosition(prose) & Node.DOCUMENT_POSITION_FOLLOWING)
    })
    expect(bannerFirst).toBe(true)

    // 折叠整张卡：横幅随正文收起，但常驻徽标必须还在
    await page.getByRole('button', { name: /需求：给登录页加图形验证码/ }).click()
    await expect(page.getByTestId('unresearched-banner')).toHaveCount(0)
    await expect(page.getByText('未经调研', { exact: true })).toBeVisible()
  })

  test('送编码前弹出阻断式弹层：必勾才能确认，label 点击生效，焦点困在弹层内', async ({ page }) => {
    const { sessionPayloads } = await openOrchestratedPlan(page)

    await page.getByRole('option', { name: /onion-web/ }).click()
    await page.getByRole('button', { name: '确认编码' }).click()

    // 🔴 用 role 而不是 `data-test="unresearched-dialog"`：那个属性挂在
    // `AlertDialogContent` 包装组件上，而它的根是 `AlertDialogPortal`（teleport 根），
    // 属性透传不到真实 DOM（控制台有对应的 Vue warn）。这是测试钩子失效，不是产品缺陷。
    const dialog = page.getByRole('alertdialog')
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('该方案未经代码调研')

    // 未勾选时确认按钮不可用（弹层是「阻断式」的落点）
    const confirm = page.getByTestId('ack-confirm')
    await expect(confirm).toBeDisabled()

    // 焦点陷阱：Tab 一圈焦点仍在弹层内
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press('Tab')
      const inside = await page.evaluate(() => {
        const d = document.querySelector('[role="alertdialog"]')
        return !!(d && document.activeElement && d.contains(document.activeElement))
      })
      expect(inside).toBe(true)
    }

    // label 点击生效：点文字（不是复选框本身）也能勾上
    await dialog.getByText('我已了解风险，仍要用该草稿送编码').click()
    await expect(page.getByTestId('ack-checkbox')).toHaveAttribute('aria-checked', 'true')
    await expect(confirm).toBeEnabled()

    await confirm.click()
    await expect(dialog).toHaveCount(0)

    // 用户签名只在勾选确认后才发出
    expect(sessionPayloads).toHaveLength(1)
    expect((sessionPayloads[0] as Record<string, unknown>).acknowledge_unresearched).toBe(true)
  })

  test('取消弹层则不发请求，且确认不跨次记忆（再打开时勾选被重置）', async ({ page }) => {
    const { sessionPayloads } = await openOrchestratedPlan(page)

    await page.getByRole('option', { name: /onion-web/ }).click()
    await page.getByRole('button', { name: '确认编码' }).click()
    await page.getByTestId('ack-checkbox').click()
    await expect(page.getByTestId('ack-confirm')).toBeEnabled()
    await page.getByTestId('ack-cancel').click()
    await expect(page.getByRole('alertdialog')).toHaveCount(0)
    expect(sessionPayloads).toHaveLength(0)

    // 再次触发：勾选必须回到未勾（确认不记忆）
    await page.getByRole('button', { name: '确认编码' }).click()
    await expect(page.getByRole('alertdialog')).toBeVisible()
    await expect(page.getByTestId('ack-confirm')).toBeDisabled()
  })

  test('编排产出（provenance=orchestrated）不标注、不弹层（负向对照）', async ({ page }) => {
    const { sessionPayloads } = await openOrchestratedPlan(page, { provenance: 'orchestrated' })

    await expect(page.getByTestId('unresearched-banner')).toHaveCount(0)
    await expect(page.getByText('未经调研', { exact: true })).toHaveCount(0)

    await page.getByRole('option', { name: /onion-web/ }).click()
    await page.getByRole('button', { name: '确认编码' }).click()
    await expect(page.getByRole('alertdialog')).toHaveCount(0)
    await expect.poll(() => sessionPayloads.length).toBe(1)
    // 不发送签名字段（「带了 ack」必须等价于「用户确实确认过」）
    expect(sessionPayloads[0]).not.toHaveProperty('acknowledge_unresearched')
  })
})

test.describe('UAT 109-4 lark_md 方言在界面 markdown 下的呈现', () => {
  test('项目符号渲染为字面 •，不是 markdown 列表，也没有裸「- 」', async ({ page }) => {
    await openOrchestratedPlan(page)

    const prose = page.locator('.prose').first()
    await expect(prose).toBeVisible()

    // ① 语义不丢：标题 / 分段 / 每条风险原文都在
    await expect(prose).toContainText('需求：给登录页加图形验证码')
    await expect(prose).toContainText('📋 执行计划（共 2 项）')
    await expect(prose).toContainText('⚠️ 兼容风险')
    await expect(prose).toContainText('老版本 App 未带 captcha 字段，需要灰度开关兜底')
    await expect(prose).toContainText('验证码服务不可用时需降级为短信验证')

    // ② 项目符号是字面 •
    const text = (await prose.textContent()) ?? ''
    expect(text).toContain('• 老版本 App 未带 captcha 字段，需要灰度开关兜底')
    expect(text).toContain('• 验证码服务不可用时需降级为短信验证')

    // ③ 没有把 `- ` 漏给用户，也没有渲染成 <ul>/<li>
    expect(text).not.toContain('- 老版本')
    expect(text).not.toMatch(/^-\s/m)
    await expect(prose.locator('ul')).toHaveCount(0)
    await expect(prose.locator('li')).toHaveCount(0)

    // ④ `**加粗**` 与 `> 引用` 走的是真 markdown（方言只影响列表）
    await expect(prose.locator('strong')).not.toHaveCount(0)
    await expect(prose.locator('blockquote')).not.toHaveCount(0)
    expect(text).not.toContain('**')
  })
})
