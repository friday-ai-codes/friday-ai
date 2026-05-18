/**
 * GraphAutoBuildToggle 单元测试
 *
 * 覆盖 4 条断言：
 * 1. 初始值渲染（Switch model-value 透传）
 * 2. 切换调 repositoriesApi.update（PATCH body 正确）
 * 3. API 失败时 enabled 视觉态回滚 + handleError 调用
 * 4. saving 期间 Switch disabled
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import GraphAutoBuildToggle from '../GraphAutoBuildToggle.vue'
vi.mock('~/api/repositories', => ({
 repositoriesApi: {
 update: vi.fn,
 },
}))
const successSpy = vi.fn
const handleErrorSpy = vi.fn
vi.mock('~/composables/useToast', => ({
 useToast: => ({ success: successSpy, error: vi.fn }),
}))
vi.mock('~/composables/useErrorHandler', => ({
 useErrorHandler: => ({ handleError: handleErrorSpy }),
}))
// stub Switch / Tooltip 系列，避免 reka-ui provider 依赖
const SwitchStub = defineComponent({
 name: 'Switch',
 props: {
 modelValue: { type: Boolean, default: false },
 disabled: { type: Boolean, default: false },
 },
 emits: ['update:modelValue'],
 template: `<button
 data-testid="switch":aria-label="$attrs['aria-label']":disabled="disabled":data-checked="modelValue"
 @click="$emit('update:modelValue', !modelValue)"
 ></button>`,
})
const stubComponents = {
 Switch: SwitchStub,
 Tooltip: defineComponent({ template: '<div><slot /></div>' }),
 TooltipProvider: defineComponent({ template: '<div><slot /></div>' }),
 TooltipTrigger: defineComponent({ template: '<div><slot /></div>' }),
 TooltipContent: defineComponent({ template: '<div><slot /></div>' }),
}
function mountToggle(initial = false) {
 return mount(GraphAutoBuildToggle, {
 props: { repositoryId: 'repo-1', initial },
 global: { stubs: stubComponents },
 })
}
describe('graphAutoBuildToggle', => {
 beforeEach( => {
 vi.clearAllMocks
 })
 it('1: 初始值渲染 — Switch model-value 与 initial 一致', => {
 const wrapper = mountToggle(true)
 const sw = wrapper.find('[data-testid="switch"]')
 expect(sw.exists).toBe(true)
 expect(sw.attributes('data-checked')).toBe('true')
 expect(sw.attributes('aria-label')).toBe('自动构建代码图谱')
 })
 it('2: 切换调 repositoriesApi.update — PATCH body 含 auto_build_graph_enabled', async => {
 vi.mocked(repositoriesApi.update).mockResolvedValue({} as never)
 const wrapper = mountToggle(false)
 await wrapper.find('[data-testid="switch"]').trigger('click')
 await flushPromises
 expect(repositoriesApi.update).toHaveBeenCalledWith('repo-1', {
 auto_build_graph_enabled: true,
 })
 expect(successSpy).toHaveBeenCalledWith('已开启自动构建图谱')
 // emit update:enabled 给父组件
 const emitted = wrapper.emitted('update:enabled')
 expect(emitted).toBeTruthy
 expect(emitted![0]).toEqual([true])
 })
 it('3: API 失败 — enabled 视觉态回滚 + handleError 调用', async => {
 vi.mocked(repositoriesApi.update).mockRejectedValue(new Error('boom'))
 const wrapper = mountToggle(true)
 const sw = wrapper.find('[data-testid="switch"]')
 expect(sw.attributes('data-checked')).toBe('true')
 await sw.trigger('click') // 尝试切到 false
 await flushPromises
 expect(repositoriesApi.update).toHaveBeenCalledTimes(1)
 expect(handleErrorSpy).toHaveBeenCalledTimes(1)
 expect(handleErrorSpy.mock.calls[0][1]).toBe('更新自动构建开关')
 // 视觉态回滚到 true
 expect(wrapper.find('[data-testid="switch"]').attributes('data-checked')).toBe('true')
 // 未 emit update:enabled
 expect(wrapper.emitted('update:enabled')).toBeUndefined
 })
 it('4: saving 期间 Switch disabled — 防止重复点击', async => {
 let resolveUpdate!: => void
 vi.mocked(repositoriesApi.update).mockImplementation(
 => new Promise((resolve) => {
 resolveUpdate = => resolve({} as never)
 }),
 )
 const wrapper = mountToggle(false)
 const sw = wrapper.find('[data-testid="switch"]')
 await sw.trigger('click')
 await wrapper.vm.$nextTick
 // saving=true 时 disabled
 expect(wrapper.find('[data-testid="switch"]').attributes('disabled')).toBeDefined
 resolveUpdate
 await flushPromises
 // saving=false 后恢复
 expect(wrapper.find('[data-testid="switch"]').attributes('disabled')).toBeUndefined
 })
})
