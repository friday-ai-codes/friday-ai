/**
 * Friday 工具令牌绑定（Tool Token Binding）管理 Pinia Store
 *
 * 安全姿态（T-10-05，mirror accessTokens store）：
 * - 仅缓存绑定与可绑定工具元数据；令牌明文 / hash 绝不写入任何 store state。
 * - 绑定 DTO 中的令牌仅为 BoundTokenDto（name + 前后缀指纹 + is_valid），无明文来源。
 * - 错误统一 re-throw，供 UI 层 useErrorHandler 承接。
 */

import type {
  BindableToolDto,
  ToolBindingDto,
  ToolBindingUpsertPayload,
} from '~/types/toolBinding'
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { toolBindingsApi } from '~/api/toolBindings'

export const useToolBindingStore = defineStore('toolBinding', () => {
  // ============================================================================
  // State（仅绑定/工具元数据，无明文）
  // ============================================================================
  const bindings = ref<ToolBindingDto[]>([])
  const bindableTools = ref<BindableToolDto[]>([])
  const loading = ref(false)
  const lastError = ref<string | null>(null)

  // ============================================================================
  // Actions（错误统一 re-throw，供 UI 层 useErrorHandler 承接）
  // ============================================================================

  /** 拉取当前用户的工具令牌绑定列表。 */
  async function fetchBindings(): Promise<ToolBindingDto[]> {
    loading.value = true
    lastError.value = null
    try {
      const list = await toolBindingsApi.list()
      bindings.value = list
      return list
    }
    catch (e) {
      lastError.value = e instanceof Error ? e.message : '加载工具绑定失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  /** 拉取可绑定的 mcp/skill 工具列表。 */
  async function fetchBindable(): Promise<BindableToolDto[]> {
    loading.value = true
    lastError.value = null
    try {
      const list = await toolBindingsApi.bindable()
      bindableTools.value = list
      return list
    }
    catch (e) {
      lastError.value = e instanceof Error ? e.message : '加载可绑定工具失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  /**
   * 绑定 / 换绑：成功后就地更新（同工具替换）或插入绑定列表。
   *
   * 仅缓存返回的绑定元数据（含 BoundTokenDto 指纹），绝不缓存任何明文。
   */
  async function upsertBinding(
    payload: ToolBindingUpsertPayload,
  ): Promise<ToolBindingDto> {
    loading.value = true
    lastError.value = null
    try {
      const updated = await toolBindingsApi.upsert(payload)
      const idx = bindings.value.findIndex(
        b => b.remote_tool === updated.remote_tool,
      )
      if (idx >= 0)
        bindings.value = bindings.value.map((b, i) => (i === idx ? updated : b))
      else
        bindings.value = [updated, ...bindings.value]
      return updated
    }
    catch (e) {
      lastError.value = e instanceof Error ? e.message : '绑定工具令牌失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  /** 解绑：成功后从绑定列表移除该项。 */
  async function unbindBinding(id: number): Promise<void> {
    loading.value = true
    lastError.value = null
    try {
      await toolBindingsApi.unbind(id)
      bindings.value = bindings.value.filter(b => b.id !== id)
    }
    catch (e) {
      lastError.value = e instanceof Error ? e.message : '解绑工具令牌失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  return {
    // state
    bindings,
    bindableTools,
    loading,
    lastError,
    // actions
    fetchBindings,
    fetchBindable,
    upsertBinding,
    unbindBinding,
  }
})
