/**
 * Phase Plan — IndexProgressTimeline 单测（work item §6.2/§7）
 *
 * 测试三组文件分组渲染、空状态文案、v-if 隐藏条件。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent } from 'vue'
import IndexProgressTimeline from '../IndexProgressTimeline.vue'
// Stub StatusBadge 避免依赖
const stubComponents = {
 StatusBadge: defineComponent({ template: '<span class="status-badge-stub"><slot /></span>' }),
}
function mountTimeline(changedFiles = {}, isIndexing = true) {
 return mount(IndexProgressTimeline, {
 props: {
 repositoryId: 'repo-1',
 indexHistoryId: null,
 changedFiles,
 isIndexing,
 },
 global: { stubs: stubComponents },
 })
}
describe('IndexProgressTimeline', => {
 it('A: 新增文件组 — changed_files.added 有值时显示"新增 (2)"标签 + 文件路径', => {
 const wrapper = mountTimeline({ added: ['src/foo.py', 'src/bar.py'] })
 expect(wrapper.text).toContain('新增 (2)')
 expect(wrapper.text).toContain('src/foo.py')
 expect(wrapper.text).toContain('src/bar.py')
 // 新增图标 emerald 颜色
 expect(wrapper.html).toContain('text-emerald-600')
 })
 it('B: 修改文件组 — changed_files.modified 有值时显示"修改 (1)"', => {
 const wrapper = mountTimeline({ modified: ['src/api.py'] })
 expect(wrapper.text).toContain('修改 (1)')
 expect(wrapper.text).toContain('src/api.py')
 // 修改图标 amber 颜色
 expect(wrapper.html).toContain('text-amber-600')
 })
 it('C: 删除文件组 — changed_files.deleted 有值时显示"删除 (1)"+ destructive 颜色', => {
 const wrapper = mountTimeline({ deleted: ['src/old.py'] })
 expect(wrapper.text).toContain('删除 (1)')
 expect(wrapper.text).toContain('src/old.py')
 // 删除图标 destructive 颜色
 expect(wrapper.html).toContain('text-destructive')
 })
 it('D: 空状态 — changedFiles 全空时显示"全量首次索引（无变更文件清单）"', => {
 const wrapper = mountTimeline({})
 expect(wrapper.text).toContain('全量首次索引（无变更文件清单）')
 })
 it('E: v-if 隐藏 — isIndexing=false 时组件不渲染', => {
 const wrapper = mountTimeline({}, false)
 // 组件根级 v-if="isIndexing" 为 false 时，wrapper 包含空注释节点
 expect(wrapper.html).not.toContain('本次索引变更')
 expect(wrapper.find('.card').exists).toBe(false)
 })
})
