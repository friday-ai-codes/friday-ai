import type {
  AvailableModel,
  ProviderCredentialDto,
  TestConnectionResponse,
} from '~/types/providerCredential'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// ============================================================================
// Mock API client（vi.mock 自动 hoist,store 内 import 会拿到 mock 后的对象）
// ============================================================================

const listMock = vi.fn()
const retrieveMock = vi.fn()
const createMock = vi.fn()
const updateMock = vi.fn()
const removeMock = vi.fn()
const toggleActiveMock = vi.fn()
const testConnectionMock = vi.fn()
const refreshModelsMock = vi.fn()
const listProviderTypesMock = vi.fn()

vi.mock('~/api/providerCredentials', () => ({
  providerCredentialsApi: {
    list: (...args: unknown[]) => listMock(...args),
    retrieve: (...args: unknown[]) => retrieveMock(...args),
    create: (...args: unknown[]) => createMock(...args),
    update: (...args: unknown[]) => updateMock(...args),
    remove: (...args: unknown[]) => removeMock(...args),
    toggleActive: (...args: unknown[]) => toggleActiveMock(...args),
    testConnection: (...args: unknown[]) => testConnectionMock(...args),
    refreshModels: (...args: unknown[]) => refreshModelsMock(...args),
    listProviderTypes: (...args: unknown[]) => listProviderTypesMock(...args),
  },
}))

// dynamic import 保证 vi.mock 已就位后再载入 store（与 prompts.test.ts 同风格）
const { useProviderCredentialStore } = await import('~/stores/providerCredential')

// ============================================================================
// Fixtures
// ============================================================================

function makeCred(overrides: Partial<ProviderCredentialDto> = {}): ProviderCredentialDto {
  return {
    id: overrides.id ?? 'cred-1',
    provider_type: overrides.provider_type ?? 'anthropic',
    name: overrides.name ?? 'test',
    scope: overrides.scope ?? 'system',
    scope_id: overrides.scope_id ?? null,
    is_active: overrides.is_active ?? true,
    is_default: overrides.is_default ?? false,
    last_health_check_at: overrides.last_health_check_at ?? null,
    last_health_check_status: overrides.last_health_check_status ?? '',
    last_health_check_error: overrides.last_health_check_error ?? '',
    available_models: overrides.available_models ?? [],
    api_key_last4: overrides.api_key_last4 ?? '...abcd',
    has_api_key: overrides.has_api_key ?? true,
    config: overrides.config ?? {},
    default_model: overrides.default_model ?? 'claude-3-5-sonnet-20241022',
    max_concurrency: overrides.max_concurrency ?? 50,
    created_at: overrides.created_at ?? '2026-04-20T00:00:00Z',
    updated_at: overrides.updated_at ?? '2026-04-20T00:00:00Z',
  }
}

describe('useProviderCredentialStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    vi.clearAllMocks()
  })

  // --- hydrate 三分支 ---

  it('hydrate 空 sessionStorage:初始 credentials 为空数组 + lastFetchedAt=0', () => {
    const store = useProviderCredentialStore()
    expect(store.credentials).toEqual([])
    expect(store.lastFetchedAt).toBe(0)
  })

  it('hydrate 有效 snapshot:credentials / providerTypes / lastFetchedAt 从 sessionStorage 恢复', () => {
    const snapshot = {
      credentials: [makeCred({ id: 'hyd-1' })],
      providerTypes: [],
      lastFetchedAt: 123,
      currentSpaceId: null,
    }
    sessionStorage.setItem('providerCredentialCache', JSON.stringify(snapshot))
    const store = useProviderCredentialStore()
    expect(store.credentials.length).toBe(1)
    expect(store.credentials[0].id).toBe('hyd-1')
    expect(store.lastFetchedAt).toBe(123)
  })

  it('hydrate 损坏 JSON:清掉脏缓存且 credentials 保持空', () => {
    sessionStorage.setItem('providerCredentialCache', '{not-json')
    const store = useProviderCredentialStore()
    expect(store.credentials).toEqual([])
    expect(sessionStorage.getItem('providerCredentialCache')).toBeNull()
  })

  // --- fetchCredentials TTL ---

  it('fetchCredentials:30s 内同上下文命中缓存,不重复调 API', async () => {
    listMock.mockResolvedValue([makeCred()])
    const store = useProviderCredentialStore()
    await store.fetchCredentials({ scope: 'system' })
    expect(listMock).toHaveBeenCalledTimes(1)
    // 30s 内同上下文再次调用 → 命中缓存
    await store.fetchCredentials({ scope: 'system' })
    expect(listMock).toHaveBeenCalledTimes(1)
  })

  it('fetchCredentials:force=true 绕过 TTL 强制重拉', async () => {
    listMock.mockResolvedValue([makeCred()])
    const store = useProviderCredentialStore()
    await store.fetchCredentials({ scope: 'system' })
    await store.fetchCredentials({ scope: 'system', force: true })
    expect(listMock).toHaveBeenCalledTimes(2)
  })

  // --- mutation 双写 ---

  it('createCredential:新凭证插入列表头部 + sessionStorage 被 setItem', async () => {
    const newCred = makeCred({ id: 'new-1' })
    createMock.mockResolvedValueOnce(newCred)
    const store = useProviderCredentialStore()
    await store.createCredential({
      provider_type: 'anthropic',
      name: 'new',
      scope: 'system',
      default_model: 'claude-3-5-sonnet-20241022',
      available_models: [
        {
          id: 'claude-3-5-sonnet-20241022',
          display_name: 'Claude 3.5 Sonnet',
        },
      ],
      config: { api_key: 'sk-ant-test' },
    })
    expect(store.credentials[0].id).toBe('new-1')
    const raw = sessionStorage.getItem('providerCredentialCache')
    expect(raw).not.toBeNull()
    const persisted = JSON.parse(raw ?? '{}')
    expect(persisted.credentials.length).toBe(1)
    expect(persisted.credentials[0].id).toBe('new-1')
  })

  it('updateCredential:按 id 精确替换', async () => {
    const original = makeCred({ id: 'u-1', name: 'old' })
    const updated = makeCred({ id: 'u-1', name: 'new' })
    listMock.mockResolvedValueOnce([original])
    updateMock.mockResolvedValueOnce(updated)
    const store = useProviderCredentialStore()
    await store.fetchCredentials({ scope: 'system' })
    await store.updateCredential('u-1', { name: 'new' })
    expect(store.credentials[0].name).toBe('new')
  })

  it('deleteCredential:从列表按 id 移除', async () => {
    const a = makeCred({ id: 'a' })
    const b = makeCred({ id: 'b' })
    listMock.mockResolvedValueOnce([a, b])
    removeMock.mockResolvedValueOnce(undefined)
    const store = useProviderCredentialStore()
    await store.fetchCredentials({ scope: 'system' })
    await store.deleteCredential('a')
    expect(store.credentials.map(c => c.id)).toEqual(['b'])
  })

  it('toggleActive:API 成功后状态与后端返回值对齐', async () => {
    const cred = makeCred({ id: 't-1', is_active: true })
    listMock.mockResolvedValueOnce([cred])
    toggleActiveMock.mockResolvedValueOnce({ is_active: false })
    const store = useProviderCredentialStore()
    await store.fetchCredentials({ scope: 'system' })
    await store.toggleActive('t-1')
    expect(store.credentials[0].is_active).toBe(false)
  })

  it('toggleActive:API 失败时回滚到原值', async () => {
    const cred = makeCred({ id: 't-2', is_active: true })
    listMock.mockResolvedValueOnce([cred])
    toggleActiveMock.mockRejectedValueOnce(new Error('network'))
    const store = useProviderCredentialStore()
    await store.fetchCredentials({ scope: 'system' })
    await expect(store.toggleActive('t-2')).rejects.toThrow()
    expect(store.credentials[0].is_active).toBe(true)
  })

  // --- UX-06 核心:getModelsForCredential ---

  it('getModelsForCredential:cache hit(available_models 非空)不调 refreshModels', async () => {
    const models: AvailableModel[] = [{ id: 'm-1', display_name: 'M1' }]
    const cred = makeCred({ id: 'mc-1', available_models: models })
    listMock.mockResolvedValueOnce([cred])
    const store = useProviderCredentialStore()
    await store.fetchCredentials({ scope: 'system' })
    const result = await store.getModelsForCredential('mc-1')
    expect(result).toEqual(models)
    expect(refreshModelsMock).not.toHaveBeenCalled()
  })

  it('getModelsForCredential:cache miss 触发 refreshModels 并写回 credential', async () => {
    const cred = makeCred({ id: 'mc-2', available_models: [] })
    const fetched: AvailableModel[] = [{ id: 'fresh', display_name: 'Fresh' }]
    listMock.mockResolvedValueOnce([cred])
    refreshModelsMock.mockResolvedValueOnce({ available_models: fetched })
    const store = useProviderCredentialStore()
    await store.fetchCredentials({ scope: 'system' })
    const result = await store.getModelsForCredential('mc-2')
    expect(result).toEqual(fetched)
    expect(refreshModelsMock).toHaveBeenCalledWith('mc-2')
    expect(store.credentials[0].available_models).toEqual(fetched)
  })

  // --- testConnection 同步 health 字段 ---

  it('testConnection:成功后同步 last_health_check_* 到 credential', async () => {
    const cred = makeCred({ id: 'tc-1' })
    const resp: TestConnectionResponse = {
      status: 'ok',
      latency_ms: 120,
      last_health_check_at: '2026-04-20T10:00:00Z',
    }
    listMock.mockResolvedValueOnce([cred])
    testConnectionMock.mockResolvedValueOnce(resp)
    const store = useProviderCredentialStore()
    await store.fetchCredentials({ scope: 'system' })
    await store.testConnection('tc-1')
    expect(store.credentials[0].last_health_check_status).toBe('ok')
    expect(store.credentials[0].last_health_check_at).toBe('2026-04-20T10:00:00Z')
    expect(store.credentials[0].last_health_check_error).toBe('')
  })
})
