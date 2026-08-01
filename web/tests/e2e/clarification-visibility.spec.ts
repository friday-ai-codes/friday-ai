/**
 * UAT 107-5：会话处于 `waiting_clarification` 时，这件事对用户是不是可见的。
 *
 * 107 未新增前端面，承载者是既有的 `ChatStatusBar` + `ClarificationCard`。
 * 这条用例走「刷新 / 切回会话」这条真实路径：runtime 回一个
 * `active + phase=waiting_clarification + pending_clarification`，看用户能不能
 * 在页面上看到「在等我回答」和那张卡。
 */
import { expect, test } from '@playwright/test'
import { installApi } from './support/api'
import {
  CONVERSATION_ID,
  conversationDetail,
  idleRuntime,
  userMessage,
} from './support/payloads'

const PENDING_CLARIFICATION = {
  clarification_id: 'clar-e2e-1',
  question: '验证码是只在登录页启用，还是注册页也一起加？',
  options: [
    { id: 'opt-login', label: '只在登录页', hint: '改动面最小' },
    { id: 'opt-both', label: '登录页 + 注册页' },
  ],
  allow_freeform: true,
}

test.describe('UAT 107-5 澄清等待态的用户可见性', () => {
  test('waiting_clarification 在状态条与澄清卡两处都可见，且给得出跳过出口', async ({ page }) => {
    await installApi(page, async ({ route, path, method }) => {
      if (method === 'GET' && path === `/chat/conversations/${CONVERSATION_ID}`) {
        await route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify(conversationDetail([
            userMessage('msg-user', '给登录页加图形验证码'),
          ])),
        })
        return true
      }
      if (method === 'GET' && path.endsWith('/runtime')) {
        await route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify(idleRuntime({
            active: true,
            status: 'waiting_clarification',
            phase: 'waiting_clarification',
            pending_clarification: PENDING_CLARIFICATION,
          })),
        })
        return true
      }
      return false
    })

    await page.goto(`/chat?conversation=${CONVERSATION_ID}`)

    // ① 状态条：告诉用户「在等你」，而不是「正在生成」
    await expect(page.getByText('等待你在上方卡片中确认...')).toBeVisible()

    // ② 澄清卡：问题正文 + 待回复徽标 + 可点的选项
    await expect(page.getByText('还需要确认一下')).toBeVisible()
    await expect(page.getByText('待回复')).toBeVisible()
    await expect(page.getByText(PENDING_CLARIFICATION.question)).toBeVisible()
    for (const opt of PENDING_CLARIFICATION.options)
      await expect(page.getByRole('radio').filter({ hasText: opt.label })).toBeVisible()

    // ③ 兜底出口：卡片漏发时不至于永久卡死
    await expect(page.getByRole('button', { name: '跳过，直接回答' })).toBeVisible()
  })

  test('无待回复澄清时不出现澄清卡与等待文案（负向对照）', async ({ page }) => {
    await installApi(page, async ({ route, path, method }) => {
      if (method === 'GET' && path === `/chat/conversations/${CONVERSATION_ID}`) {
        await route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify(conversationDetail([userMessage('msg-user', '你好')])),
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
    await expect(page.getByText('你好')).toBeVisible()
    await expect(page.getByText('还需要确认一下')).toHaveCount(0)
    await expect(page.getByText('等待你在上方卡片中确认...')).toHaveCount(0)
  })
})
