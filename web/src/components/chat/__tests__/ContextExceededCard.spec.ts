/**
 * Phase Wave stub — Plan fill real assertion.
 *
 * Scope: ContextExceededCard 三按钮（清理历史 / 换大 context 模型 / 精简 system prompt）。
 * Consumer: Plan Wave Task 07-03。
 */
import { describe, expect, it } from 'vitest'
describe('contextExceededCard (Phase Wave stub)', => {
 it.todo('Phase Wave stub — Plan fill real assertion')
 it('placeholder to ensure suite collects', => {
 expect(true).toBe(true)
 })
})
// TODO(Plan Task 07-03)：
// - 渲染 estimated / max / exceeded_by 数值
// - 按钮 1 "清理对话历史" click emit('cleanup')
// - 按钮 2 "换大 context 模型" click emit('switch-model')
// - 按钮 3 "精简 system prompt" click emit('trim-prompt')
// - model 名称展示
