/**
 * Setup API 服务
 * 封装首启向导相关的 API 调用（无需认证，AllowAny）
 */

import { get, post } from './client'

export interface SetupStatus {
  needs_setup: boolean
  is_initialized: boolean
}

export interface SetupInitRequest {
  username: string
  password: string
  display_name?: string
}

/**
 * 查询系统初始化状态（AllowAny，无需认证）
 * 路由守卫在 initAuth() 前调用，fail-safe：异常时调用方 catch 按已初始化处理
 */
export async function getSetupStatus(): Promise<SetupStatus> {
  return get<SetupStatus>('/auth/setup/status/')
}

/**
 * 首启初始化：创建管理员账号
 * Phase 1 最小实现；注意 setup.vue 的 POST 提交保持原始 fetch，
 * initSetup 供外部消费方和测试使用，避免 403 触发全局 auth:forbidden 重定向
 */
export async function initSetup(data: SetupInitRequest): Promise<void> {
  return post<void>('/auth/setup/', data)
}

export default { getSetupStatus, initSetup }
