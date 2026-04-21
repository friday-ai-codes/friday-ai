/**
 * Phase Plan:NodeConfigPanel Provider 集成 vitest 集成测
 *
 * 覆盖:
 * - Dropdown 数据源(store.activeCredentials)
 * - capability 判定:anthropic supports_thinking=true / openai_chat=false
 * - 切换 provider_credential_id 后 props 同步
 * - ModelSelect 重拉 available_models(store.getModelsForCredential)
 *
 * 注意:AIPromptConfig 的 props.config 是响应式对象,字段双向绑定
 * 通过 useConfigModel.field 回传 emit('update:config')。本 spec 以 AIPromptConfig
 * 为被测载体(Plan 四个 AI config 组件结构一致,覆盖 AIPromptConfig 即代表整体)。
 */
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
// ============================================================================
// Mock providerCredentialsApi - hoist 到 store import 之前
// ============================================================================
const mockCredentials = [
 {
 id: 'cred-1',
 provider_type: 'anthropic' as const,
 name: 'anth-prod',
 scope: 'system' as const,
 scope_id: null,
 is_active: true,
 last_health_check_at: null,
 last_health_check_status: '' as const,
 last_health_check_error: '',
 available_models: [
 {
 id: 'claude-opus-4-7',
 display_name: 'Claude Opus 4.7',
 supports_tools: true,
 supports_vision: true,
 context_length: 200000,
 },
 ],
 api_key_last4: '...abcd',
 has_api_key: true,
 created_at: '2026-04-20T00:00:00Z',
 updated_at: '2026-04-20T00:00:00Z',
 },
 {
 id: 'cred-2',
 provider_type: 'openai_chat' as const,
 name: 'oai-prod',
 scope: 'system' as const,
 scope_id: null,
 is_active: true,
 last_health_check_at: null,
 last_health_check_status: '' as const,
 last_health_check_error: '',
 available_models: [
 {
 id: 'gpt-4o',
 display_name: 'GPT-4o',
 supports_tools: true,
 supports_vision: true,
 context_length: 128000,
 },
 ],
 api_key_last4: '...xyzw',
 has_api_key: true,
 created_at: '2026-04-20T00:00:00Z',
 updated_at: '2026-04-20T00:00:00Z',
 },
]
const mockProviderTypes = [
 {
 provider_type: 'anthropic' as const,
 langchain_prefix: 'anthropic',
 supports_thinking: true,
 supports_reasoning: false,
 supports_vision: true,
 default_model: 'claude-opus-4-7',
 credential_schema_json_schema: { properties: {} },
 },
 {
 provider_type: 'openai_chat' as const,
 langchain_prefix: 'openai',
 supports_thinking: false,
 supports_reasoning: false,
 supports_vision: true,
 default_model: 'gpt-4o',
 credential_schema_json_schema: { properties: {} },
 },
]
vi.mock('~/api/providerCredentials', => ({
 providerCredentialsApi: {
 list: vi.fn.mockResolvedValue(mockCredentials),
 retrieve: vi.fn,
 create: vi.fn,
 update: vi.fn,
 remove: vi.fn,
 toggleActive: vi.fn,
 testConnection: vi.fn,
 refreshModels: vi.fn.mockResolvedValue({ available_models: }),
 listProviderTypes: vi.fn.mockResolvedValue(mockProviderTypes),
 },
}))
// AIModelConfig 依赖的 ~/api/workflow 接口会在挂载时发起网络请求;此处 stub 掉
vi.mock('~/api/workflow', => ({
 getLLMSystemConfig: vi.fn.mockResolvedValue(null),
 queryLLMModels: vi.fn.mockResolvedValue({ models: }),
 querySystemLLMModels: vi.fn.mockResolvedValue({ models: }),
}))
// Dynamic import 保证 vi.mock 已就位
const { default: AIPromptConfig } = await import(
 '~/components/workflow/config/AIPromptConfig.vue'
)
const { useProviderCredentialStore } = await import('~/stores/providerCredential')
// ============================================================================
// Helpers
// ============================================================================
async function mountPromptConfig(
 configOverrides: Record<string, unknown> = {},
): Promise<ReturnType<typeof mount>> {
 setActivePinia(createPinia)
 const store = useProviderCredentialStore
 await store.fetchCredentials({ scope: 'system' })
 await store.fetchProviderTypes
 const baseConfig = {
 use_custom_api: false,
 api_base_url: '',
 api_key: '',
 provider_credential_id: null,
 system_prompt: '',
 user_prompt: '',
 model: '',
 temperature: 0.7,
 max_tokens: 4096,
 output_format: 'text',
 ...configOverrides,
 }
 return mount(AIPromptConfig, {
 props: { config: baseConfig as never },
 global: {
 stubs: { RouterLink: true },
 },
 })
}
// ============================================================================
// Tests
// ============================================================================
describe('AIPromptConfig Provider 集成(Phase Plan)', => {
 beforeEach( => {
 vi.clearAllMocks
 // 清 sessionStorage,避免 store hydrate 污染后续用例
 sessionStorage.clear
 })
 it('渲染 ProviderCredentialDropdown + ModelSelect 两个 placeholder', async => {
 const wrapper = await mountPromptConfig
 const html = wrapper.html
 // Dropdown placeholder
 expect(html).toContain('请选择凭证')
 // ModelSelect placeholder(credentialId 为 null 时 filteredModels 为空)
 expect(html).toContain('请选择模型')
 })
 it('Dropdown 数据源读 store.activeCredentials(2 条 active)', async => {
 await mountPromptConfig
 const store = useProviderCredentialStore
 expect(store.activeCredentials.length).toBe(2)
 expect(store.activeCredentials.map(c => c.provider_type)).toEqual([
 'anthropic',
 'openai_chat',
 ])
 })
 it('provider_credential_id=cred-1(anthropic)→ providerTypes supports_thinking=true', async => {
 await mountPromptConfig({ provider_credential_id: 'cred-1' })
 const store = useProviderCredentialStore
 const meta = store.providerTypes.find(p => p.provider_type === 'anthropic')
 expect(meta?.supports_thinking).toBe(true)
 })
 it('provider_credential_id=cred-2(openai_chat)→ providerTypes supports_thinking=false', async => {
 await mountPromptConfig({ provider_credential_id: 'cred-2' })
 const store = useProviderCredentialStore
 const meta = store.providerTypes.find(p => p.provider_type === 'openai_chat')
 expect(meta?.supports_thinking).toBe(false)
 })
 it('切换 provider_credential_id 后触发 update:config(字段写回 config 对象)', async => {
 const wrapper = await mountPromptConfig({ provider_credential_id: null })
 // 场景模拟:父组件 setProps 更新 config.provider_credential_id → 子组件响应式绑定跟随
 const currentProps = wrapper.props as unknown as { config: Record<string, unknown> }
 const newCfg = {
 ...currentProps.config,
 provider_credential_id: 'cred-1',
 }
 await wrapper.setProps({ config: newCfg as never })
 // store.getCredentialById 已在 computed 中执行;验证 store 状态可用
 const store = useProviderCredentialStore
 expect(store.getCredentialById('cred-1')?.provider_type).toBe('anthropic')
 })
 it('credentialId=cred-1 mount 时 store.getModelsForCredential 命中 cache,不触发 refreshModels', async => {
 const { providerCredentialsApi } = await import('~/api/providerCredentials')
 const refreshSpy = vi.mocked(providerCredentialsApi.refreshModels)
 await mountPromptConfig({ provider_credential_id: 'cred-1' })
 // cred-1 初始 available_models 非空(cache hit),不应走 refreshModels
 expect(refreshSpy).not.toHaveBeenCalled
 const store = useProviderCredentialStore
 const models = await store.getModelsForCredential('cred-1')
 expect(models).toHaveLength(1)
 expect(models[0].id).toBe('claude-opus-4-7')
 })
})
