/**
 * Friday Access Token 管理 API 客户端（Phase）
 *
 * 对应后端 server/access_tokens/views.py:AccessTokenViewSet
 * （list / create 一次性明文 / @action revoke 软吊销）。
 *
 * `client.ts` 自动拼 `/api` 前缀且在末尾补 `/`（Django 301 规避），
 * 本模块统一写相对路径 `/access-tokens/...`，URL 全部以 `/` 结尾。
 */
import type {
 AccessTokenCreatePayload,
 AccessTokenCreateResult,
 AccessTokenDto,
} from '~/types/accessToken'
import { get, post } from './client'
/** DRF 分页响应形状。 */
interface DrfPaginated<T> {
 count?: number
 next?: string | null
 previous?: string | null
 results?: T
}
/** 兼容 DRF 分页与裸 list 两种响应。 */
function extractList<T>(payload: T | DrfPaginated<T>): T {
 if (Array.isArray(payload))
 return payload
 return payload.results ??
}
export const accessTokensApi = {
 /** GET /api/access-tokens/（仅返回元数据，绝不含明文）。 */
 list: async: Promise<AccessTokenDto> => {
 const resp = await get<AccessTokenDto | DrfPaginated<AccessTokenDto>>(
 '/access-tokens/',
 )
 return extractList(resp)
 },
 /** POST /api/access-tokens/（一次性返回明文 token）。 */
 create: async (
 payload: AccessTokenCreatePayload,
 ): Promise<AccessTokenCreateResult> => {
 return post<AccessTokenCreateResult>('/access-tokens/', payload)
 },
 /** POST /api/access-tokens/<id>/revoke/（软吊销，返回更新后的元数据）。 */
 revoke: async (id: string): Promise<AccessTokenDto> => {
 return post<AccessTokenDto>(`/access-tokens/${id}/revoke/`, {})
 },
}
export default accessTokensApi
