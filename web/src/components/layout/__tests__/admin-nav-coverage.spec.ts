/**
 * 守卫：admin 页面必须有导航入口，或显式登记豁免理由。
 *
 * 背景：侧边栏的 adminNavItems 是 AppSidebar.vue 里的硬编码数组，而路由由
 * unplugin-vue-router 按文件系统自动注册。两者不联动——往 src/pages/admin/ 加页面
 * 只会得到可访问的 URL，不会得到入口。git-credentials（Plan 26-04 REPO-01）与
 * artifact-types 就是这么变成「功能完整但用户找不到」的：路由、i18n、admin 守卫
 * 全齐，唯独漏了往数组里加一行，且没有任何检查会发现。
 *
 * 本测试用文件系统扫描对账，新增 admin 页面时要么加入口、要么在下面写明豁免理由。
 */
import { readdirSync, readFileSync } from 'node:fs'
import path, { posix } from 'node:path'
import { describe, expect, it } from 'vitest'

const PAGES_DIR = path.resolve(__dirname, '../../../pages')
const SIDEBAR = path.resolve(__dirname, '../AppSidebar.vue')

/**
 * 有意不进侧边栏的 admin 页面 —— 每条必须写清替代入口在哪。
 * 加条目前先自问：用户真的能找到它吗？找不到就该进侧边栏而不是进这个名单。
 */
const INTENTIONALLY_UNLISTED: Record<string, string> = {
  '/admin/providers': '由 Chat 的「供应商缺失」卡片 CTA 跳入，属上下文相关入口而非常驻导航',
  '/admin/oidc': '重定向页，指向 /admin#oidc 锚点',
  '/admin/observability/alerts': '运维监控子页，从 /admin/observability 页内 Tab 进入',
  '/admin/observability/logs': '运维监控子页，从 /admin/observability 页内 Tab 进入',
}

/** 从文件路径推出路由（对齐 unplugin-vue-router 的文件系统约定）。 */
function toRoute(relPath: string): string {
  return `/${relPath}`
    .replace(/\.vue$/, '')
    .replace(/\/index$/, '')
}

/** 递归收集目录下的 .vue 文件，返回相对 baseDir 的 posix 路径。 */
function collectVueFiles(dir: string, baseDir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = posix.join(dir, entry.name)
    if (entry.isDirectory())
      return collectVueFiles(full, baseDir)
    return entry.name.endsWith('.vue') ? [posix.relative(baseDir, full)] : []
  })
}

describe('admin 导航覆盖', () => {
  const sidebarSource = readFileSync(SIDEBAR, 'utf-8')

  const adminRoutes = collectVueFiles(posix.join(PAGES_DIR, 'admin'), PAGES_DIR)
    // components/ 下是页面私有子组件，不是路由
    .filter(p => !p.includes('/components/'))
    // 动态段（如 feedback/[id].vue）是详情页，从列表页进入
    .filter(p => !p.includes('['))
    .map(toRoute)
    .filter(r => r !== '/admin') // 根页自身就是「系统设置」入口

  it('扫描到的 admin 页面数量合理（防 glob 写错导致空跑假绿）', () => {
    expect(adminRoutes.length).toBeGreaterThanOrEqual(8)
  })

  it.each(adminRoutes)('%s 有侧边栏入口或已登记豁免', (route) => {
    const inSidebar = sidebarSource.includes(`'${route}'`)
    const exempted = route in INTENTIONALLY_UNLISTED

    expect(
      inSidebar || exempted,
      `${route} 既不在 AppSidebar 的 adminNavItems 里，也未登记豁免理由。\n`
      + '页面能通过 URL 访问不等于用户找得到它——请往 adminNavItems 加一行，\n'
      + '或在本文件的 INTENTIONALLY_UNLISTED 里写明替代入口。',
    ).toBe(true)
  })

  it('豁免名单不含已经进了侧边栏的路由（避免名单腐化）', () => {
    const stale = Object.keys(INTENTIONALLY_UNLISTED).filter(r => sidebarSource.includes(`'${r}'`))
    expect(stale, `这些路由已在侧边栏，应从豁免名单移除：${stale.join(', ')}`).toEqual([])
  })

  it('豁免名单不含已删除的页面（避免名单腐化）', () => {
    const ghosts = Object.keys(INTENTIONALLY_UNLISTED).filter(r => !adminRoutes.includes(r))
    expect(ghosts, `这些豁免项对应的页面已不存在：${ghosts.join(', ')}`).toEqual([])
  })
})
