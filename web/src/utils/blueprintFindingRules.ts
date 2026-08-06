/**
 * AI 审查 finding 的 `[rule_id]` 前缀解析（quick-260806-vqh）。
 *
 * 后端开线程时把规则标记写进首条消息正文：`question = f"[{rule_id}] {detail}"`
 * （`blueprint_review.py`）。`detail` 本就是中文，唯独这个 snake_case 的 `rule_id`
 * 是给机器看的 —— 本模块负责在**展示层**把它剥出来换成中文标签。
 *
 * ⛔ **绝不改后端那行**：`BlueprintThread` 没有 `rule_id` 字段，跨轮去重靠
 * `_RULE_ID_TAG` 从首条消息把 rule_id 反查回来建索引。换成中文正则立刻失配 ⇒ 第二轮起
 * 既拿不到「第 N 轮仍存在」留痕、也不进「本轮已消失 → resolve」的收尾循环 ⇒ 一条
 * open+blocking 的 BLOCKER 会永久挡住确认（114-MN-03 记录过的事故形态）。
 * 汉化留在展示层还有个附带好处：历史线程无需数据迁移即刻生效。
 */

/**
 * 与后端 `blueprint_review._RULE_ID_TAG` 等价的前缀正则。
 *
 * ⚠️ **跨语言陷阱**：后端写的是显式字符类 `[A-Za-z0-9_]+` 而**不是** `\w+`，因为 Python 的
 * `\w` 是 Unicode 感知的、**会匹配中文**。JS 的 `\w` 恒等于 ASCII 的 `[A-Za-z0-9_]`，
 * 所以这里用 `\w` 与后端等价 —— 但反向移植时⛔不可把 `\w` 直接搬回 Python。
 *
 * ⛔ 不放宽字符集：`[已修复]` 这类中文前缀正是靠匹配不上才得以原样保留；放宽后它们会被
 * 当成规则标记剥掉，而它们本来就已经是人话。
 */
const RULE_ID_TAG = /^\[(\w+)\]\s*/

/** 后端 `blueprint_review.py` 产出的全部 rule_id（LLM 5 条 + 机械规则 17 条）。 */
export const FINDING_RULE_IDS = [
  // goal-backward LLM 一类
  'acceptance_uncovered',
  'truth_unsupported',
  'key_link_broken',
  'constraint_conflict',
  // LLM 不可得时的 fail-closed meta finding
  'goal_backward_unavailable',
  // 规则①前置与结构
  'precondition_missing',
  'schema_version_missing',
  'schema_invalid',
  // 规则②引用
  'citation_missing',
  'citation_missing_weak',
  // 规则③角色一致性
  'role_mismatch',
  'capability_unreferenced',
  // 规则④ API 闭环
  'api_ref_dangling',
  'support_repo_missing',
  // 规则⑤禁令与约束
  'forbidden_schedule',
  'out_of_scope_introduced',
  'constraint_ref_dangling',
  // 规则⑥仓库章程
  'charter_violation',
  'charter_boundary_risk',
  // 确认门锁定偏离（三种形态各有独立 rule_id）
  'gate_lock_violation',
  'gate_lock_violation_role',
  'gate_lock_violation_responsibility',
] as const

const KNOWN_RULE_IDS: ReadonlySet<string> = new Set(FINDING_RULE_IDS)

export interface ParsedFindingBody {
  /** 解析出的 rule_id；消息没有规则前缀时为空串。 */
  ruleId: string
  /** 剥掉前缀后的正文；没有前缀时是原文。 */
  text: string
}

/**
 * 拆开 `[rule_id] 正文` 形态的消息。
 *
 * 匹配不上（人工留言、`[已修复] …` 这类中文前缀、追加的「第 N 轮仍存在：…」）时
 * `ruleId` 为空串、`text` 是原文 —— 调用方据此决定渲不渲染徽标。
 */
export function parseFindingBody(body: unknown): ParsedFindingBody {
  const raw = typeof body === 'string' ? body : String(body ?? '')
  const match = RULE_ID_TAG.exec(raw)
  if (!match)
    return { ruleId: '', text: raw }
  return { ruleId: match[1], text: raw.slice(match[0].length) }
}

/**
 * 该 rule_id 是否有中文标签文案。
 *
 * 后端新增规则而前端没跟上时返回 `false` ⇒ 调用方回落原始 id。⛔ 不静默吞掉未知规则：
 * 显示一个陌生的英文 id 也远好过让评审人以为「这条没有分类」。
 */
export function isKnownFindingRule(ruleId: string): boolean {
  return KNOWN_RULE_IDS.has(ruleId)
}
