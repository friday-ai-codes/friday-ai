/**
 * 首页 Dashboard 聚合统计 API
 */

import { get } from './client'

/** 单项统计：累计 + 今日新增 */
export interface DashboardStatItem {
  total: number
  today: number
}

/** 进行中的编码工作条目 */
export interface InProgressCodingItem {
  id: string
  title: string
  repository_name: string
  status: string
  status_label: string
  /** chat = 对话发起的编码会话；workflow = 工作流发起的编码任务 */
  source: 'chat' | 'workflow'
  conversation_id?: string
  workflow_execution_id?: string
  updated_at: string
}

export interface DashboardStatsResponse {
  stats: {
    repositories: DashboardStatItem
    code_relations: DashboardStatItem
    codings: DashboardStatItem
    tech_plans: DashboardStatItem
    questions: DashboardStatItem
    documents: DashboardStatItem
  }
  in_progress: {
    coding: {
      count: number
      items: InProgressCodingItem[]
    }
  }
}

export async function getDashboardStats(): Promise<DashboardStatsResponse> {
  return get<DashboardStatsResponse>('/system/dashboard/stats/')
}
