import process from 'node:process'
import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright e2e 配置。
 *
 * 运行模型与 `tests/e2e/auth.spec.ts` 既有约定一致：**只起 Vite dev server，
 * 不起 Django、不连数据库**，全部后端响应用 `page.route('**\/api\/**')` 拦截。
 * 这些用例验证的是「给定这份后端载荷，界面呈现是否成立」——载荷形状由后端用例
 * 锁定，前端这一侧 mock 才能保持无副作用、可重复、秒级。
 *
 * 端口刻意避开 `vite.config.ts` 的 10240（`strictPort: true`）：开发者本地
 * dev server 常年占着那个口，撞上会直接启动失败而不是排队。
 */
const PORT = Number(process.env.E2E_PORT ?? 10250)
const BASE_URL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${PORT}`

export default defineConfig({
  testDir: './tests/e2e',
  // 断言超时给足：首屏要等 Vite 按需编译整条 chat 链路（首次访问 3~10s 不罕见）。
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  // CI 上禁用 test.only，防止「只跑一条却全绿」的假通过。
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],

  use: {
    baseURL: BASE_URL,
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    // 全局固定成浅色：需要暗色的用例自己开 `colorScheme: 'dark'` 的 context，
    // 免得宿主机的系统主题偷偷改变断言前提。
    colorScheme: 'light',
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: {
    // `--no-open` + `BROWSER=none`：无头跑用例时不要弹出宿主机浏览器。
    command: `BROWSER=none pnpm exec vite --port ${PORT} --strictPort --no-open`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: 'ignore',
    stderr: 'pipe',
  },
})
