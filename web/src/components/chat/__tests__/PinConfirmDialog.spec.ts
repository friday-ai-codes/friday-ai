/**
 * Phase Wave stub — Plan fill real assertion.
 *
 * Scope: ChatHeader pin 弹窗 + ChatInterruptView WAITING 态 Provider 只读。
 * Consumer: Plan Wave Task 02-02。
 */
import { describe, expect, it } from 'vitest'
describe('pinConfirmDialog (Phase Wave stub)', => {
 it.todo('Phase Wave stub — Plan fill real assertion')
 it('placeholder to ensure suite collects', => {
 expect(true).toBe(true)
 })
})
// TODO(Plan Task 02-02)：
// - active 对话切换 Provider 触发 Dialog 打开
// - 点击确认 emit('confirm', credentialId)
// - frozen 对话（status ∈ {completed, stopped, error}）按钮置灰
// - ChatInterruptView WAITING 态 Provider 字段 readonly
