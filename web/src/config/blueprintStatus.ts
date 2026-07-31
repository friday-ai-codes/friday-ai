/**
 * 蓝图状态徽标配置与三组状态白名单（Phase 115，UI-SPEC §13.9 / §7.9 / §9.1）。
 *
 * 与 `~/config/status.ts` 的两处刻意差异：
 * 1. 配置存 **`labelKey`（i18n key）而不是中文 `label`** —— `status.ts` 是内联中文的老面，
 *    本相位新页面全部文案走 vue-i18n（⛔ 配置里不写中文字面量）。
 * 2. 只 `import type { StatusConfig }` 复用类型契约，⛔ **不改 `status.ts`**（CREATE-ONLY），
 *    也不往它的 `type` 联合里加 `'blueprint'`。
 *
 * `icon` 存**裸图标名**（`lucide--pen-line`），与 `status.ts` 全域一致：消费组件内部做
 * `` `icon-[${config.icon}]` `` 拼接。⚠️ 拼接发生在运行期 ⇒ 这批图标必须在
 * `styles/main.css` 的 `@source inline(...)` 里 safelist（115-02 已补齐 12 个）。
 */

import type { StatusConfig } from '~/config/status'

/** 蓝图状态徽标配置：把 `status.ts` 的中文 `label` 换成 i18n key。 */
export interface BlueprintStatusConfig extends Omit<StatusConfig, 'label'> {
  labelKey: string
}

/**
 * 12 态徽标配置（11 个状态机取值 + `''`）。
 *
 * 与后端 `delivery.models.BlueprintStatus` 枚举同步；`''` 是 **v0 旧数据**（升级前建的
 * artifact 未进状态机），是合法输入而非未知态 —— 它必须命中本表的 `''` 档（「旧版方案」），
 * ⛔ 不得掉进 `getBlueprintStatusConfig` 的 unknown 兜底。
 */
export const BLUEPRINT_STATUS_CONFIG: Record<string, BlueprintStatusConfig> = {
  'researching': { labelKey: 'knowledge.blueprints.status.researching', icon: 'lucide--scan-eye', variant: 'info', animate: true },
  'drafting': { labelKey: 'knowledge.blueprints.status.drafting', icon: 'lucide--pen-line', variant: 'info', animate: true },
  'ai_reviewing': { labelKey: 'knowledge.blueprints.status.ai_reviewing', icon: 'lucide--shield-check', variant: 'info', animate: true },
  'needs_clarification': { labelKey: 'knowledge.blueprints.status.needs_clarification', icon: 'lucide--help-circle', variant: 'warning' },
  'pending_review': { labelKey: 'knowledge.blueprints.status.pending_review', icon: 'lucide--user-check', variant: 'warning' },
  'confirmed': { labelKey: 'knowledge.blueprints.status.confirmed', icon: 'lucide--check-circle', variant: 'success' },
  'implementing': { labelKey: 'knowledge.blueprints.status.implementing', icon: 'lucide--hammer', variant: 'info', animate: true },
  'implemented': { labelKey: 'knowledge.blueprints.status.implemented', icon: 'lucide--check-check', variant: 'success' },
  'archived': { labelKey: 'knowledge.blueprints.status.archived', icon: 'lucide--archive', variant: 'muted' },
  'failed': { labelKey: 'knowledge.blueprints.status.failed', icon: 'lucide--x-circle', variant: 'destructive' },
  'superseded': { labelKey: 'knowledge.blueprints.status.superseded', icon: 'lucide--file-x', variant: 'muted' },
  '': { labelKey: 'knowledge.blueprints.status.legacy', icon: 'lucide--file-text', variant: 'outline' },
}

/**
 * 未知态兜底配置。
 *
 * ⚠️ `labelKey` 刻意**不放在 `knowledge.blueprints.status.*` 下**：那个子树的 12 个键与
 * `BLUEPRINT_STATUS_CONFIG` 的 12 档**一一对应**（配置单测锁死这个等式），多一个 `unknown`
 * 会破坏它。
 */
const UNKNOWN_STATUS_CONFIG: BlueprintStatusConfig = {
  labelKey: 'knowledge.blueprints.statusUnknown',
  icon: 'lucide--help-circle',
  variant: 'muted',
}

/**
 * 取状态徽标配置；未在表内的取值走 unknown 兜底。
 *
 * ⚠️ `''` 命中 `''` 那一档（「旧版方案」）而**不是** unknown —— 用 `in` 判定而非真值判定。
 */
export function getBlueprintStatusConfig(status: string): BlueprintStatusConfig {
  return BLUEPRINT_STATUS_CONFIG[status] ?? UNKNOWN_STATUS_CONFIG
}

/**
 * 可编辑白名单（六值，成员逐字对齐后端 `blueprint_lifecycle_service.EDITABLE_BLUEPRINT_STATUSES`）。
 *
 * ⚠️ 与后端的刻意差异：后端那个闸的入参是 **artifact**，前端这个是 **status 字符串** ——
 * 前端拿到的只有响应体里的 `current_status`，不该也不能重建 artifact 语义。
 *
 * ⛔ 这个白名单**只驱动「渲染与否」，不是权限判断**：真正的闸在后端，越界一律以状态码为准。
 */
export const EDITABLE_BLUEPRINT_STATUSES: ReadonlySet<string> = new Set([
  '',
  'researching',
  'drafting',
  'ai_reviewing',
  'needs_clarification',
  'pending_review',
])

/**
 * 该状态下是否渲染作答 / 评论入口。
 *
 * `false` 时（`confirmed` / `implementing` / `implemented` / `archived` / `superseded` / `failed`）：
 * 作答输入框与选区 popover 的「发起评论」按钮**不存在于 DOM**（不是 `disabled`）；
 * finding 的处置（resolve / dismiss）**不受本闸约束** —— 后端没给它加状态闸，且那是死锁出口。
 */
export function isBlueprintEditable(status: string): boolean {
  return EDITABLE_BLUEPRINT_STATUSES.has(status)
}

/**
 * 轮询开启的三个「生成中」状态（供 `~/composables/useBlueprintLive` 消费）。
 *
 * ⛔ **不在 composable 里另写一份**：轮询判据只能有一个来源。进入 `pending_review` 与任一
 * 终态即自动停。
 */
export const LIVE_BLUEPRINT_STATUSES: ReadonlySet<string> = new Set([
  'researching',
  'drafting',
  'ai_reviewing',
])

/**
 * 编排**已确定走完**的四态（供阶段时间线把发过事件的阶段一律收成「完成」）。
 *
 * ⛔ 刻意**不含** `failed` 与 `superseded`：
 * - `failed` 下把阶段收成「完成」会把失败讲成成功，那正是本集合要避免的反面；
 * - `superseded` 是「被新版本取代」，它自己那一轮可能根本没跑完，无从推断。
 *
 * ⚠️ 这不是「终态」的通用定义，只服务于时间线的末态推断，⛔ 不要拿它当只读闸
 * （只读闸是 `isBlueprintEditable` 的反面，两者成员刻意不同）。
 */
export const ORCHESTRATION_SETTLED_BLUEPRINT_STATUSES: ReadonlySet<string> = new Set([
  'confirmed',
  'implementing',
  'implemented',
  'archived',
])

/** 版本原因徽标配置（`produced_by_ref` 前缀 → 徽标），`labelKey` 同样走 i18n。 */
export interface ProducedByConfig {
  labelKey: string
  icon: string
  variant: StatusConfig['variant']
}

/**
 * `produced_by_ref` 的四前缀映射（UI-SPEC §9.1）。
 *
 * 与后端落版本时写入的前缀同步：`human_edit:` 同时是 B3 人工块保护的判据源。
 */
export const PRODUCED_BY_PREFIXES: ReadonlyArray<[string, ProducedByConfig]> = [
  ['human_edit:', { labelKey: 'knowledge.blueprints.version.reasonHumanEdit', icon: 'lucide--user-pen', variant: 'secondary' }],
  ['ai_review_reflow:', { labelKey: 'knowledge.blueprints.version.reasonAiReviewReflow', icon: 'lucide--refresh-cw', variant: 'info' }],
  ['human_block_restore:', { labelKey: 'knowledge.blueprints.version.reasonHumanBlockRestore', icon: 'lucide--shield', variant: 'warning' }],
  ['blueprint_review_reject:', { labelKey: 'knowledge.blueprints.version.reasonBlueprintReviewReject', icon: 'lucide--undo-2', variant: 'destructive' }],
]

/** 四前缀都不命中时的第五档：AI 产出。 */
const AI_PRODUCED_CONFIG: ProducedByConfig = {
  labelKey: 'knowledge.blueprints.version.reasonAiGenerated',
  icon: 'lucide--sparkles',
  variant: 'muted',
}

/**
 * 取版本原因徽标（五档：四前缀 + AI 产出兜底）。
 *
 * @example producedByReason('human_edit:u-1') // → 人工编辑档
 * @example producedByReason('') // → AI 产出档
 */
export function producedByReason(ref: string): ProducedByConfig {
  const value = typeof ref === 'string' ? ref : ''
  for (const [prefix, config] of PRODUCED_BY_PREFIXES) {
    if (value.startsWith(prefix))
      return config
  }
  return AI_PRODUCED_CONFIG
}
