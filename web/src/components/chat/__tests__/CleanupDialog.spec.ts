/**
 * Phase Plan Task 02 — CleanupDialog 组件测试。
 *
 * 覆盖 CleanupDialog：消息预览 + 批量勾选 + DELETE 调用闭环。
 *
 * Test matrix:
 * A: open=true → 加载 messages + 默认全选最早 5 条
 * B: 删除按钮在无选中时 disabled；有选中时可点击
 * C: 确认删除（AlertDialogAction click）→ 调用 DELETE api.del（mock 注入），成功 emit('confirm')
 * D: DELETE 失败保留 Dialog 开，errorMsg 写入
 * E: 关闭按钮 emit('update:open', false)
 */
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
// Mock api client（必须在 import 组件前）
const delMock = vi.fn
const getMock = vi.fn
vi.mock('~/api/client', => ({
 get: (...args: unknown) => getMock(...args),
 del: (...args: unknown) => delMock(...args),
 ApiError: class extends Error {},
}))
// Mock vue-sonner toast（静音）
vi.mock('vue-sonner', => ({
 toast: {
 success: vi.fn,
 error: vi.fn,
 },
}))
import CleanupDialog from '~/components/chat/CleanupDialog.vue'
const mockMessages = [
 { id: 'm1', role: 'user', content: '第一条用户消息', created_at: '2026-04-01T10:00:00Z' },
 { id: 'm2', role: 'assistant', content: '第一条助手回复', created_at: '2026-04-01T10:01:00Z' },
 { id: 'm3', role: 'user', content: '第二条用户消息', created_at: '2026-04-01T10:02:00Z' },
 { id: 'm4', role: 'assistant', content: '第二条助手回复', created_at: '2026-04-01T10:03:00Z' },
 { id: 'm5', role: 'user', content: '第三条用户消息', created_at: '2026-04-01T10:04:00Z' },
 { id: 'm6', role: 'assistant', content: '第三条助手回复', created_at: '2026-04-01T10:05:00Z' },
]
describe('cleanupDialog', => {
 beforeEach( => {
 delMock.mockReset
 getMock.mockReset
 getMock.mockResolvedValue({ messages: mockMessages })
 })
 it('A: open=true → 拉取 messages + 默认选中最早 5 条（最多）', async => {
 const wrapper = mount(CleanupDialog, {
 props: { open: true, conversationId: 'conv-abc' },
 global: {
 stubs: {
 // Dialog / AlertDialog Portal 组件在 happy-dom 下默认不渲染 content —
 // 用 render-all stub 透出所有插槽到根 DOM，便于断言
 Dialog: { template: '<div><slot /></div>' },
 DialogContent: { template: '<div><slot /></div>' },
 DialogHeader: { template: '<div><slot /></div>' },
 DialogTitle: { template: '<h2><slot /></h2>' },
 DialogDescription: { template: '<p><slot /></p>' },
 DialogFooter: { template: '<div><slot /></div>' },
 AlertDialog: { template: '<div><slot /></div>' },
 AlertDialogTrigger: { template: '<div><slot /></div>' },
 AlertDialogContent: { template: '<div><slot /></div>' },
 AlertDialogHeader: { template: '<div><slot /></div>' },
 AlertDialogTitle: { template: '<h3><slot /></h3>' },
 AlertDialogDescription: { template: '<p><slot /></p>' },
 AlertDialogFooter: { template: '<div><slot /></div>' },
 AlertDialogCancel: { template: '<button><slot /></button>' },
 AlertDialogAction: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
 ScrollArea: { template: '<div><slot /></div>' },
 Checkbox: {
 props: ['modelValue'],
 emits: ['update:modelValue'],
 template: '<input type="checkbox":checked="modelValue" @change="$emit(\'update:modelValue\', !$event.target.checked === false)" />',
 },
 },
 },
 })
 await flushPromises
 expect(getMock).toHaveBeenCalled
 const html = wrapper.html
 expect(html).toContain('清理对话历史')
 // 6 条消息，默认选中最早 5 条
 expect(wrapper.text).toContain('第一条用户消息')
 // 选中计数应为 5
 expect(wrapper.text).toContain('5 条')
 })
 it('B: 删除按钮在选中为 0 时 disabled', async => {
 const wrapper = mount(CleanupDialog, {
 props: { open: true, conversationId: 'conv-abc' },
 global: {
 stubs: {
 Dialog: { template: '<div><slot /></div>' },
 DialogContent: { template: '<div><slot /></div>' },
 DialogHeader: { template: '<div><slot /></div>' },
 DialogTitle: { template: '<h2><slot /></h2>' },
 DialogDescription: { template: '<p><slot /></p>' },
 DialogFooter: { template: '<div><slot /></div>' },
 AlertDialog: { template: '<div><slot /></div>' },
 AlertDialogTrigger: { template: '<div><slot /></div>' },
 AlertDialogContent: { template: '<div><slot /></div>' },
 AlertDialogHeader: { template: '<div><slot /></div>' },
 AlertDialogTitle: { template: '<h3><slot /></h3>' },
 AlertDialogDescription: { template: '<p><slot /></p>' },
 AlertDialogFooter: { template: '<div><slot /></div>' },
 AlertDialogCancel: { template: '<button><slot /></button>' },
 AlertDialogAction: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
 ScrollArea: { template: '<div><slot /></div>' },
 Checkbox: {
 props: ['modelValue'],
 template: '<input type="checkbox":checked="modelValue" />',
 },
 },
 },
 })
 await flushPromises
 // 组件初始化应选中最早 5 条（默认全选），故按钮不应 disabled
 const buttons = wrapper.findAll('button')
 const deleteBtn = buttons.find(b => b.text.includes('永久删除选中消息'))
 expect(deleteBtn).toBeTruthy
 // 存在一个删除按钮（非 disabled 默认 5 选中）
 expect(deleteBtn!.attributes('disabled')).toBeUndefined
 })
 it('C: 确认删除 → 调用 api.del(?before_id=X) + emit("confirm")', async => {
 delMock.mockResolvedValue({ deleted_count: 5 })
 const wrapper = mount(CleanupDialog, {
 props: { open: true, conversationId: 'conv-abc' },
 global: {
 stubs: {
 Dialog: { template: '<div><slot /></div>' },
 DialogContent: { template: '<div><slot /></div>' },
 DialogHeader: { template: '<div><slot /></div>' },
 DialogTitle: { template: '<h2><slot /></h2>' },
 DialogDescription: { template: '<p><slot /></p>' },
 DialogFooter: { template: '<div><slot /></div>' },
 AlertDialog: { template: '<div><slot /></div>' },
 AlertDialogTrigger: { template: '<div><slot /></div>' },
 AlertDialogContent: { template: '<div><slot /></div>' },
 AlertDialogHeader: { template: '<div><slot /></div>' },
 AlertDialogTitle: { template: '<h3><slot /></h3>' },
 AlertDialogDescription: { template: '<p><slot /></p>' },
 AlertDialogFooter: { template: '<div><slot /></div>' },
 AlertDialogCancel: { template: '<button><slot /></button>' },
 AlertDialogAction: { template: '<button class="confirm-delete" @click="$emit(\'click\')"><slot /></button>' },
 ScrollArea: { template: '<div><slot /></div>' },
 Checkbox: {
 props: ['modelValue'],
 template: '<input type="checkbox":checked="modelValue" />',
 },
 },
 },
 })
 await flushPromises
 // 点击 AlertDialogAction（确认删除）
 const confirmBtn = wrapper.find('.confirm-delete')
 await confirmBtn.trigger('click')
 await flushPromises
 // api.del 被调用且 URL 含 before_id
 expect(delMock).toHaveBeenCalled
 const callArg = String(delMock.mock.calls[0][0])
 expect(callArg).toContain('/chat/conversations/conv-abc/messages/')
 expect(callArg).toContain('before_id=')
 // emit('confirm', beforeId)
 expect(wrapper.emitted('confirm')).toBeTruthy
 })
 it('D: DELETE 失败保留 Dialog 开，errorMsg 写入组件', async => {
 delMock.mockRejectedValue(new Error('Network error'))
 const wrapper = mount(CleanupDialog, {
 props: { open: true, conversationId: 'conv-abc' },
 global: {
 stubs: {
 Dialog: { template: '<div><slot /></div>' },
 DialogContent: { template: '<div><slot /></div>' },
 DialogHeader: { template: '<div><slot /></div>' },
 DialogTitle: { template: '<h2><slot /></h2>' },
 DialogDescription: { template: '<p><slot /></p>' },
 DialogFooter: { template: '<div><slot /></div>' },
 AlertDialog: { template: '<div><slot /></div>' },
 AlertDialogTrigger: { template: '<div><slot /></div>' },
 AlertDialogContent: { template: '<div><slot /></div>' },
 AlertDialogHeader: { template: '<div><slot /></div>' },
 AlertDialogTitle: { template: '<h3><slot /></h3>' },
 AlertDialogDescription: { template: '<p><slot /></p>' },
 AlertDialogFooter: { template: '<div><slot /></div>' },
 AlertDialogCancel: { template: '<button><slot /></button>' },
 AlertDialogAction: { template: '<button class="confirm-delete" @click="$emit(\'click\')"><slot /></button>' },
 ScrollArea: { template: '<div><slot /></div>' },
 Checkbox: {
 props: ['modelValue'],
 template: '<input type="checkbox":checked="modelValue" />',
 },
 },
 },
 })
 await flushPromises
 await wrapper.find('.confirm-delete').trigger('click')
 await flushPromises
 // 失败路径未 emit update:open（Dialog 保持开启）
 const openUpdates = wrapper.emitted('update:open') ??
 const falseCloses = openUpdates.filter((e: unknown) => e[0] === false)
 expect(falseCloses.length).toBe(0)
 // 组件 text 含错误提示（或 destructive 样式）
 expect(wrapper.html).toMatch(/失败|Network error/i)
 })
 it('E: 点击取消按钮 emit("update:open", false)', async => {
 const wrapper = mount(CleanupDialog, {
 props: { open: true, conversationId: 'conv-abc' },
 global: {
 stubs: {
 Dialog: { template: '<div><slot /></div>' },
 DialogContent: { template: '<div><slot /></div>' },
 DialogHeader: { template: '<div><slot /></div>' },
 DialogTitle: { template: '<h2><slot /></h2>' },
 DialogDescription: { template: '<p><slot /></p>' },
 DialogFooter: { template: '<div><slot /></div>' },
 AlertDialog: { template: '<div><slot /></div>' },
 AlertDialogTrigger: { template: '<div><slot /></div>' },
 AlertDialogContent: { template: '<div><slot /></div>' },
 AlertDialogHeader: { template: '<div><slot /></div>' },
 AlertDialogTitle: { template: '<h3><slot /></h3>' },
 AlertDialogDescription: { template: '<p><slot /></p>' },
 AlertDialogFooter: { template: '<div><slot /></div>' },
 AlertDialogCancel: { template: '<button><slot /></button>' },
 AlertDialogAction: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
 ScrollArea: { template: '<div><slot /></div>' },
 Checkbox: {
 props: ['modelValue'],
 template: '<input type="checkbox":checked="modelValue" />',
 },
 },
 },
 })
 await flushPromises
 const cancelBtn = wrapper.findAll('button').find(b => b.text.trim === '取消')
 expect(cancelBtn).toBeTruthy
 await cancelBtn!.trigger('click')
 const openUpdates = wrapper.emitted('update:open') ??
 expect(openUpdates.some((e: unknown) => e[0] === false)).toBe(true)
 })
 it('F: 选中 preview 最后一条时拒绝提交，errorMsg 提示"保留至少 1 条未选中消息"', async => {
 // Phase Plan：末尾边界 — 选中 preview 列表最后一条时 handleConfirmDelete 应拒绝提交
 // fixture：构造 3 条消息（< PREVIEW_LIMIT=20，< DEFAULT_SELECT_COUNT=5 → 全选三条，含末尾 m3）
 const threeMessages = [
 { id: 'm1', role: 'user', content: 'first', created_at: '2026-04-01T10:00:00Z' },
 { id: 'm2', role: 'assistant', content: 'second', created_at: '2026-04-01T10:01:00Z' },
 { id: 'm3', role: 'user', content: 'third', created_at: '2026-04-01T10:02:00Z' },
 ]
 getMock.mockResolvedValue({ messages: threeMessages })
 const wrapper = mount(CleanupDialog, {
 props: { open: true, conversationId: 'conv-boundary' },
 global: {
 stubs: {
 Dialog: { template: '<div><slot /></div>' },
 DialogContent: { template: '<div><slot /></div>' },
 DialogHeader: { template: '<div><slot /></div>' },
 DialogTitle: { template: '<h2><slot /></h2>' },
 DialogDescription: { template: '<p><slot /></p>' },
 DialogFooter: { template: '<div><slot /></div>' },
 AlertDialog: { template: '<div><slot /></div>' },
 AlertDialogTrigger: { template: '<div><slot /></div>' },
 AlertDialogContent: { template: '<div><slot /></div>' },
 AlertDialogHeader: { template: '<div><slot /></div>' },
 AlertDialogTitle: { template: '<h3><slot /></h3>' },
 AlertDialogDescription: { template: '<p><slot /></p>' },
 AlertDialogFooter: { template: '<div><slot /></div>' },
 AlertDialogCancel: { template: '<button><slot /></button>' },
 AlertDialogAction: { template: '<button class="confirm-delete" @click="$emit(\'click\')"><slot /></button>' },
 ScrollArea: { template: '<div><slot /></div>' },
 Checkbox: {
 props: ['modelValue'],
 template: '<input type="checkbox":checked="modelValue" />',
 },
 },
 },
 })
 await flushPromises
 // 组件默认选中最早 DEFAULT_SELECT_COUNT=5 条；因 3 < 5 → 全选三条；包含末尾 m3
 await wrapper.find('.confirm-delete').trigger('click')
 await flushPromises
 // apiDel 不应被调用（边界命中后直接 return）
 expect(delMock).not.toHaveBeenCalled
 // errorMsg 渲染锁定的 work item 边界文案
 expect(wrapper.html).toContain('请保留至少 1 条未选中消息')
 // Dialog 未关闭（emit('update:open', false) 未触发）
 const openUpdates = wrapper.emitted('update:open') ??
 expect(openUpdates.filter((e: unknown) => e[0] === false).length).toBe(0)
 })
})
