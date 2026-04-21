/**
 * Phase Wave stub — Plan fill real assertion.
 *
 * Scope: CleanupDialog 预览 + 批量勾选 + DELETE 调用闭环。
 * Consumer: Plan Wave Task 07-04。
 */
import { describe, expect, it } from 'vitest'
describe('cleanupDialog (Phase Wave stub)', => {
 it.todo('Phase Wave stub — Plan fill real assertion')
 it('placeholder to ensure suite collects', => {
 expect(true).toBe(true)
 })
})
// TODO(Plan Task 07-04)：
// - 消息列表预览（按时间倒序，N 条可视）
// - 批量勾选 checkbox 状态与 before_id 计算
// - 确认删除调用 DELETE /api/chat/conversations/{id}/messages/?before_id=X
// - 删除成功 emit('deleted', count) + 关闭 dialog
// - 删除失败保留 dialog 并展示错误提示
// - 空列表状态渲染 "无可清理消息"
