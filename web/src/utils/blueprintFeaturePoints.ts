/**
 * 功能点展示口径（quick-260806-fpx）。
 *
 * `intent` 三档的徽标 variant、i18n 键与标题记号剥离原本内联在 `RequirementSpecSection`
 * 里；本次新增的功能点 chip 有四处消费（现状分析 / 模块卡 / 实现项卡 / 澄清向导），
 * 再抄一份就是第二套口径 ⇒ 收敛到此。
 *
 * ⛔ **不发明第四档**：未知 `intent` 退 `outline` + 渲染 schema 原样 token，
 * 让"上游给了个新枚举值"这件事在界面上可见，而不是被悄悄归进某一档。
 */

export type IntentVariant = 'success' | 'info' | 'warning' | 'outline'

const INTENT_VARIANT: Record<string, Exclude<IntentVariant, 'outline'>> = {
  greenfield: 'success',
  brownfield: 'info',
  fix: 'warning',
}

const INTENT_LABEL_KEY: Record<string, string> = {
  greenfield: 'intentGreenfield',
  brownfield: 'intentBrownfield',
  fix: 'intentFix',
}

export function intentVariantOf(intent: string | undefined): IntentVariant {
  return INTENT_VARIANT[intent ?? ''] ?? 'outline'
}

/** `knowledge.blueprints.spec.*` 下的键后缀；无匹配返回 `null`（调用方回落原样 token）。 */
export function intentLabelKeyOf(intent: string | undefined): string | null {
  return INTENT_LABEL_KEY[intent ?? ''] ?? null
}

/**
 * 剥掉标题行首的 markdown 记号（`#### 功能点 B：…`）—— 旧版机械拆解器没剥干净时的兜底。
 * ⛔ 只剥行首，不动标题内部的 `#`。
 */
export function cleanFeaturePointTitle(title: string | undefined): string {
  return String(title ?? '').replace(/^#{1,6}\s+/, '').trim()
}

// ── 功能点 → 正文行 内联标签匹配（quick-260806：功能点分散进目标正文）─────────────

export interface FeaturePointLineTag {
  pointId: string
  intent: string
  title: string
}

/**
 * 匹配用归一化：剥加粗记号（渲染文本理应已删，双保险）+ 折叠空白。
 * ⛔ 不剥行首列表/标题记号 —— 入参是 `buildMarkdownRender` 的**渲染文本**行，记号已删除。
 */
function normalizeForMatch(value: string): string {
  return value.replace(/\*\*/g, '').replace(/\s+/g, ' ').trim()
}

/**
 * 功能点 → 渲染行的**顺序贪婪**匹配（两指针）。
 *
 * 机械拆解器按文档顺序产出功能点，标题原文即目标正文里的对应行 ⇒ 顺序对齐天然解决
 * **同名标题**的归属（fp_7/fp_9「掌握程度浮层」各归属自己模块下的那一行）。
 * 未匹配的点不推进游标（后续点仍从原位置起扫），由调用方兜底展示。
 *
 * Args:
 *   rendered: `buildMarkdownRender` 的渲染文本（记号已删除）。
 *   lines: 渲染坐标的行表（同一模型的 `lines`）。
 *   points: 功能点（按文档顺序）。
 *
 * Returns:
 *   Map<行起点渲染 offset, tag>。一行至多一个标签。
 */
export function matchFeaturePointsToRenderedLines(
  rendered: string,
  lines: readonly { start: number, end: number }[],
  points: readonly { id: string, title?: string, intent?: string }[],
): Map<number, FeaturePointLineTag> {
  const result = new Map<number, FeaturePointLineTag>()
  if (!rendered || !lines.length || !points.length)
    return result
  const lineTexts = lines.map(line =>
    normalizeForMatch(rendered.slice(line.start, line.end).replace(/\n$/, '')),
  )
  let cursor = 0
  for (const point of points) {
    const title = normalizeForMatch(cleanFeaturePointTitle(point.title))
    if (!title)
      continue
    for (let i = cursor; i < lineTexts.length; i++) {
      if (lineTexts[i] !== title)
        continue
      result.set(lines[i].start, {
        pointId: String(point.id ?? ''),
        intent: String(point.intent ?? ''),
        title,
      })
      cursor = i + 1
      break
    }
  }
  return result
}
