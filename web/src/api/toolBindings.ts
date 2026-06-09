/**
 * Friday 工具令牌绑定（Tool Token Binding）管理 API 客户端
 *
 * 对应后端 server/tools/views.py 的绑定/可绑定工具端点
 * （list / bindable / upsert / unbind）。
 *
 * 安全（10-01 决策）：浏览器 client **绝不**引用工具执行端点（PAT-only 的
 * 容器回调）；浏览器仅做绑定的 list/bindable/upsert/unbind。
 *
 * `client.ts` 自动拼 `/api` 前缀且在末尾补 `/`（Django 301 规避），
 * 本模块统一写相对路径 `/tools/...`，URL 全部以 `/` 结尾。
 */

import type {
  BindableToolDto,
  ToolBindingDto,
  ToolBindingUpsertPayload,
} from '~/types/toolBinding'
import { del, get, post } from './client'

/** DRF 分页响应形状。 */
interface DrfPaginated<T> {
  count?: number
  next?: string | null
  previous?: string | null
  results?: T[]
}

/** 兼容 DRF 分页与裸 list 两种响应。 */
function extractList<T>(payload: T[] | DrfPaginated<T>): T[] {
  if (Array.isArray(payload))
    return payload
  return payload.results ?? []
}

export const toolBindingsApi = {
  /** GET /api/tools/bindings/（当前用户的绑定，仅元数据，绝不含明文）。 */
  list: async (): Promise<ToolBindingDto[]> => {
    const resp = await get<ToolBindingDto[] | DrfPaginated<ToolBindingDto>>(
      '/tools/bindings/',
    )
    return extractList(resp)
  },

  /** GET /api/tools/bindable/（可绑定的 mcp/skill 工具）。 */
  bindable: async (): Promise<BindableToolDto[]> => {
    const resp = await get<BindableToolDto[] | DrfPaginated<BindableToolDto>>(
      '/tools/bindable/',
    )
    return extractList(resp)
  },

  /** POST /api/tools/bindings/（绑定/换绑，返回绑定元数据）。 */
  upsert: async (
    payload: ToolBindingUpsertPayload,
  ): Promise<ToolBindingDto> => {
    return post<ToolBindingDto>('/tools/bindings/', payload)
  },

  /** DELETE /api/tools/bindings/<id>/（解绑）。 */
  unbind: async (id: number): Promise<void> => {
    return del<void>(`/tools/bindings/${id}/`)
  },
}

export default toolBindingsApi
