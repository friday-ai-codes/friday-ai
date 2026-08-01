/**
 * UAT 106-4：管理页 RAG tab「仓库路由权重」区的交互与渲染。
 *
 * 该区在里程碑内零单测（MN-05 deferred），这套用例是它的第一份自动化证据。
 * 入口是真实的 `/admin` 页面 + 真实 tab 切换，不单独挂组件。
 */
import type { Page } from '@playwright/test'
import { expect, test } from '@playwright/test'
import { installApi } from './support/api'
import { weightConfig, weightConfigRejection } from './support/payloads'

const WEIGHT_CONFIG_PATH = '/settings/repo-router/weight-config'

interface WeightMockOptions {
  /** PUT 的响应：'ok' 走保存成功回读，数组则回 400 + errors。 */
  putResult?: 'ok' | string[]
}

async function openRagTab(page: Page, options: WeightMockOptions = {}) {
  let getCount = 0
  const saved: unknown[] = []

  const api = await installApi(page, async ({ route, path, method }) => {
    if (path !== WEIGHT_CONFIG_PATH)
      return false

    if (method === 'GET') {
      getCount += 1
      // 第二次 GET = 保存后的回读，回一份带新版本号、非默认态的配置。
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify(
          getCount === 1
            ? weightConfig()
            : weightConfig({ weight_set_version: 'phase106-v3', is_default: false }),
        ),
      })
      return true
    }

    if (method === 'PUT') {
      saved.push(JSON.parse(route.request().postData() ?? '{}'))
      if (Array.isArray(options.putResult)) {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify(weightConfigRejection(options.putResult)),
        })
        return true
      }
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify(weightConfig({ weight_set_version: 'phase106-v3', is_default: false })),
      })
      return true
    }
    return false
  })

  await page.goto('/admin')
  await page.getByRole('button', { name: 'RAG 设置' }).click()
  // 同一 tab 下还有向量索引 / 精排两个区，各自也有「保存设置」按钮 ——
  // 全部断言都锁在本区的 section 内，避免误点邻居。
  const section = page.locator('section').filter({
    has: page.getByRole('heading', { name: '仓库路由权重' }),
  })
  await expect(section).toBeVisible()
  return { api, saved, section, save: section.getByRole('button', { name: '保存设置' }) }
}

/** reka-ui Select：点开 trigger → 在弹出的 listbox 里点选项。 */
async function pickWeight(page: Page, key: string, label: string) {
  await page.locator(`#repo-router-weight-${key}`).click()
  await page.getByRole('option', { name: label, exact: true }).click()
}

const PREVALIDATION = '保存前请修正以下问题'

test.describe('UAT 106-4 仓库路由权重设置区', () => {
  test('五权重下拉渲染当前值、常数可编辑、T2 停用 facet 可多选', async ({ page }) => {
    const { section } = await openRagTab(page)

    // 五个信号权重各一个下拉，回显后端当前值
    for (const [key, value] of Object.entries({
      text: '0.55',
      domain: '0.15',
      activity: '0.12',
      stack: '0.08',
      team: '0.05',
    })) {
      await expect(page.locator(`#repo-router-weight-${key}`)).toContainText(value)
    }

    // 常数是可编辑输入框（不是只读展示）
    const nCap = page.locator('#repo-router-const-n_cap')
    await expect(nCap).toHaveValue('6')
    await expect(nCap).toBeEditable()

    // T2 停用 facet：两项可选、默认未勾
    await expect(page.locator('#repo-router-t2-disabled-domain')).not.toBeChecked()
    await expect(page.locator('#repo-router-t2-disabled-stack')).not.toBeChecked()
    await page.locator('#repo-router-t2-disabled-stack').check()
    await expect(page.locator('#repo-router-t2-disabled-stack')).toBeChecked()

    // 默认态标注
    await expect(section.getByText('当前为内置默认值')).toBeVisible()
  })

  test('INV-R2 文本主导预校验拦截非法输入，并禁用保存', async ({ page }) => {
    const { save } = await openRagTab(page)

    // 把文本证据压到 0.05，业务域升到 0.55 —— 文本不再是最大项
    await pickWeight(page, 'text', '0.05')
    await pickWeight(page, 'domain', '0.55')

    const box = page.getByText(PREVALIDATION).locator('xpath=../..')
    await expect(box).toBeVisible()
    await expect(box).toContainText('「文本证据」权重必须是所有信号中的最大项（文本主导不变量 INV-R2）')
    await expect(box).toContainText('文本证据必须占主导（INV-R2）')
    await expect(save).toBeDisabled()
  })

  test('校准区间预校验拦截 c_lo >= c_hi', async ({ page }) => {
    const { save } = await openRagTab(page)

    await page.locator('#repo-router-const-s_top_c_hi').fill('0.1')
    const box = page.getByText(PREVALIDATION).locator('xpath=../..')
    await expect(box).toContainText('S_top 校准区间非法：c_lo 必须小于 c_hi')
    await expect(save).toBeDisabled()

    // 改回合法值后提示消失、保存恢复可用
    await page.locator('#repo-router-const-s_top_c_hi').fill('0.6')
    await expect(page.getByText(PREVALIDATION)).toHaveCount(0)
    await expect(save).toBeEnabled()
  })

  test('后端 400 的 errors 逐条显示', async ({ page }) => {
    // 这两条是 `validate_weight_config` 的真实产出（对同一份非法配置实跑取得）
    const errors = [
      'constants.n_cap=0.5 非法：n_cap 必须 >= 1',
      'constants.half_life_days=-1.0 非法：half_life_days 必须 > 0',
    ]
    const { save } = await openRagTab(page, { putResult: errors })

    // 前端预校验只校「是不是有效数值」，这两个值能过前端、被后端拒绝
    await page.locator('#repo-router-const-n_cap').fill('0.5')
    await page.locator('#repo-router-const-half_life_days').fill('-1')
    await save.click()

    const box = page.getByText('后端校验未通过').locator('xpath=../..')
    await expect(box).toBeVisible()
    for (const err of errors)
      await expect(box).toContainText(err)
  })

  test('保存成功后提示「下一次路由立即生效」并回读后端规范化结果', async ({ page }) => {
    const { saved, save, section } = await openRagTab(page)

    await pickWeight(page, 'domain', '0.10')
    await page.locator('#repo-router-weight-version').fill('phase106-v3')
    await save.click()

    await expect(page.getByText('仓库路由权重已保存，下一次路由立即生效，无需发版')).toBeVisible()

    // 回读：版本号换成后端返回的值、默认态标注消失
    await expect(page.locator('#repo-router-weight-version')).toHaveValue('phase106-v3')
    await expect(section.getByText('当前为内置默认值')).toHaveCount(0)

    // PUT 载荷不得携带 is_default（后端拒绝未知顶层键）
    expect(saved).toHaveLength(1)
    expect(saved[0]).not.toHaveProperty('is_default')
    expect((saved[0] as { weights: Record<string, number> }).weights.domain).toBe(0.1)
  })
})
