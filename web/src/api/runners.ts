/**
 * Runners API 服务
 * 封装所有 Runner 相关的 API 调用
 */
import type { RegistrationToken, RegistrationTokenCreate, RegistrationTokenCreateResponse, Runner } from '~/types'
import { del, get, post } from './client'
/**
 * 获取 Runner 列表
 */
export async function listRunners: Promise<Runner> {
 return get<Runner>('/runners/')
}
/**
 * 删除 Runner
 */
export async function deleteRunner(runnerId: string): Promise<void> {
 return del(`/runners/${runnerId}/`)
}
export async function listTokens: Promise<RegistrationToken> {
 return get<RegistrationToken>('/runners/tokens/')
}
export async function createToken(data: RegistrationTokenCreate): Promise<RegistrationTokenCreateResponse> {
 return post<RegistrationTokenCreateResponse>('/runners/tokens/', data)
}
export async function deleteToken(tokenId: string): Promise<void> {
 return del(`/runners/tokens/${tokenId}/`)
}
export default {
 list: listRunners,
 delete: deleteRunner,
 listTokens,
 createToken,
 deleteToken,
}
