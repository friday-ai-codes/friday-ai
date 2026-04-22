/**
 * Phase Plan 前端：AIModelConfig.apiBaseUrlError computed + error 文案渲染。
 *
 * 覆盖 （228 认证混淆 前端 UX 路径）：
 * F: useCustomApi=true + apiBaseUrl="" → 渲染 text-destructive 错误文案 + aria-invalid=true
 * G: useCustomApi=true + apiBaseUrl="https://..." → 不显示错误文案，显示说明文案
 * H: useCustomApi=false → 自定义 API 区块不展开，不可能触发 error
 *
 * 注：describe/it 标题首字母大写（F/G/H）遵循 Plan acceptance_criteria 锁定
 * （grep 断言 "F: useCustomApi..."），与 Phase ChatHeader.spec.ts 一致，
 * test/prefer-lowercase-title 规则在本文件禁用。
 */
/* eslint-disable test/prefer-lowercase-title */
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AIModelConfig from '~/components/workflow/config/AIModelConfig.vue'
// Mock workflow API — AIModelConfig onMounted 会调 getLLMSystemConfig
// vitest 会 hoist vi.mock 到 import 之前（factory 是纯工厂函数，不捕获上下文）
vi.mock('~/api/workflow', => ({
 getLLMSystemConfig: vi.fn.mockResolvedValue({ base_url: '', has_api_key: false }),
 queryLLMModels: vi.fn.mockResolvedValue({ models: }),
 querySystemLLMModels: vi.fn.mockResolvedValue({ models: }),
}))
describe('AIModelConfig.apiBaseUrlError', => {
 it('F: useCustomApi=true + apiBaseUrl="" → 渲染 destructive 错误文案 + aria-invalid=true', async => {
 const wrapper = mount(AIModelConfig, {
 props: {
 useCustomApi: true,
 apiBaseUrl: '',
 apiKey: '',
 model: '',
 },
 global: {
 stubs: {
 Input: {
 props: ['modelValue', 'ariaInvalid'],
 template: '<input:data-aria-invalid="ariaInvalid":class="$attrs.class" />',
 inheritAttrs: false,
 },
 Switch: true,
 Select: true,
 SelectContent: true,
 SelectItem: true,
 SelectTrigger: true,
 SelectValue: true,
 Label: { template: '<label><slot /></label>' },
 Button: { template: '<button><slot /></button>' },
 Separator: true,
 },
 },
 })
 // 等 onMounted loadSystemConfig resolve
 await new Promise(resolve => setTimeout(resolve, 0))
 const html = wrapper.html
 expect(html).toContain('API Base URL 为必填')
 // aria-invalid 透传到 Input stub
 const inputs = wrapper.findAll('input')
 const baseUrlInput = inputs.find(i => i.attributes('data-aria-invalid') === 'true')
 expect(baseUrlInput).toBeTruthy
 })
 it('G: useCustomApi=true + apiBaseUrl="https://api.openai.com/v1" → 不显示 error，显示说明文案', async => {
 const wrapper = mount(AIModelConfig, {
 props: {
 useCustomApi: true,
 apiBaseUrl: 'https://api.openai.com/v1',
 apiKey: '',
 model: '',
 },
 global: {
 stubs: {
 Input: true,
 Switch: true,
 Select: true,
 SelectContent: true,
 SelectItem: true,
 SelectTrigger: true,
 SelectValue: true,
 Label: { template: '<label><slot /></label>' },
 Button: { template: '<button><slot /></button>' },
 Separator: true,
 },
 },
 })
 await new Promise(resolve => setTimeout(resolve, 0))
 const html = wrapper.html
 expect(html).not.toContain('API Base URL 为必填')
 expect(html).toContain('支持 OpenAI、Ollama')
 })
 it('H: useCustomApi=false → 自定义 API 区块不展开，无 error 文案', async => {
 const wrapper = mount(AIModelConfig, {
 props: {
 useCustomApi: false,
 apiBaseUrl: '',
 apiKey: '',
 model: '',
 },
 global: {
 stubs: {
 Input: true,
 Switch: true,
 Select: true,
 SelectContent: true,
 SelectItem: true,
 SelectTrigger: true,
 SelectValue: true,
 Label: { template: '<label><slot /></label>' },
 Button: { template: '<button><slot /></button>' },
 Separator: true,
 },
 },
 })
 await new Promise(resolve => setTimeout(resolve, 0))
 const html = wrapper.html
 expect(html).not.toContain('API Base URL 为必填')
 })
})
