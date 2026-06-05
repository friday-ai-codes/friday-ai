import type { Page } from '@playwright/test'
import { expect, test } from '@playwright/test'

async function mockUnauthenticatedApi(page: Page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())

    if (!url.pathname.startsWith('/api/')) {
      await route.continue()
      return
    }

    const path = url.pathname.replace(/^\/api/, '').replace(/\/$/, '')

    if (path === '/auth/me' || path === '/auth/refresh') {
      await route.fulfill({
        status: 401,
        json: { detail: 'Unauthenticated' },
      })
      return
    }

    if (path === '/oidc/providers/public') {
      await route.fulfill({ json: [] })
      return
    }

    await route.fulfill({ json: { results: [] } })
  })
}

test.describe('Authentication shell', () => {
  test.beforeEach(async ({ page }) => {
    await mockUnauthenticatedApi(page)
  })

  test('redirects private routes to the login page', async ({ page }) => {
    await page.goto('/')

    await expect(page).toHaveURL(/\/login/)
    await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
    await expect(page.getByPlaceholder('请输入用户名')).toBeVisible()
    await expect(page.getByPlaceholder('请输入密码')).toBeVisible()
  })

  test('renders the public login form', async ({ page }) => {
    await page.goto('/login')

    await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
    await expect(page.getByText('登录您的 Friday AI 账户')).toBeVisible()
    await expect(page.getByRole('button', { name: '登录' })).toBeVisible()
  })
})
