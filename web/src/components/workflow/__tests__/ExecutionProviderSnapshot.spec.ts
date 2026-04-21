/**
 * Phase Wave stub — Plan fill real assertion.
 *
 * Scope: Execution 详情页 ExecutionProviderSnapshot 渲染快照字段。
 * Consumer: Plan Wave Task 04-02。
 */
import { describe, expect, it } from 'vitest'
describe('executionProviderSnapshot (Phase Wave stub)', => {
 it.todo('Phase Wave stub — Plan fill real assertion')
 it('placeholder to ensure suite collects', => {
 expect(true).toBe(true)
 })
})
// TODO(Plan Task 04-02)：
// - 渲染 node_id / provider_type / model / resolved_source
// - api_key_fingerprint 脱敏展示（前缀 + ***）
// - 多节点分行渲染
// - 空 snapshot 渲染 "未记录"
// - 与 ResolvedSourceBadge 组合渲染（winning.source → badge 颜色）
