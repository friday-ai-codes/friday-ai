/**
 * 工具调用展示逻辑的单一权威。
 *
 * 抽自 ChatMessageBubble.vue，供 ChatMessageBubble / ToolProcessGroup 共用：
 *
 * - `toolLabel`：工具名 → 中文标签。
 * - `toolAction`：工具调用 → 一行人类可读摘要；对 search / relevance 等工具
 *   注入「仓库名称」而非裸 UUID（用户诉求 2 / 3）。
 * - `relevanceCandidates`：解析 analyze_repository_relevance 结果里的候选仓库。
 * - `collectRepoNames`：从一次工具调用里抽取 repository_id → name 贡献，
 *   供上层聚合成会话级 id→name 映射。
 */

export interface RelevanceCandidate {
  id: string
  name: string
  score: number
  level: 'high' | 'medium' | 'low'
  evidence?: string
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
 * 解析 analyze_repository_relevance 结果里的候选仓库（含名称 / 分数 / 等级）。
 * 兼容 `{data:{candidates}}` 与历史的扁平 `{candidates}` 两种形态。
 */
export function relevanceCandidates(result: unknown): RelevanceCandidate[] {
  const parsed = parseResult(result)
  if (!parsed)
    return []
  const data = (parsed.data as Record<string, unknown> | undefined) ?? parsed
  const raw = (data.candidates as unknown) ?? (parsed.candidates as unknown)
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
    }]
  })
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
      if (qPart && repo)
        return `在 ${repo} RAG 检索 ${qPart}`
      if (qPart)
        return `RAG 检索 ${qPart}`
      return repo ? `在 ${repo} RAG 检索代码` : 'RAG 代码检索'
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
    default: {
      const entries = Object.entries(input || {}).slice(0, 2)
      const desc = entries.map(([k, v]) => `${k}: ${typeof v === 'string' ? truncate(v, 30) : JSON.stringify(v)}`).join(', ')
      return desc || '执行操作'
    }
  }
}
