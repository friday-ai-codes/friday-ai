/**
 * Runners API 服务
 * 封装所有 Runner 相关的 API 调用
 */
import type { Runner } from '~/types'
import { del, get } from './client'
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
export default {
 list: listRunners,
 delete: deleteRunner,
}
