import { test, expect } from '@playwright/test'
test.describe('Home Page', => {
 test('should display the home page correctly', async ({ page }) => {
 await page.goto('/')
 // 检查标题
 await expect(page.locator('h1')).toContainText('Friday AI')
 // 检查功能卡片
 await expect(page.locator('text=智能任务执行')).toBeVisible
 await expect(page.locator('text=安全隔离')).toBeVisible
 await expect(page.locator('text=人工审核')).toBeVisible
 })
 test('should navigate to tasks page', async ({ page }) => {
 await page.goto('/')
 // 点击查看任务按钮
 await page.click('text=查看任务')
 // 验证导航到任务页面
 await expect(page).toHaveURL('/tasks')
 await expect(page.locator('h1')).toContainText('任务列表')
 })
})
test.describe('Tasks Page', => {
 test('should display task list', async ({ page }) => {
 await page.goto('/tasks')
 // 检查任务列表标题
 await expect(page.locator('h1')).toContainText('任务列表')
 // 检查表头
 await expect(page.locator('text=任务名称')).toBeVisible
 await expect(page.locator('text=状态')).toBeVisible
 await expect(page.locator('text=创建时间')).toBeVisible
 })
})