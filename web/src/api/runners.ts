/**
 * Runners API 服务
 * 封装所有 Runner 相关的 API 调用
 */
import type { PaginatedResponse, RegistrationToken, RegistrationTokenCreate, RegistrationTokenCreateResponse, Runner, RunnerEvent, RunnerTaskAssignment } from '~/types'
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
export async function getRunner(runnerId: string): Promise<Runner> {
 return get<Runner>(`/runners/${runnerId}/`)
}
export async function getRunnerTasks(
 runnerId: string,
 params?: Record<string, string | number | undefined>,
): Promise<PaginatedResponse<RunnerTaskAssignment>> {
 return get<PaginatedResponse<RunnerTaskAssignment>>(`/runners/${runnerId}/tasks/`, params)
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
export async function getRunnerLogs(
 runnerId: string,
 params?: Record<string, string | number | undefined>,
): Promise<PaginatedResponse<RunnerEvent>> {
 return get<PaginatedResponse<RunnerEvent>>(`/runners/${runnerId}/logs/`, params)
}
export default {
 list: listRunners,
 delete: deleteRunner,
 getRunner,
 getRunnerTasks,
 listTokens,
 createToken,
 deleteToken,
 getRunnerLogs,
}
