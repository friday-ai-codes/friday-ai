/**
 * 侧边栏「项目」导航项顺序守护测试（WS-01）。
 *
 * 以静态读取 AppSidebar.vue 源文本的方式断言 mainNavItems 中
 * `/projects` 入口位于 `/`（首页）之后、`/spaces`（空间）之前，
 * 不挂载组件以避开 auto-import / store 依赖，保证确定性守护不被回归。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// vitest 的 cwd 为 web/，从此处解析 AppSidebar.vue 源文件。
const sidebarPath = resolve(process.cwd(), 'src/components/layout/AppSidebar.vue')
const source = readFileSync(sidebarPath, 'utf-8')

describe('AppSidebar mainNavItems 顺序', () => {
  it('「项目」入口位于首页与空间之间', () => {
    const homeIdx = source.indexOf('{ to: \'/\',')
    const projectsIdx = source.indexOf('to: \'/projects\'')
    const spacesIdx = source.indexOf('to: \'/spaces\'')

    expect(homeIdx).toBeGreaterThanOrEqual(0)
    expect(projectsIdx).toBeGreaterThanOrEqual(0)
    expect(spacesIdx).toBeGreaterThanOrEqual(0)

    expect(homeIdx).toBeLessThan(projectsIdx)
    expect(projectsIdx).toBeLessThan(spacesIdx)
  })

  it('「项目」入口携带中文 label 与图标', () => {
    expect(source).toContain('label: \'项目\'')
    expect(source).toContain('icon: \'lucide--folder-kanban\'')
  })
})
