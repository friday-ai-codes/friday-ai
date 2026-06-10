import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitepress'
import { groupIconMdPlugin, groupIconVitePlugin } from 'vitepress-plugin-group-icons'
import llmstxt from 'vitepress-plugin-llms'

const __dirname = dirname(fileURLToPath(import.meta.url))
const apiSidebarPath = resolve(__dirname, 'api-sidebar.json')

function loadApiSidebar() {
  if (existsSync(apiSidebarPath)) {
    return JSON.parse(readFileSync(apiSidebarPath, 'utf-8'))
  }

  return [{ text: 'API Reference', items: [{ text: 'Overview', link: '/api/' }] }]
}

export default defineConfig({
  title: 'Friday AI',
  description: '开源 AI 开发自动化平台 — 把需求自动推进到可审查的代码变更',
  lang: 'zh-CN',
  // GitHub Pages 项目站点需要 /friday-ai/ 前缀，本地开发保持 /
  base: process.env.DOCS_BASE || '/',
  lastUpdated: true,
  ignoreDeadLinks: [/^https?:\/\/localhost/],
  markdown: {
    config(md) {
      md.use(groupIconMdPlugin)
    },
  },
  vite: {
    plugins: [
      groupIconVitePlugin(),
      // 构建时生成 llms.txt / llms-full.txt，方便 AI 助手读取整站文档
      llmstxt(),
    ],
  },
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: `${process.env.DOCS_BASE || '/'}favicon.svg` }],
    ['meta', { name: 'theme-color', content: '#14b8a6' }],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:title', content: 'Friday AI' }],
    ['meta', { property: 'og:description', content: '开源 AI 开发自动化平台 — 把需求自动推进到可审查的代码变更' }],
  ],
  themeConfig: {
    logo: { light: '/logo-mark.svg', dark: '/logo-mark-dark.svg' },
    siteTitle: 'Friday AI',
    nav: [
      { text: '指南', link: '/guide/introduction', activeMatch: '^/guide/' },
      { text: '部署', link: '/deploy/', activeMatch: '^/deploy/' },
      { text: '核心技术', link: '/internals/', activeMatch: '^/internals/' },
      { text: '集成', link: '/integrations/feishu', activeMatch: '^/integrations/' },
      { text: 'API', link: '/api/', activeMatch: '^/api/' },
      { text: '贡献', link: '/contributing/', activeMatch: '^/contributing/' },
    ],
    sidebar: {
      '/guide/': [
        {
          text: '开始使用',
          items: [
            { text: '什么是 Friday AI', link: '/guide/introduction' },
            { text: '快速开始', link: '/guide/quick-start' },
          ],
        },
        {
          text: '使用 Friday',
          items: [
            { text: '工作流指南', link: '/guide/workflows' },
            { text: 'Friday Codebase Agent', link: '/guide/friday-codebase-agent' },
          ],
        },
        {
          text: '管理',
          items: [{ text: '管理指南', link: '/guide/admin' }],
        },
      ],
      '/deploy/': [
        {
          text: '部署',
          items: [
            { text: '部署总览', link: '/deploy/' },
            { text: 'Docker Compose 部署', link: '/deploy/docker-compose' },
            { text: 'Helm / Kubernetes 部署', link: '/deploy/helm' },
            { text: '源码与本地开发', link: '/deploy/source' },
            { text: '环境变量参考', link: '/deploy/configuration' },
          ],
        },
      ],
      '/internals/': [
        {
          text: '核心技术',
          items: [
            { text: '架构总览', link: '/internals/' },
            { text: '工作流引擎', link: '/internals/workflow-engine' },
            { text: 'Runner 与 Task 执行器', link: '/internals/runner' },
            { text: '代码智能层（Graph RAG）', link: '/internals/code-intelligence' },
            { text: '安全模型', link: '/internals/security' },
          ],
        },
      ],
      '/integrations/': [
        {
          text: '集成与扩展',
          items: [
            { text: '飞书集成', link: '/integrations/feishu' },
            { text: 'Agent Skills', link: '/integrations/skills' },
            { text: 'MCP Server', link: '/integrations/mcp' },
            { text: 'Codebase Agent 指南', link: '/guide/friday-codebase-agent' },
          ],
        },
      ],
      '/contributing/': [
        {
          text: '贡献',
          items: [{ text: '贡献指南', link: '/contributing/' }],
        },
      ],
      '/api/': loadApiSidebar(),
    },
    socialLinks: [
      { icon: 'github', link: 'https://github.com/friday-ai-codes/friday-ai' },
      { icon: 'npm', link: 'https://www.npmjs.com/package/@friday-ai-codes/mcp' },
    ],
    editLink: {
      pattern: 'https://github.com/friday-ai-codes/friday-ai/edit/main/docs/:path',
      text: '在 GitHub 上编辑此页',
    },
    footer: {
      message: '基于 MIT License 发布',
      copyright: `Copyright © ${new Date().getFullYear()} friday-ai-codes`,
    },
    outline: { level: 'deep', label: '本页目录' },
    docFooter: { prev: '上一篇', next: '下一篇' },
    lastUpdatedText: '最后更新',
    darkModeSwitchLabel: '外观',
    sidebarMenuLabel: '菜单',
    returnToTopLabel: '回到顶部',
    search: {
      provider: 'local',
      options: {
        translations: {
          button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
          modal: {
            noResultsText: '没有找到结果',
            resetButtonTitle: '清除搜索条件',
            footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' },
          },
        },
      },
    },
  },
})
