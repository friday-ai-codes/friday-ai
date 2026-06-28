/**
 * Human Task Center 统一待办 API（Chassis v2 · P8）。
 *
 * 对接后端 `delivery/api/human_task_views.py`：统一收件箱（物化 HumanTask ∪ 投影的
 * 待答澄清 / 待审批 / 失败反应重试）、开原生待办、物化待办动作（resolve/skip/reassign）、
 * 投影澄清按题作答回流。
 */

import { get, post } from './client'

/** 待办类型。 */
export type HumanTaskType
  = | 'clarification'
    | 'approval'
    | 'risk_ack'
    | 'takeover'
    | 'reaction_retry'

/** 待办状态。 */
export type HumanTaskStatus = 'open' | 'done' | 'skipped' | 'expired'

/** 统一待办呈现（物化行与投影行共用形态）。 */
export interface HumanTaskView {
  /** 物化行为 UUID；投影行为合成 id（如 `clarification:<uuid>`）。 */
  id: string
  task_type: HumanTaskType
  scope: string
  subject_id: string
  status: HumanTaskStatus
  /** "materialized"（落表）| "projection"（查询时投影）。 */
  source: 'materialized' | 'projection'
  source_signal: string
  assignee_user_id: string | null
  assignee_role: string | null
  artifact_version_id: string | null
  due_at: string | null
  created_at: string | null
  resolved_at: string | null
  resolution: Record<string, unknown>
  /** UI 呈现标题（澄清取首个待答问题 / 审批取节点名 / 反应取目标类型）。 */
  title: string
  /** 类型相关元数据（澄清携 questions / 审批携 node_execution_id / 反应携 last_error 等）。 */
  detail: Record<string, any>
}

/** 收件箱过滤参数。 */
export interface InboxParams {
  /** 仅看指派给当前用户的物化待办。 */
  mine?: boolean
  /** 是否叠加投影（默认 true）。 */
  includeProjections?: boolean
}

/** 开原生待办入参（risk_ack / takeover 等）。 */
export interface OpenHumanTaskBody {
  task_type: HumanTaskType
  scope: string
  subject_id: string
  assignee_user_id?: string | null
  assignee_role?: string | null
  source_signal?: string
  due_at?: string | null
  dedup_key?: string
  resolution?: Record<string, unknown>
}

/** 单题作答。 */
export interface ClarificationAnswer {
  question_id: string
  selected: unknown
  freeform_text?: string
}

/**
 * 拉统一待办收件箱（"我需要处理什么"）。
 */
export async function listHumanTasks(params: InboxParams = {}): Promise<HumanTaskView[]> {
  const query: Record<string, string> = {}
  if (params.mine)
    query.mine = '1'
  if (params.includeProjections === false)
    query.include_projections = '0'
  return get<HumanTaskView[]>('/delivery/human-tasks/', query)
}

/**
 * 开一条原生待办（risk_ack / takeover 等）。
 */
export async function openHumanTask(body: OpenHumanTaskBody): Promise<HumanTaskView> {
  return post<HumanTaskView>('/delivery/human-tasks/', body)
}

/**
 * 处理（完成）物化待办，回流主链路。
 */
export async function resolveHumanTask(
  taskId: string,
  resolution: Record<string, unknown> = {},
): Promise<{ id: string, status: HumanTaskStatus }> {
  return post(`/delivery/human-tasks/${taskId}/resolve/`, { resolution })
}

/**
 * 跳过物化待办。
 */
export async function skipHumanTask(
  taskId: string,
  reason = '',
): Promise<{ id: string, status: HumanTaskStatus }> {
  return post(`/delivery/human-tasks/${taskId}/skip/`, { reason })
}

/**
 * 转派物化待办。
 */
export async function reassignHumanTask(
  taskId: string,
  payload: { assignee_user_id?: string | null, assignee_role?: string | null },
): Promise<{ id: string, status: HumanTaskStatus }> {
  return post(`/delivery/human-tasks/${taskId}/reassign/`, payload)
}

/**
 * 对投影的待答澄清按题作答（经后端 ClarificationService 单一入口回流）。
 */
export async function answerClarification(
  clarificationId: string,
  answers: ClarificationAnswer[],
): Promise<{ clarification_id: string, status: HumanTaskStatus }> {
  return post(`/delivery/human-tasks/clarification/${clarificationId}/answer/`, { answers })
}

export default {
  listHumanTasks,
  openHumanTask,
  resolveHumanTask,
  skipHumanTask,
  reassignHumanTask,
  answerClarification,
}
