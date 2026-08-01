/**
 * UAT 105-3 / 107-2：路由结果面在浏览器里的真实可达性与呈现。
 *
 * 全部断言从**用户入口**出发：打开会话 → 展开「分析过程」→ 展开「仓库分级路由」
 * 那一步，再看候选清单。这与既有 vitest 契约测试（routingCandidateSurface.spec.ts）
 * 的取证层不同：那一层挂的是 `ChatMessageBubble`，这一层挂的是真实路由 + 真实页面
 * + 真实 CSS，能顺带兜住「组件在，但页面上点不到 / 被样式吃掉」这一类失守。
 */
import type { Page } from '@playwright/test'
import type { RelevanceSeed } from './support/payloads'
import { expect, test } from '@playwright/test'
import { installApi } from './support/api'
import {
  CONVERSATION_ID,
  conversationDetail,
  idleRuntime,
  relevanceMessage,
  userMessage,
} from './support/payloads'

const GROUPED: RelevanceSeed = {
  block_order: ['in_project', 'global'],
  candidates: [
    {
      repository_id: 'r-in',
      repository_name: 'onion-web',
      score: 0.91,
      level: 'high',
      evidence: '命中登录模块与表单校验',
      group: 'in_project',
      breakdown: { text: 0.7, breadth: 0.11, activity: 0.1 },
    },
    {
      repository_id: 'r-out',
      repository_name: 'sso-gateway',
      score: 0.62,
      level: 'medium',
      evidence: '命中验证码签发接口',
      group: 'global',
      breakdown: { text: 0.5, domain: 0.12 },
    },
  ],
}

/** 打开会话并走两次点击把候选清单展开；任一步点不开即失败。 */
async function openRoutingDetail(page: Page, seed: RelevanceSeed) {
  await installApi(page, async ({ route, path, method }) => {
    if (method === 'GET' && path === `/chat/conversations/${CONVERSATION_ID}`) {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify(conversationDetail([
          userMessage('msg-user', '给登录页加图形验证码'),
          relevanceMessage(seed),
        ])),
      })
      return true
    }
    if (method === 'GET' && path.endsWith('/runtime')) {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(idleRuntime()) })
      return true
    }
    return false
  })

  await page.goto(`/chat?conversation=${CONVERSATION_ID}`)

  const processHead = page.locator('.tpg-head')
  await expect(processHead).toBeVisible()
  await processHead.click()

  const toolRow = page.locator('.tpg-row--tool .tpg-row-head').first()
  await expect(toolRow).toBeVisible()
  await toolRow.click()

  await expect(page.getByTestId('routing-candidate-list')).toBeVisible()
}

test.describe('UAT 105-3 / 107-2 路由结果面（对话过程面板 → 仓库分级路由）', () => {
  test('105-3：分数分解为中文信号名、3 位小数等宽右对齐、合计行等于总分', async ({ page }) => {
    await openRoutingDetail(page, GROUPED)

    const toggles = page.getByTestId('routing-breakdown-toggle')
    await expect(toggles).toHaveCount(2)
    // 默认收起
    await expect(page.getByTestId('routing-breakdown')).toHaveCount(0)
    await expect(toggles.first()).toHaveAttribute('aria-expanded', 'false')

    await toggles.first().click()
    const panel = page.getByTestId('routing-breakdown').first()
    await expect(panel).toBeVisible()
    await expect(toggles.first()).toHaveAttribute('aria-expanded', 'true')

    // 中文信号名而不是英文 key
    await expect(panel).toContainText('文本相关')
    await expect(panel).toContainText('命中广度')
    await expect(panel).toContainText('活跃度')
    await expect(panel).not.toContainText('breadth')

    // 三位小数 + 合计 == 总分（0.700 + 0.110 + 0.100 = 0.910）
    await expect(panel).toContainText('0.700')
    await expect(panel).toContainText('0.110')
    await expect(panel).toContainText('0.100')
    await expect(panel).toContainText('合计')
    await expect(panel).toContainText('0.910')

    // 等宽 + 右对齐是「一眼能竖着比大小」的前提，属于本项的可见判据
    const valueCell = panel.locator('span.font-mono').first()
    const style = await valueCell.evaluate(el => ({
      family: getComputedStyle(el).fontFamily,
      align: getComputedStyle(el).textAlign,
    }))
    expect(style.family.toLowerCase()).toContain('mono')
    expect(style.align).toBe('right')
  })

  test('105-3：无 breakdown 的历史 trace 不渲染展开入口，其余照常', async ({ page }) => {
    await openRoutingDetail(page, {
      block_order: ['in_project', 'global'],
      candidates: [{ ...GROUPED.candidates[0], breakdown: undefined }],
    })

    await expect(page.getByTestId('routing-candidate')).toHaveCount(1)
    await expect(page.getByTestId('routing-breakdown-toggle')).toHaveCount(0)
    await expect(page.getByTestId('routing-level-badge')).toContainText('高 0.91')
  })

  test('107-2：两组分区标题 + 组内计数，顺序取自后端 block_order', async ({ page }) => {
    await openRoutingDetail(page, GROUPED)

    const headings = page.getByTestId('routing-group-heading')
    await expect(headings).toHaveCount(2)
    await expect(headings.nth(0)).toContainText('本项目关联仓')
    await expect(headings.nth(0)).toContainText('（1）')
    await expect(headings.nth(1)).toContainText('全局候选')
    await expect(headings.nth(1)).toContainText('（1）')
  })

  test('107-2：全局组常驻跨组说明句 + 候选级「跨组」徽标（只挂全局那条）', async ({ page }) => {
    await openRoutingDetail(page, GROUPED)

    const note = page.getByTestId('routing-cross-group-note')
    await expect(note).toHaveCount(1)
    await expect(note).toHaveText('未关联当前平台，可能涉及跨组协作')
    // 常驻可见，不依赖 hover
    await expect(note).toBeVisible()

    const badges = page.getByTestId('routing-cross-group-badge')
    await expect(badges).toHaveCount(1)
    await expect(badges).toHaveAttribute('aria-label', '未关联当前平台，可能涉及跨组协作')
  })

  test('107-2：迟滞置顶提示条按「本项目组是否为空」换措辞', async ({ page }) => {
    await openRoutingDetail(page, { ...GROUPED, block_order: ['global', 'in_project'] })
    await expect(page.getByTestId('routing-promotion-notice')).toHaveText('更匹配的仓不在本项目关联范围内')
  })

  test('107-2：本项目组为空时置顶提示换成陈述句', async ({ page }) => {
    await openRoutingDetail(page, {
      block_order: ['global', 'in_project'],
      candidates: [GROUPED.candidates[1]],
    })
    await expect(page.getByTestId('routing-promotion-notice')).toHaveText('本项目关联范围内没有匹配的仓库')
  })

  test('107-2：降级时出 amber 横幅并把置信徽标灰化', async ({ page }) => {
    await openRoutingDetail(page, { ...GROUPED, degraded: true, degrade_reason: 'timeout' })

    const banner = page.getByTestId('routing-degraded-banner')
    await expect(banner).toBeVisible()
    await expect(banner).toContainText('本次未经 LLM 推理，置信度仅供参考')
    await expect(banner).toContainText('降级原因：上游超时')
    await expect(banner).toHaveAttribute('role', 'alert')
    // amber：断真实计算色而不是 class 名（class 名对不上时用户看到的是「没有告警色」）
    const borderColor = await banner.evaluate(el => getComputedStyle(el).borderTopColor)
    expect(borderColor).not.toBe('rgba(0, 0, 0, 0)')

    // 徽标灰化：level 文案不变，颜色不再宣称「高置信可信」
    const badge = page.getByTestId('routing-level-badge').first()
    await expect(badge).toContainText('高')
    const degradedBg = await badge.evaluate(el => getComputedStyle(el).backgroundColor)

    // 对照组：未降级同一条候选的徽标底色必须与灰化态不同
    await openRoutingDetail(page, GROUPED)
    const healthyBadge = page.getByTestId('routing-level-badge').first()
    const healthyBg = await healthyBadge.evaluate(el => getComputedStyle(el).backgroundColor)
    expect(degradedBg).not.toBe(healthyBg)
  })

  test('107-2：闭集外的降级原因回退「未知原因」，绝不回显原始值', async ({ page }) => {
    await openRoutingDetail(page, {
      ...GROUPED,
      degraded: true,
      degrade_reason: 'ConnectionResetError: upstream said <secret-token>',
    })
    const banner = page.getByTestId('routing-degraded-banner')
    await expect(banner).toContainText('降级原因：未知原因')
    await expect(banner).not.toContainText('secret-token')
    await expect(banner).not.toContainText('ConnectionResetError')
  })

  test('107-2：历史 trace（无 group / degraded 字段）平铺渲染，与改动前一致', async ({ page }) => {
    await openRoutingDetail(page, { candidates: GROUPED.candidates.map(c => ({ ...c, group: undefined })) })

    await expect(page.getByTestId('routing-candidate')).toHaveCount(2)
    await expect(page.getByTestId('routing-group-heading')).toHaveCount(0)
    await expect(page.getByTestId('routing-cross-group-note')).toHaveCount(0)
    await expect(page.getByTestId('routing-cross-group-badge')).toHaveCount(0)
    await expect(page.getByTestId('routing-degraded-banner')).toHaveCount(0)
    await expect(page.getByTestId('routing-promotion-notice')).toHaveCount(0)
  })
})
