/**
 * PromptVersionList.vue 单元测试
 *
 * 覆盖路径（Plan Task 2 behavior §2）：
 * 1. 渲染所有版本 DESC 排序（v3, v2, v1）
 * 2. 当前激活版本带 `当前版本` Badge
 * 3. 只有一个版本时显示 inline 提示
 * 4. 两个 Select 用于选 v1/v2 对比
 * 5. 选中非当前版本后 "恢复到此版本" 按钮变为可用
 * 6. 点击 "恢复到此版本" → useConfirmDialog.confirm 被调用（mock 返回 true）→ activateVersion 被调用
 * 7. useConfirmDialog.confirm 返回 false → activateVersion 不被调用
 */
import type { PromptDetail, PromptVersion } from '~/types/prompts'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PromptVersionList from '../PromptVersionList.vue'
// mock 所有外部依赖 —— vi.mock 会被自动 hoist 到顶部
const activateVersionMock = vi.fn
const confirmMock = vi.fn
const successMock = vi.fn
const handleErrorMock = vi.fn
vi.mock('~/stores/prompts', => ({
 usePromptsStore: => ({
 activateVersion: activateVersionMock,
 }),
}))
vi.mock('~/composables/useConfirmDialog', => ({
 useConfirmDialog: => ({
 confirm: confirmMock,
 isOpen: { value: false },
 options: { value: { description: '' } },
 handleConfirm: vi.fn,
 handleCancel: vi.fn,
 }),
}))
vi.mock('~/composables/useToast', => ({
 useToast: => ({
 success: successMock,
 error: vi.fn,
 warning: vi.fn,
 info: vi.fn,
 }),
}))
vi.mock('~/composables/useErrorHandler', => ({
 useErrorHandler: => ({ handleError: handleErrorMock }),
}))
function makeVersion(n: number): PromptVersion {
 return {
 id: `ver-${n}`,
 version: n,
 body: `body for v${n}`,
 variables_schema: {},
 declared_variables:,
 change_note: `变更说明 v${n}`,
 created_by: 1,
 created_at: `2026-04-0${n}T00:00:00Z`,
 }
}
function makePrompt(activeVersionId: string): PromptDetail {
 return {
 id: 'prompt-abc',
 slug: 'test.slug',
 category: 'chat_agent',
 scope: 'system',
 project: null,
 title: '测试 Prompt',
 description: '',
 is_builtin: false,
 active_version: {
 ...makeVersion(3),
 id: activeVersionId,
 },
 declared_variables:,
 created_by: 1,
 created_at: '2026-04-01T00:00:00Z',
 updated_at: '2026-04-01T00:00:00Z',
 }
}
async function flushAsync: Promise<void> {
 await new Promise(resolve => setTimeout(resolve, 20))
}
describe('promptVersionList.vue', => {
 beforeEach( => {
 activateVersionMock.mockReset
 confirmMock.mockReset
 successMock.mockReset
 handleErrorMock.mockReset
 })
 it('版本按 DESC 排序渲染', => {
 const versions = [makeVersion(1), makeVersion(2), makeVersion(3)]
 const wrapper = mount(PromptVersionList, {
 props: { prompt: makePrompt('ver-3'), versions },
 })
 const items = wrapper.findAll('li')
 expect(items.length).toBe(3)
 // 第一个应为 v3，最后为 v1
 expect(items[0].text).toContain('v3')
 expect(items[1].text).toContain('v2')
 expect(items[2].text).toContain('v1')
 })
 it('当前激活版本带 `当前版本` Badge', => {
 const versions = [makeVersion(1), makeVersion(2), makeVersion(3)]
 const wrapper = mount(PromptVersionList, {
 props: { prompt: makePrompt('ver-2'), versions },
 })
 const items = wrapper.findAll('li')
 // ver-2 对应 v2，应在第二个位置（DESC 排序后）
 expect(items[1].text).toContain('当前版本')
 // 其他位置不应含 Badge
 expect(items[0].text).not.toContain('当前版本')
 expect(items[2].text).not.toContain('当前版本')
 })
 it('只有一个版本时显示 inline 提示', => {
 const versions = [makeVersion(1)]
 const wrapper = mount(PromptVersionList, {
 props: { prompt: makePrompt('ver-1'), versions },
 })
 expect(wrapper.text).toContain('仅有一个版本，保存后会自动追加新版本供对比')
 })
 it('存在 >=2 版本时渲染 PromptVersionDiff 子组件', => {
 const versions = [makeVersion(1), makeVersion(2)]
 const wrapper = mount(PromptVersionList, {
 props: { prompt: makePrompt('ver-2'), versions },
 })
 // PromptVersionDiff 真实渲染，含 v1 对比 v2 文字
 expect(wrapper.text).toContain('对比')
 // "恢复到此版本" 按钮出现
 expect(wrapper.text).toContain('恢复到此版本')
 })
 it('点击 "恢复到此版本" 调 confirm 返回 true 后调 activateVersion', async => {
 confirmMock.mockResolvedValueOnce(true)
 activateVersionMock.mockResolvedValueOnce({})
 const versions = [makeVersion(1), makeVersion(2), makeVersion(3)]
 // active = v3（最新），默认对比为 v1 vs v3，rollbackCandidate 应为非 active 的 v1
 const wrapper = mount(PromptVersionList, {
 props: { prompt: makePrompt('ver-3'), versions },
 })
 const rollbackBtn = wrapper.findAll('button').find(b => b.text.includes('恢复到此版本'))
 expect(rollbackBtn).toBeTruthy
 await rollbackBtn!.trigger('click')
 await flushAsync
 expect(confirmMock).toHaveBeenCalledTimes(1)
 expect(activateVersionMock).toHaveBeenCalledTimes(1)
 expect(successMock).toHaveBeenCalled
 })
 it('confirm 返回 false 时不调 activateVersion', async => {
 confirmMock.mockResolvedValueOnce(false)
 const versions = [makeVersion(1), makeVersion(2), makeVersion(3)]
 const wrapper = mount(PromptVersionList, {
 props: { prompt: makePrompt('ver-3'), versions },
 })
 const rollbackBtn = wrapper.findAll('button').find(b => b.text.includes('恢复到此版本'))
 await rollbackBtn!.trigger('click')
 await flushAsync
 expect(confirmMock).toHaveBeenCalledTimes(1)
 expect(activateVersionMock).not.toHaveBeenCalled
 expect(successMock).not.toHaveBeenCalled
 })
})
