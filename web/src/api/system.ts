/**
 * 系统级健康检查 API + 通用设置扩展
 */

import { get } from './client'

export type ServiceHealthStatus = 'healthy' | 'unhealthy' | 'not_configured'
/**
 * 整体状态只区分正常 / 异常：未配置视为正常。
 */
export type OverallHealthStatus = 'healthy' | 'unhealthy'

export interface ServiceHealth {
  name: 'database' | 'redis' | 'feishu' | 'qdrant' | string
  label: string
  status: ServiceHealthStatus
  message?: string
  latency_ms?: number
}

export interface SystemHealth {
  overall: OverallHealthStatus
  checked_at: string
  services: ServiceHealth[]
}

export async function getSystemHealth(): Promise<SystemHealth> {
  return get<SystemHealth>('/system/health/')
}

// ============================================================================
// 通用设置：系统信息 / 备份 / 恢复
// ============================================================================

/** 系统信息响应。 */
export interface SystemInfoResponse {
  version: { current: string }
  changelog_url: string
  environment: Record<string, string>
  image: {
    task_runner_image: string
  }
  database: {
    engine: string
    path: string
    size: string
  }
  python_version: string
  django_version: string
}

export async function getSystemInfo(): Promise<SystemInfoResponse> {
  return get<SystemInfoResponse>('/settings/info/')
}

/** 下载数据库备份（返回 Blob，由调用方触发下载）。 */
export async function downloadSystemBackup(): Promise<Blob> {
  const resp = await fetch('/api/settings/backup/', {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${localStorage.getItem('access_token') ?? ''}`,
    },
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: '备份下载失败' }))
    throw new Error(err.detail ?? '备份下载失败')
  }
  return resp.blob()
}

/** 上传备份文件恢复数据库。 */
export async function restoreSystemBackup(file: File): Promise<{ detail: string, restored_tables: number }> {
  const formData = new FormData()
  formData.append('file', file)
  const resp = await fetch('/api/settings/backup/', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${localStorage.getItem('access_token') ?? ''}`,
    },
    body: formData,
  })
  const data = await resp.json()
  if (!resp.ok) {
    throw new Error(data.detail ?? '恢复失败')
  }
  return data
}
