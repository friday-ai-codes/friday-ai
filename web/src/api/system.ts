/**
 * 系统级健康检查 API
 */
import { get } from './client'
export type ServiceHealthStatus = 'healthy' | 'unhealthy' | 'not_configured'
export type OverallHealthStatus = 'healthy' | 'degraded' | 'unhealthy'
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
 services: ServiceHealth
}
export async function getSystemHealth: Promise<SystemHealth> {
 return get<SystemHealth>('/system/health/')
}
