// VitePress 主配置文件
// 参考: https://vitepress.dev/reference/site-config
import { defineConfig } from 'vitepress'
export default defineConfig({
 title: 'Friday AI',
 description: 'AI 驱动的敏捷开发自动化系统',
 lang: 'zh-CN',
 // 排除中文文件名的旧文档，避免路由冲突
 srcExclude: [
 '**/技术原理*.md',
 '**/获取工作项*.md',
 '**/飞书项目*.md',
 '**/claude-code-docs.md',
 '**/migration/**',
 ],
 themeConfig: {
 nav: [
 { text: '首页', link: '/' },
 { text: '指南', link: '/guide/quick-start' },
 { text: 'API 参考', link: '/api/' },
 { text: '开发', link: '/dev/architecture' },
 ],
 sidebar: {
 '/guide/': [
 {
 text: '快速开始',
 items: [
 { text: '安装部署', link: '/guide/quick-start' },
 ],
 },
 {
 text: '工作流',
 collapsed: true,
 items: [
 { text: '工作流指南', link: '/guide/workflows' },
 ],
 },
 {
 text: '管理',
 collapsed: true,
 items: [
 { text: '管理指南', link: '/guide/admin' },
 ],
 },
 ],
 '/api/':,
 '/dev/': [
 {
 text: '开发文档',
 items: [
 { text: '系统架构', link: '/dev/architecture' },
 { text: '节点规格', link: '/dev/node-spec' },
 ],
 },
 ],
 },
 search: {
 provider: 'local',
 options: {
 translations: {
 button: {
 buttonText: '搜索',
 buttonAriaLabel: '搜索文档',
 },
 modal: {
 displayDetails: '显示详细列表',
 resetButtonTitle: '重置搜索',
 noResultsText: '没有相关结果',
 footer: {
 selectText: '选择',
 navigateText: '切换',
 closeText: '关闭',
 },
 },
 },
 },
 },
 outline: {
 label: '页面导航',
 },
 docFooter: {
 prev: '上一页',
 next: '下一页',
 },
 },
})
