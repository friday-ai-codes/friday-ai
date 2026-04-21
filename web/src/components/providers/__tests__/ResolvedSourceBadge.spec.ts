/**
 * Phase Wave stub — Plan fill real assertion.
 *
 * Scope: ResolvedSourceBadge 四态颜色 + tooltip 优先级链展开 + winning source 加粗。
 * Consumer: Plan Wave Task 06-03。
 */
import { describe, expect, it } from 'vitest'
describe('resolvedSourceBadge (Phase Wave stub)', => {
 it.todo('Phase Wave stub — Plan fill real assertion')
 it('placeholder to ensure suite collects', => {
 expect(true).toBe(true)
 })
})
// TODO(Plan Task 06-03)：
// - winning.source="node" → 紫色 badge "节点级"
// - winning.source="conversation" → 蓝色 badge "对话级"
// - winning.source="project" → 绿色 badge "项目级"
// - winning.source="system" → 灰色 badge "系统级"
// - tooltip hover 展示四层 chain，winning 行加粗 + "✓"
// - tooltip chain 顺序 node > conversation > project > system
