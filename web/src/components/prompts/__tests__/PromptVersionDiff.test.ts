/**
 * PromptVersionDiff.vue 单元测试
 *
 * 覆盖路径（Plan Task 2 behavior §1）：
 * 1. v1='line1\nline2\n' vs v2='line1\nline3\n' → 左栏含 line1(unchanged)+line2(removed)
 * 右栏含 line1(unchanged)+line3(added)
 * 2. 未变更段使用 .diff-unchanged
 * 3. 新增段使用 .diff-added（仅右栏）
 * 4. 删除段使用 .diff-removed（仅左栏）
 * 5. props 变化时重新计算 diff（watch 生效）
 * 6. 顶部元信息显示 v{v1.version} 对比 v{v2.version}
 *
 * 注意：diff 包真实 import，不 mock，diffLines 会实际运行 —— 本 Plan 首次消费 diff@8.0.4
 */
import type { PromptVersion } from '~/types/prompts'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PromptVersionDiff from '../PromptVersionDiff.vue'
function makeVersion(overrides: Partial<PromptVersion>): PromptVersion {
 return {
 id: `ver-${overrides.version ?? 1}`,
 version: 1,
 body: '',
 variables_schema: {},
 declared_variables:,
 change_note: '',
 created_by: 1,
 created_at: '2026-04-01T00:00:00Z',
 ...overrides,
 }
}
describe('promptVersionDiff.vue', => {
 it('左栏展示 unchanged + removed 段，右栏展示 unchanged + added 段', => {
 const v1 = makeVersion({ version: 1, body: 'line1\nline2\n' })
 const v2 = makeVersion({ version: 2, body: 'line1\nline3\n' })
 const wrapper = mount(PromptVersionDiff, { props: { v1, v2 } })
 const html = wrapper.html
 // 双栏均包含 unchanged 的 line1
 expect(wrapper.text).toContain('line1')
 // 左栏存在 line2 removed
 expect(wrapper.text).toContain('line2')
 // 右栏存在 line3 added
 expect(wrapper.text).toContain('line3')
 // 三类 CSS class 均存在
 expect(html).toContain('diff-unchanged')
 expect(html).toContain('diff-removed')
 expect(html).toContain('diff-added')
 })
 it('未变更段使用 diff-unchanged CSS class', => {
 const v1 = makeVersion({ version: 1, body: 'shared\n' })
 const v2 = makeVersion({ version: 2, body: 'shared\n' })
 const wrapper = mount(PromptVersionDiff, { props: { v1, v2 } })
 const html = wrapper.html
 expect(html).toContain('diff-unchanged')
 // 无任何 added / removed
 expect(html).not.toContain('diff-added')
 expect(html).not.toContain('diff-removed')
 })
 it('新增段仅出现在右栏使用 diff-added CSS class', => {
 const v1 = makeVersion({ version: 1, body: '' })
 const v2 = makeVersion({ version: 2, body: 'only in v2\n' })
 const wrapper = mount(PromptVersionDiff, { props: { v1, v2 } })
 const columns = wrapper.findAll('[data-diff-column]')
 expect(columns.length).toBe(2)
 const leftHtml = columns[0].html
 const rightHtml = columns[1].html
 expect(rightHtml).toContain('diff-added')
 expect(rightHtml).toContain('only in v2')
 // 左栏不应出现 added class
 expect(leftHtml).not.toContain('diff-added')
 })
 it('删除段仅出现在左栏使用 diff-removed CSS class', => {
 const v1 = makeVersion({ version: 1, body: 'only in v1\n' })
 const v2 = makeVersion({ version: 2, body: '' })
 const wrapper = mount(PromptVersionDiff, { props: { v1, v2 } })
 const columns = wrapper.findAll('[data-diff-column]')
 const leftHtml = columns[0].html
 const rightHtml = columns[1].html
 expect(leftHtml).toContain('diff-removed')
 expect(leftHtml).toContain('only in v1')
 // 右栏不应出现 removed class
 expect(rightHtml).not.toContain('diff-removed')
 })
 it('props 变化时重新计算 diff（watch 生效）', async => {
 const v1 = makeVersion({ version: 1, body: 'initial\n' })
 const v2 = makeVersion({ version: 2, body: 'initial\n' })
 const wrapper = mount(PromptVersionDiff, { props: { v1, v2 } })
 expect(wrapper.html).not.toContain('diff-added')
 // 更新 v2 引入新增内容
 await wrapper.setProps({
 v1,
 v2: makeVersion({ version: 2, body: 'initial\nnew line\n' }),
 })
 expect(wrapper.html).toContain('diff-added')
 expect(wrapper.text).toContain('new line')
 })
 it('顶部元信息显示 v{v1.version} 对比 v{v2.version}', => {
 const v1 = makeVersion({ version: 3, body: 'a\n' })
 const v2 = makeVersion({ version: 5, body: 'b\n' })
 const wrapper = mount(PromptVersionDiff, { props: { v1, v2 } })
 expect(wrapper.text).toContain('v3 对比 v5')
 })
})
