/**
 * 蓝图交付物的**判别**与**内联中文文案**（同步点 2 收尾 · 三处触点共用）。
 *
 * 服务于三处「老面」触点：`chat/TechPlanCard.vue` / `execution/NodeDataTab.vue` /
 * `delivery/ArtifactTimeline.vue`。三者都早于 Phase 115 存在、都**不接 vue-i18n**
 * （各自 docstring / 组件家族有明确的内联中文决定），而 `~/config/blueprintStatus.ts`
 * 存的是 i18n key ⇒ 它们用不了那张表。本模块补上「同一批状态的中文字面量」这一层。
 *
 * ⛔ **不改 `blueprintStatus.ts`**：那是 115 相位新页面的 i18n 面，两个消费群体的文案
 * 载体不同（key vs 中文），强行合并只会逼一边改掉自己既定的约定。
 *
 * ⚠️ **两份定义 + 一条漂移守卫**（形状照后端 `blueprint_observation.BLUEPRINT_STATUS_MESSAGES`
 * 与 chat 那份的相等守卫）：`__tests__/blueprintArtifact.spec.ts` 逐键断言
 * :data:`BLUEPRINT_STATUS_TEXT` 与 `zh-CN.json` 的 `knowledge.blueprints.status.*`
 * **逐字相等**、且键集与 `BLUEPRINT_STATUS_CONFIG` 完全一致。改了一边不改另一边即红。
 */

/**
 * 蓝图 content 的判别字段取值（与后端 `blueprint_schema.BLUEPRINT_SCHEMA_VERSION` 同源）。
 *
 * ⭐ 判别口径与 `delivery/artifacts/builtin_types.py` **逐字相同**：只有 `content.schema_version`
 * 严格等于本常量才走蓝图分支，其余（含 `undefined` / `''` / 未来的 `blueprint/v2`）一律
 * 落 v0 旧链渲染路径 —— v0 产物必须逐像素不变。
 */
export const BLUEPRINT_SCHEMA_VERSION = 'blueprint/v1'

/**
 * 是否为 blueprint/v1。
 *
 * 🔴 **允许清单而非拒绝清单**（与 `TechPlanCard.isUnresearched` 同一条纪律）：写成
 * `!== undefined` 会让任何将来的新 schema 默认被当成蓝图渲染。未知取值一律按 v0 处理，
 * 失败代价方向正确（多渲一次旧形态 ≪ 把未知结构当蓝图渲染出一片空白）。
 */
export function isBlueprintSchemaVersion(value: unknown): boolean {
  return value === BLUEPRINT_SCHEMA_VERSION
}

/**
 * 11 个状态机取值 + `''`（v0 旧数据）的中文文案。
 *
 * `''` 是**合法输入而非未知态**（升级前建的 artifact 未进状态机）——用 `in` 判定而非真值
 * 判定才命中它，与 `getBlueprintStatusConfig` 同纪律。
 */
export const BLUEPRINT_STATUS_TEXT: Record<string, string> = {
  'researching': '调研中',
  'drafting': '产出中',
  'ai_reviewing': 'AI 审查中',
  'needs_clarification': '需要澄清',
  'pending_review': '待人类审查',
  'confirmed': '已确认',
  'implementing': '实施中',
  'implemented': '实施完成',
  'archived': '已归档',
  'failed': '已失败',
  'superseded': '已废弃',
  '': '旧版方案',
}

/** 表外取值的兜底文案（⛔ 不并进上表：上表的 12 档与 i18n 子树一一对应，被守卫锁死）。 */
export const BLUEPRINT_STATUS_UNKNOWN_TEXT = '未知状态'

/** 取状态中文；表外取值走 unknown 兜底（`''` 命中「旧版方案」而非兜底）。 */
export function blueprintStatusText(status: string): string {
  return BLUEPRINT_STATUS_TEXT[status] ?? BLUEPRINT_STATUS_UNKNOWN_TEXT
}

/**
 * 「等人处置」的两个状态：触点上用它决定徽标语气（warning）而非中性。
 *
 * ⛔ 只驱动呈现语气，**不是**任何闸 —— 真正的放行判据在后端（工作流侧 `pending_review`
 * 不产出 `plan` 载荷那一条）。
 */
export const BLUEPRINT_ATTENTION_STATUSES: ReadonlySet<string> = new Set([
  'needs_clarification',
  'pending_review',
])

/**
 * 蓝图查看器路由（Phase 115-06 建，`:id` = `artifact_id`）。
 *
 * ⛔ 三处触点都经本函数拼路径，不各写一遍字面量：查看器路由若改名，改一处即可。
 */
export function blueprintViewerPath(artifactId: string): string {
  return `/knowledge/blueprints/${artifactId}`
}
