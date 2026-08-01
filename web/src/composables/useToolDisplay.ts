/**
 * 工具调用展示逻辑的单一权威。
 *
 * 抽自 ChatMessageBubble.vue，供 ChatMessageBubble / ToolProcessGroup 共用：
 *
 * - `toolLabel`：工具名 → 中文标签。
 * - `toolAction`：工具调用 → 一行人类可读摘要；对 search / relevance 等工具
 *   注入「仓库名称」而非裸 UUID（用户诉求 2 / 3）。
 * - `relevanceCandidates`：解析 analyze_repository_relevance 结果里的候选仓库。
 * - `routingDecisionView`：在候选之上再产出分组 / 跨组 / 降级三层事实
 *   （ROUTE-01 / ROUTE-02 / ROUTE-07 / RELY-03 的数据层）。
 * - `collectRepoNames`：从一次工具调用里抽取 repository_id → name 贡献，
 *   供上层聚合成会话级 id→name 映射。
 */

import type { RoutingGroup } from '~/types/routing'

export interface RelevanceCandidate {
  id: string
  name: string
  score: number
  level: 'high' | 'medium' | 'low'
  evidence?: string
  /**
   * 归属组（ROUTE-01）。**缺失或空串一律视为 global**——后端 pydantic 字段的
   * 默认值就是空串，用 `??` 兜底会让空串漏过去，那条候选在两个分区的 filter
   * 上都不匹配、两个分区都不渲染它，而组计数仍把它算进总数。
   */
  group: RoutingGroup
  /** 分数分解（ROUTE-07）：信号名 → 贡献值，Σ值 == score。缺失为空对象。 */
  breakdown: Record<string, number>
  /** 凸组合排序分（旁路字段）：**只参与排序**，不进任何可见文案。 */
  scoreRanked?: number
}

/** 工具名 → 中文。覆盖 server/agents/tools 下全部面向对话的工具。 */
export const TOOL_LABELS: Record<string, string> = {
  // 空间 / 仓库 / 文件
  browse_file_content: '浏览文件',
  list_space_structure: '空间结构',
  get_space_overview: '空间概览',
  list_space_repositories: '仓库列表',
  get_repository_info: '仓库信息',
  // search_repository_code 是混合 RAG 检索（dense embedding + BM25 sparse + 符号精确匹配
  // + L4 图谱扩展），标签点明 RAG 让用户看清「这是语义检索仓库」而非普通文本搜索。
  search_repository_code: 'RAG 代码检索',
  search_code: 'RAG 代码检索',
  list_project_structure: '空间结构',
  get_project_overview: '空间概览',
  list_project_repositories: '仓库列表',
  // 相关性 / 代码关系 / 接口
  analyze_repository_relevance: '仓库分级路由',
  // find_related_code 走 chunk 级代码图谱（CALL/IMPORT/TEST_OF…）沿关系召回关联代码，
  // 区别于 RAG 模糊召回，标签点明用了图谱能力。
  find_related_code: '关联代码查找召回',
  list_endpoints: '接口列表',
  find_api_handler: '查找接口实现',
  find_api_callers: '查找接口调用方',
  // 深度分析 / 编码方案
  deep_analysis: '深度分析',
  create_coding_plan: '编码方案',
  update_coding_plan: '更新方案',
  send_plan_card: '发送方案卡片',
  verify_plan: '校验方案',
  // 编排入口（109-04）：两个工具返回体同形，同判定同卡片
  start_plan_research: '方案编排调研',
  start_feature_solution: '功能方案编排',
  // 交互 / 澄清
  ask_user_question: '询问用户',
  ask_clarification: '澄清提问',
  // 飞书文档 / 消息
  fetch_feishu_document: '读取飞书文档',
  create_feishu_document: '创建飞书文档',
  send_card_message: '发送卡片消息',
  // 需求（work item）
  get_work_item_detail: '需求详情',
  list_related_work_items: '关联需求',
  add_work_item_comment: '添加需求评论',
}

/** 工具名 → 对应的 lucide 图标（process 列表里每行左侧的语义图标）。 */
export const TOOL_ICONS: Record<string, string> = {
  browse_file_content: 'icon-[lucide--file-text]',
  list_space_structure: 'icon-[lucide--folder-tree]',
  get_space_overview: 'icon-[lucide--layout-dashboard]',
  list_space_repositories: 'icon-[lucide--folder-git-2]',
  get_repository_info: 'icon-[lucide--info]',
  search_repository_code: 'icon-[lucide--search]',
  search_code: 'icon-[lucide--search]',
  analyze_repository_relevance: 'icon-[lucide--git-compare]',
  find_related_code: 'icon-[lucide--network]',
  list_endpoints: 'icon-[lucide--list]',
  find_api_handler: 'icon-[lucide--plug]',
  find_api_callers: 'icon-[lucide--plug-zap]',
  fetch_feishu_document: 'icon-[lucide--file-down]',
  create_feishu_document: 'icon-[lucide--file-plus]',
  get_work_item_detail: 'icon-[lucide--clipboard-list]',
  list_related_work_items: 'icon-[lucide--clipboard-list]',
  start_plan_research: 'icon-[lucide--workflow]',
  start_feature_solution: 'icon-[lucide--workflow]',
}

export function bareName(name: string): string {
  return name.replace(/^mcp__[^_]+__/, '')
}

export function toolLabel(name: string): string {
  return TOOL_LABELS[bareName(name)] || bareName(name)
}

export function toolIcon(name: string): string {
  return TOOL_ICONS[bareName(name)] || 'icon-[lucide--wrench]'
}

/** 把 tool result（JSON string / dict / undefined）安全解析成对象。 */
function parseResult(result: unknown): Record<string, unknown> | null {
  if (!result)
    return null
  if (typeof result === 'object')
    return result as Record<string, unknown>
  if (typeof result === 'string') {
    const t = result.trim()
    if (!t)
      return null
    try {
      const parsed = JSON.parse(t)
      return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : null
    }
    catch {
      return null
    }
  }
  return null
}

/**
 * 工具出参的 data 节：兼容 `{output:{data}}`（chat_runner 包一层 ToolResult）、
 * `{data}` 与历史的扁平顶层三种形态。
 *
 * `output.data` 这一层与 `stores/chat.ts` 的 `maybeParseRoutingTraceFromToolResult`
 * 同口径 —— 两处对同一份 result 解出不同形状会让「store 里有 trace、过程面板里
 * 没有候选」这种半截状态成为可能。
 */
function relevanceDataNode(result: unknown): Record<string, unknown> | null {
  const parsed = parseResult(result)
  if (!parsed)
    return null
  const output = parsed.output as Record<string, unknown> | undefined
  const nested = output?.data as Record<string, unknown> | undefined
  const flat = parsed.data as Record<string, unknown> | undefined
  // 优先取**真的带 candidates 的**那一层：`{data:{}}` 这类空壳存在时，原实现会
  // 回退到顶层去找 candidates，这条兜底必须保留。
  for (const node of [nested, flat, parsed]) {
    if (node && Array.isArray(node.candidates))
      return node
  }
  return nested ?? flat ?? parsed
}

/** 归属组兜底：缺失**或空串**都回到 global（后端默认值就是空串）。 */
function groupOf(raw: unknown): RoutingGroup {
  return raw === 'in_project' ? 'in_project' : 'global'
}

/** 分数分解兜底：只收数值项，非法值整项丢弃（不进渲染面）。 */
function breakdownOf(raw: unknown): Record<string, number> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw))
    return {}
  const out: Record<string, number> = {}
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof value === 'number' && Number.isFinite(value))
      out[key] = value
  }
  return out
}

/**
 * 解析 analyze_repository_relevance 结果里的候选仓库（含名称 / 分数 / 等级 /
 * 归属组 / 分数分解）。兼容 `{output:{data:{candidates}}}` / `{data:{candidates}}`
 * 与历史的扁平 `{candidates}` 三种形态。
 */
export function relevanceCandidates(result: unknown): RelevanceCandidate[] {
  const data = relevanceDataNode(result)
  if (!data)
    return []
  const raw = data.candidates as unknown
  if (!Array.isArray(raw))
    return []
  return raw.flatMap((c): RelevanceCandidate[] => {
    if (!c || typeof c !== 'object')
      return []
    const obj = c as Record<string, unknown>
    const id = String(obj.repository_id ?? obj.id ?? '')
    const name = String(obj.repository_name ?? obj.name ?? '')
    if (!name && !id)
      return []
    const level = (obj.level === 'high' || obj.level === 'medium' || obj.level === 'low')
      ? obj.level
      : 'low'
    return [{
      id,
      name: name || id,
      score: typeof obj.score === 'number' ? obj.score : 0,
      level,
      evidence: typeof obj.evidence === 'string' ? obj.evidence : undefined,
      group: groupOf(obj.group),
      breakdown: breakdownOf(obj.breakdown),
      scoreRanked: typeof obj.score_ranked === 'number' ? obj.score_ranked : undefined,
    }]
  })
}

/** 一个分区：组标识 + 该组候选（区内已按 rank 降序）。 */
export interface RoutingBlock {
  group: RoutingGroup
  candidates: RelevanceCandidate[]
}

/**
 * 路由决策视图（ROUTE-01 / ROUTE-02 / ROUTE-07 / RELY-03 的单一数据层）。
 *
 * 承载「分组呈现 / 跨组标注 / 分数分解 / 降级事实」四件事所需的全部派生结论，
 * 组件只负责把它画出来，不再各自解析一遍 tool result。
 */
export interface RoutingDecisionView {
  /** 是否启用分组呈现。为 false 时 `blocks` 恒为单块平铺。 */
  grouped: boolean
  /** 分区（顺序即 `block_order`，空组不产出）。 */
  blocks: RoutingBlock[]
  /** 候选总数（含被分进各区的全部候选）。 */
  total: number
  /** 全局组被置顶（后端迟滞比较的结果）。 */
  promoted: boolean
  /** 置顶时本项目组一条候选都没有 —— 措辞要从「更匹配」换成陈述句。 */
  inProjectEmpty: boolean
  /** 降级事实，由后端派生；前端**绝不**按 router_version 或候选内容自行推断。 */
  degraded: boolean
  /** 降级原因（受控闭集的键；缺失为空串）。 */
  degradeReason: string
}

/** 排序键：`score_ranked` 是后端凸组合排序分，缺失时回退 `score`。 */
function rankKey(c: RelevanceCandidate): number {
  return c.scoreRanked ?? c.score
}

function byRankDesc(a: RelevanceCandidate, b: RelevanceCandidate): number {
  const delta = rankKey(b) - rankKey(a)
  if (delta !== 0)
    return delta
  // 同分 tie-break 与后端同口径（repository_id 升序），保证渲染顺序稳定
  return a.id.localeCompare(b.id)
}

/**
 * 把一次 analyze_repository_relevance 出参解析成路由决策视图。
 *
 * 分组启用的**唯一依据是后端 `block_order`**——长度 2 即启用（后端契约：有项目
 * 上下文时恒为长度 2，即使某组为空）。长度 1 = 无项目上下文 ⇒ 平铺，此时标「跨组」
 * 反而误导；缺失（历史结果 / legacy 路径）同样平铺，保持今日渲染。
 *
 * 刻意**不**按候选内容兜底：用 `some(c => c.group === 'in_project')` 判定会恰在最
 * 需要分组的场景失效——正确仓在跨组、本项目组为空时没有任何候选是 in_project，
 * 分组被判为关闭，「更匹配的仓不在本项目关联范围内」这句最有信息量的提示反而不出现。
 *
 * 区内按 rank 降序，**不做全局重排**：按 score 把全部候选重排一次会覆盖后端的分区
 * 顺序与置顶决策（107-RESEARCH Pitfall 4）。
 */
export function routingDecisionView(result: unknown): RoutingDecisionView {
  const data = relevanceDataNode(result)
  const candidates = relevanceCandidates(result)
  const sorted = [...candidates].sort(byRankDesc)

  const rawOrder = data?.block_order
  const order: RoutingGroup[] = Array.isArray(rawOrder) && rawOrder.length === 2
    ? (rawOrder.map(groupOf) as RoutingGroup[])
    : []
  const grouped = order.length === 2

  const blocks: RoutingBlock[] = grouped
    ? order
        .map(group => ({ group, candidates: sorted.filter(c => c.group === group) }))
        .filter(block => block.candidates.length > 0)
    : (sorted.length > 0 ? [{ group: 'global' as const, candidates: sorted }] : [])

  return {
    grouped,
    blocks,
    total: sorted.length,
    promoted: grouped && order[0] === 'global',
    inProjectEmpty: !sorted.some(c => c.group === 'in_project'),
    degraded: data?.degraded === true,
    degradeReason: typeof data?.degrade_reason === 'string' ? data.degrade_reason : '',
  }
}

/**
 * 从一次工具调用里抽取 repository_id → name 的贡献，供上层聚合成
 * 会话级映射（relevance 候选 / coding plan 推荐仓库）。
 */
export function collectRepoNames(name: string, _input: Record<string, unknown> | undefined, result: unknown): Record<string, string> {
  const bare = bareName(name)
  const out: Record<string, string> = {}
  if (bare === 'analyze_repository_relevance') {
    for (const c of relevanceCandidates(result)) {
      if (c.id && c.name)
        out[c.id] = c.name
    }
    return out
  }
  if (bare === 'create_coding_plan' || bare === 'update_coding_plan') {
    const parsed = parseResult(result)
    if (parsed) {
      const recs = parsed.recommended_repositories
      if (Array.isArray(recs)) {
        for (const r of recs) {
          if (r && typeof r === 'object') {
            const obj = r as Record<string, unknown>
            const id = String(obj.id ?? '')
            const nm = String(obj.name ?? '')
            if (id && nm)
              out[id] = nm
          }
        }
      }
      const rid = String(parsed.repository_id ?? '')
      const rname = String(parsed.repository_name ?? '')
      if (rid && rname)
        out[rid] = rname
    }
    return out
  }
  return out
}

export interface RerankInfo {
  mode: string
  model?: string
  candidates?: number
  returned?: number
  fallbackFrom?: string
}

/**
 * 从 search_repository_code 结果里解析精排信息（search_rag 写入 metadata.rerank）。
 * mode 缺失或为 'off' 时返回 null（不展示）。
 */
export function rerankInfo(result: unknown): RerankInfo | null {
  const parsed = parseResult(result)
  if (!parsed)
    return null
  const meta = (parsed.metadata as Record<string, unknown> | undefined) ?? parsed
  const r = meta?.rerank as Record<string, unknown> | undefined
  if (!r || typeof r !== 'object')
    return null
  const mode = String(r.mode ?? '')
  if (!mode || mode === 'off')
    return null
  return {
    mode,
    model: typeof r.model === 'string' ? r.model : undefined,
    candidates: typeof r.candidates === 'number' ? r.candidates : undefined,
    returned: typeof r.returned === 'number' ? r.returned : undefined,
    fallbackFrom: typeof r.fallback_from === 'string' ? r.fallback_from : undefined,
  }
}

/** 把精排信息渲染成附加在检索摘要后的一段，例如「· 精排 50→10（qwen3-rerank）」。 */
function rerankSuffix(result?: string): string {
  const info = rerankInfo(result)
  if (!info)
    return ''
  const who = info.mode === 'model' ? (info.model || '模型精排') : '启发式精排'
  const count = (info.candidates != null && info.returned != null)
    ? ` ${info.candidates}→${info.returned}`
    : ''
  return ` · 精排${count}（${who}）`
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n)}…` : s
}

/**
 * 把秒数渲染成中文人性化时长（借鉴 open-webui「Thought for {{DURATION}}」）。
 * `< 1s` → 「不到 1 秒」；`< 60s` → 「N 秒」；否则「N 分 N 秒」。
 */
export function humanizeDuration(seconds: number): string {
  if (seconds <= 0)
    return ''
  if (seconds < 1)
    return '不到 1 秒'
  if (seconds < 60)
    return `${Math.round(seconds)} 秒`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return s ? `${m} 分 ${s} 秒` : `${m} 分`
}

/** 仓库名称首字符（用于堆叠头像式预览的色块）。 */
export function repoInitial(name: string): string {
  const trimmed = (name || '').trim()
  return trimmed ? trimmed[0].toUpperCase() : '?'
}

function repoNameOf(id: string, repoNames?: Record<string, string>): string {
  if (!id)
    return ''
  const nm = repoNames?.[id]
  if (nm)
    return nm
  // 拿不到名称时退化为短 id（前 8 位），避免整段 UUID 占满。
  return id.length > 8 ? `${id.slice(0, 8)}…` : id
}

/**
 * 搜索代码调用命中的仓库展示名。
 * - 指定 repository_id → 单个仓库名。
 * - 仅 space_id（全空间检索）→ 返回 ['全部仓库']。
 */
export function searchedRepoLabel(input: Record<string, unknown> | undefined, repoNames?: Record<string, string>): string {
  const repoId = (input?.repository_id as string) || ''
  if (repoId)
    return repoNameOf(repoId, repoNames)
  // repository_ids 复数（新契约）
  const ids = input?.repository_ids
  if (Array.isArray(ids) && ids.length > 0) {
    const names = ids.map(id => repoNameOf(String(id), repoNames)).filter(Boolean)
    if (names.length > 0)
      return names.length > 2 ? `${names.slice(0, 2).join('、')} 等 ${names.length} 个仓库` : names.join('、')
  }
  return '全部仓库'
}

/**
 * 工具调用 → 一行人类可读摘要。`repoNames` 可选，用于把仓库 UUID 渲染成名称。
 */
export function toolAction(
  name: string,
  input: Record<string, unknown>,
  result?: string,
  repoNames?: Record<string, string>,
): string {
  const bare = bareName(name)
  switch (bare) {
    case 'search_repository_code':
    case 'search_code': {
      const q = (input?.query as string) || ''
      const repo = searchedRepoLabel(input, repoNames)
      const qPart = q ? `「${truncate(q, 32)}」` : ''
      let base: string
      if (qPart && repo)
        base = `在 ${repo} RAG 检索 ${qPart}`
      else if (qPart)
        base = `RAG 检索 ${qPart}`
      else
        base = repo ? `在 ${repo} RAG 检索代码` : 'RAG 代码检索'
      return base + rerankSuffix(result)
    }
    case 'analyze_repository_relevance': {
      const cands = relevanceCandidates(result)
      if (cands.length > 0) {
        const names = cands.map(c => c.name).filter(Boolean)
        const head = names.slice(0, 3).join('、')
        const more = names.length > 3 ? ` 等 ${names.length} 个仓库` : ''
        return `关联到 ${head}${more}`
      }
      const q = (input?.query as string) || ''
      return q ? `分析「${truncate(q, 32)}」相关仓库` : '仓库分级路由'
    }
    case 'find_related_code': {
      const sym = (input?.symbol_name as string) || (input?.symbol as string) || ''
      const file = (input?.file_path as string) || ''
      const anchor = sym || (file ? truncate(file, 32) : '')
      return anchor ? `关联代码查找召回：${anchor}` : '关联代码查找召回'
    }
    case 'find_api_handler':
    case 'find_api_callers': {
      const path = (input?.api_path as string) || (input?.path as string) || ''
      return path ? `接口 ${path}` : (bare === 'find_api_handler' ? '查找接口实现' : '查找接口调用方')
    }
    case 'fetch_feishu_document': {
      const url = (input?.document_url as string) || (input?.url as string) || ''
      return url ? `读取 ${truncate(url, 40)}` : '读取飞书文档'
    }
    case 'browse_file_content': {
      const p = (input?.file_path as string) || (input?.path as string) || ''
      if (!p)
        return '浏览文件内容'
      const repoId = (input?.repository_id as string) || ''
      const repo = repoId ? repoNameOf(repoId, repoNames) : ''
      return repo ? `${repo} · ${p}` : `查看 ${p}`
    }
    case 'get_space_overview':
    case 'get_project_overview':
      return '获取空间概览'
    case 'list_space_repositories':
    case 'list_project_repositories':
      return '列出所有仓库'
    case 'list_space_structure':
    case 'list_project_structure':
      return '浏览文件结构'
    case 'get_repository_info': {
      const repoId = (input?.repository_id as string) || ''
      const repo = repoId ? repoNameOf(repoId, repoNames) : ''
      return repo ? `获取 ${repo} 详情` : '获取仓库详情'
    }
    case 'deep_analysis': {
      const desc = (input?.task_description as string) || ''
      let label = desc ? `分析「${truncate(desc, 30)}」` : '深度代码分析'
      if (result) {
        const resultStr = typeof result === 'string' ? result : JSON.stringify(result)
        try {
          const parsed = JSON.parse(resultStr)
          const sid = parsed?.data?.session_id
          if (sid)
            label += ` · ${sid}`
        }
        catch {
          const m = resultStr.match(/session: ([\w-]+)/)
          if (m)
            label += ` · ${m[1]}`
        }
      }
      return label
    }
    // 编排入口（109-04）：两个工具返回体同形，共用同一段摘要逻辑。
    // 🔴 三分支文案全取本文件常量，不回显后端 placeholder / message 原文 ——
    // 后端自由文本只用于留痕与排障，让它上屏成为惯例，下一个产出路径就会带着
    // LLM 原文上屏。
    case 'start_plan_research':
    case 'start_feature_solution': {
      const parsed = parseResult(result)
      if (parsed) {
        if (parsed.status === 'done')
          return '跨仓方案编排已完成'
        if (parsed.__blocking_task__)
          return '方案编排调研进行中'
      }
      const requirement = (input?.requirement as string) || ''
      return requirement
        ? `编排「${truncate(requirement, 32)}」`
        : TOOL_LABELS[bare]
    }
    default: {
      const entries = Object.entries(input || {}).slice(0, 2)
      const desc = entries.map(([k, v]) => `${k}: ${typeof v === 'string' ? truncate(v, 30) : JSON.stringify(v)}`).join(', ')
      return desc || '执行操作'
    }
  }
}
