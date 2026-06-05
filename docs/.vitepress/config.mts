import { defineConfig } from 'vitepress'
import { readFileSync, existsSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

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
  description: 'Open-source development automation with AI agents and workflows',
  lang: 'en-US',
  ignoreDeadLinks: [/^https?:\/\/localhost/],
  themeConfig: {
    nav: [
      { text: 'Home', link: '/' },
      { text: 'Guide', link: '/guide/quick-start' },
      { text: 'API', link: '/api/' },
    ],
    sidebar: {
      '/guide/': [
        {
          text: 'Getting Started',
          items: [{ text: 'Quick Start', link: '/guide/quick-start' }],
        },
        {
          text: 'Workflows',
          collapsed: true,
          items: [
            { text: 'Workflow Guide', link: '/guide/workflows' },
            { text: 'Friday Codebase Agent', link: '/guide/friday-codebase-agent' },
          ],
        },
        {
          text: 'Administration',
          collapsed: true,
          items: [{ text: 'Admin Guide', link: '/guide/admin' }],
        },
      ],
      '/api/': loadApiSidebar(),
    },
    search: {
      provider: 'local',
    },
  },
})
