/**
 * 截图识需求 API（Phase 35 screenshot-recall，VIS-01）。
 *
 * 消费 35-01 后端契约：上传截图（multipart `screenshot`）→ 多模态 vision LLM 提语义
 * → 文本 query 复用既有交付知识检索召回 work_item 需求。全程瞬态（不持久化原图、
 * 不建图片向量库）；无 vision 模型/提取失败时后端 graceful 降级（`degraded === true`）。
 *
 * 字段名与 35-01 后端 serializer / 35-UI-SPEC「API Contract」严格对齐；
 * `post` 在 body 为 `FormData` 时自动跳过 JSON Content-Type（见 `client.ts` lines 127-137）。
 */

import { post } from './client'

/** 多模态提取的语义（任一段可缺省）。 */
export interface ExtractedSemantics {
  /** OCR / 文字。 */
  text?: string
  /** UI 控件描述。 */
  ui_elements?: string
  /** 业务意图。 */
  business_intent?: string
}

/** 单条召回的需求（与后端 work_item 召回项对齐）。 */
export interface RecalledRequirement {
  work_item_id: string
  title: string
  /** 飞书 / 详情外链（可选）。 */
  link?: string
  /** 相关度 0..1（可选）。 */
  relevance?: number
  /** 召回来源（rag / 反查，可选）。 */
  source?: string
}

/** 一次截图识需求的同步结果（degraded 三态）。 */
export interface ScreenshotRecallResult {
  /** 无 vision 模型 / 提取失败 → true（与召回异常区分）。 */
  degraded: boolean
  /** 降级原因码：'no_vision_model'（配置问题）| 'extraction_failed'（运行期失败）。 */
  degraded_code?: 'no_vision_model' | 'extraction_failed'
  /** 后端已脱敏的降级原因（可选）。 */
  degraded_reason?: string
  /** 提取到的语义（可选展示）。 */
  semantics?: ExtractedSemantics
  /** 派生的文本 query（可选展示）。 */
  query?: string
  /** 召回的需求列表（可能为空）。 */
  results: RecalledRequirement[]
}

export const screenshotRecallApi = {
  /** 上传截图并同步返回识别 + 召回结果。 */
  recall: (file: File): Promise<ScreenshotRecallResult> => {
    const fd = new FormData()
    fd.append('screenshot', file)
    return post<ScreenshotRecallResult>('/delivery/screenshot-recall/', fd)
  },
}
