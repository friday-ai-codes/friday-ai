/**
 * 蓝图澄清题结构化检测与归一（quick-260806-fy2）。
 *
 * 规格门把 questions 原样存进 `BlueprintThread.options`：
 * `{ text, options: string[], citations?, related_feature_points?, recommended? }`。
 * 旧路径 / 人工评论仍可能是扁平 `{ label, value, note }`。
 *
 * 本模块是前端唯一分流判据，供 ThreadCard 在向导 vs 旧 composer 之间选择。
 */

export interface ClarificationQuestion {
  text: string
  options: string[]
  recommended: string
  related_feature_points: string[]
  citations: string[]
}

const FP_ID_RE = /\bfp_[A-Za-z0-9_]+\b/g

/** 至少一项带非空 `text` / `question` ⇒ 视为规格门结构化澄清题。 */
export function isStructuredClarificationQuestions(raw: unknown): boolean {
  if (!Array.isArray(raw) || raw.length === 0)
    return false
  return raw.some((item) => {
    if (!item || typeof item !== 'object')
      return false
    const row = item as Record<string, unknown>
    const text = String(row.text ?? row.question ?? '').trim()
    return text.length > 0
  })
}

export function normalizeClarificationQuestions(raw: unknown): ClarificationQuestion[] {
  if (!Array.isArray(raw))
    return []
  const out: ClarificationQuestion[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object')
      continue
    const row = item as Record<string, unknown>
    const text = String(row.text ?? row.question ?? '').trim()
    if (!text)
      continue
    const options = Array.isArray(row.options)
      ? row.options.map(opt => String(opt ?? '').trim()).filter(Boolean)
      : []
    const related = Array.isArray(row.related_feature_points)
      ? row.related_feature_points.map(fp => String(fp ?? '').trim()).filter(Boolean)
      : []
    const citations = Array.isArray(row.citations)
      ? row.citations.map(c => String(c ?? '').trim()).filter(Boolean)
      : []
    let recommended = String(row.recommended ?? '').trim()
    if (recommended && !options.includes(recommended))
      recommended = ''
    out.push({
      text,
      options,
      recommended,
      related_feature_points: related,
      citations,
    })
  }
  return out
}

/** 合并显式 related + 题面里出现的 `fp_*` id（去重保序）。 */
export function extractFeaturePointIds(
  text: string,
  related: readonly string[] = [],
): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const id of related) {
    const trimmed = String(id ?? '').trim()
    if (!trimmed || seen.has(trimmed))
      continue
    seen.add(trimmed)
    out.push(trimmed)
  }
  for (const match of String(text ?? '').matchAll(FP_ID_RE)) {
    const id = match[0]
    if (seen.has(id))
      continue
    seen.add(id)
    out.push(id)
  }
  return out
}

export function formatClarificationAnswers(
  pairs: Array<{ question: string, answer: string }>,
): string {
  return pairs
    .map((pair, index) => `${index + 1}. ${pair.question.trim()}\n→ ${pair.answer.trim()}`)
    .join('\n\n')
}

/**
 * `formatClarificationAnswers` 的逆向：从作答正文解析 `N. 题面\n→ 答案` 对。
 *
 * 供线程卡把已答/已关闭澄清渲染成问答对视图（quick-260806 视觉整改：整墙 `pre`
 * 不便查阅）。宽容解析：编号支持 `.` / `、`，答案取该编号块内首个 `→` 之后的全部文本
 * （含换行）；解析不出任何对时返回空 Map，调用方回退原始消息渲染。
 */
export function parseClarificationAnswers(body: string): Map<number, string> {
  const answers = new Map<number, string>()
  const chunks = String(body ?? '').split(/(?=(?:^|\n)\s*\d+[.、]\s)/)
  for (const chunk of chunks) {
    const head = chunk.match(/^\s*(\d+)[.、]\s/)
    if (!head)
      continue
    const arrow = chunk.indexOf('→')
    if (arrow === -1)
      continue
    const answer = chunk.slice(arrow + 1).trim()
    if (answer)
      answers.set(Number(head[1]), answer)
  }
  return answers
}
