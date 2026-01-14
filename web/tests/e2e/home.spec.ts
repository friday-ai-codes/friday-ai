import { test, expect } from '@playwright/test'
test.describe('Home Page', => {
 test('should display the home page correctly', async ({ page }) => {
 await page.goto('/')
 // 检查标题
 await expect(page.locator('h1')).toContainText('Friday AI')
 // 检查功能卡片 - 使用 h3 标签选择器确保只匹配标题
 await expect(page.locator('h3:has-text("智能任务执行")')).toBeVisible
 await expect(page.locator('h3:has-text("安全隔离")')).toBeVisible
 await expect(page.locator('h3:has-text("人工审核")')).toBeVisible
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
 // 检查表头 - 使用精确匹配避免匹配到任务内容
 await expect(page.getByText('任务名称', { exact: true })).toBeVisible
 await expect(page.getByText('状态', { exact: true })).toBeVisible
 await expect(page.getByText('创建时间', { exact: true })).toBeVisible
 })
})