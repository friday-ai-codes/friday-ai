/**
 * 蓝图正文 markdown-lite 解析（quick-260806-gfk）。
 *
 * 机械 intake 会把整段 feature-list markdown 原文塞进一个 paragraph 块
 * （`requirement_spec.goal`），裸渲染是一面带 `##`/`- [ ]`/`**` 记号的文字墙。
 *
 * ⭐ **硬约束（P-13 同源）**：块正文是批注锚点的坐标系 —— `rangeOffsets` 按块内
 * 全部文本节点扁平拼接计算选区 offset ⇒ 渲染层**不得增删任何字符**（含记号、
 * 缩进空格与 `\n`）。本模块因此只产出「行分级 + 行内样式区间」的**绝对 offset
 * 元数据**，由 `BlueprintBlock` 在渲染时包元素与着色：记号字符淡化、加粗内容
 * 真加粗（Typora 源码高亮式，⛔ 不是渲染式 markdown）。
 *
 * 不变式：`lines` 首尾相接覆盖 `[0, text.length)` 无缝隙；`styles` 每段落在
 * 单行内且互不重叠。
 */

export type MarkdownLineKind
  = | 'h1'
    | 'h2'
    | 'h3'
    | 'h4'
    | 'task'
    | 'bullet'
    | 'ordered'
    | 'blank'
    | 'plain'

export interface MarkdownLineMeta {
  /** 行起点（绝对 offset，含行首缩进）。 */
  start: number
  /** 行终点（绝对 offset，**含**行尾 `\n`；末行无 `\n` 则到文本末尾）。 */
  end: number
  kind: MarkdownLineKind
  /** 缩进层级（每 2 个前导空格算一级，tab 算一级）。 */
  depth: number
}

/**
 * - `marker`：结构记号（`##` / `**` / 反引号 / `- ` 列表前缀）——渲染层**零宽隐藏**
 *   （字符仍在文本节点里，坐标系不动），视觉替代物由行样式/伪元素承担。
 * - `taskbox`：任务框 `- [ ]`——零宽隐藏 + 伪元素画勾选框。
 * - `dim`：淡化但可见（有序编号这类携带信息的前缀）。
 * - `bold` / `code`：内容样式。
 */
export type InlineStyleKind = 'marker' | 'taskbox' | 'dim' | 'bold' | 'code'

export interface InlineStyleRange {
  start: number
  end: number
  style: InlineStyleKind
}

export interface MarkdownLiteModel {
  lines: MarkdownLineMeta[]
  styles: InlineStyleRange[]
}

const HEADING_RE = /^(#{1,6})\s+/
const TASK_RE = /^(\s*)- \[[ x]\]\s*/i
const BULLET_RE = /^(\s*)[-*]\s+/
/**
 * 有序编号的四种形态。中文 AI 产出里 `（1）` / `1)` / `①` 比标准 `1. ` 常见得多，
 * 只认标准形态会让整段退回 `plain`，读者看到的就是一面没有层级的文字墙。
 *
 * ⚠️ `\d{1,3}[.、]` 分支**必须**跟 `\s+`：否则 `1.5 倍` 的 `1.` 会被当成编号，
 * 把行首数字吞掉（症状是正文少了个「1」，比不识别更糟）。带括号与带圈的形态自身
 * 就是闭合记号，跟空白可有可无。
 */
const ORDERED_RE = /^(\s*)(?:\d{1,3}[.、]\s+|\d{1,3}[)）]\s*|[(（]\s*\d{1,3}\s*[)）]\s*|[\u2460-\u2473]\s*)/
const BOLD_RE = /\*\*([^*\n]+)\*\*/g
const CODE_RE = /`([^`\n]+)`/g
/** 行中任意位置的任务框记号（`验收：- [ ] …` 这类嵌在句中的形态）。 */
const INLINE_TASKBOX_RE = /- \[[ x]\]/gi

/**
 * `/g` 正则的**一次性**命中判定。
 *
 * ⚠️ 带 `g` 标志的正则，`test()` 会把 `lastIndex` 推进到本次匹配之后，下次对**另一个**
 * 字符串判定时从那个陈旧下标起找 ⇒ 开头处的命中会被跳过而假阴性，且判定结果随调用顺序
 * 变化（隔一个错一个）。本函数前后各归零一次，让判定成为纯函数。
 * ⛔ 不要图省事直接写 `RE.test(x)`。
 */
function hasInlineMarker(re: RegExp, source: string): boolean {
  re.lastIndex = 0
  const hit = re.test(source)
  re.lastIndex = 0
  return hit
}

/**
 * 是否值得走富渲染。
 *
 * 两类判据：
 *
 * - **行内记号**（`` `code` `` / `**bold**`）：与行数无关。后端 prompt 的正文约定要求
 *   「凡代码标识符、文件路径、函数名一律用反引号包裹」，而 `impl_items[].how`、
 *   `findings[].detail` 这类字段常常就一行 —— 单行退回裸 `<p>` 的话，反引号会原样显示
 *   在页面上（记号本该被删掉并着色）。
 * - **块级结构**（标题 / ≥2 行列表）：需要多行才成立。
 *
 * 无记号的纯文本（单行或多行）保持原 `<p>` 路径。
 */
export function isMarkdownishText(text: string): boolean {
  const source = typeof text === 'string' ? text : ''
  if (!source)
    return false

  if (hasInlineMarker(CODE_RE, source) || hasInlineMarker(BOLD_RE, source))
    return true

  if (!source.includes('\n'))
    return false
  const lines = source.split('\n')
  let listLike = 0
  for (const line of lines) {
    if (HEADING_RE.test(line))
      return true
    if (TASK_RE.test(line) || BULLET_RE.test(line) || ORDERED_RE.test(line))
      listLike += 1
  }
  return listLike >= 2
}

function indentDepth(indent: string): number {
  let depth = 0
  let spaces = 0
  for (const ch of indent) {
    if (ch === '\t') {
      depth += 1
      spaces = 0
      continue
    }
    spaces += 1
    if (spaces === 2) {
      depth += 1
      spaces = 0
    }
  }
  return depth
}

interface LineClass {
  kind: MarkdownLineKind
  depth: number
  markerEnd: number
  /** 行首记号的渲染档：隐藏（marker/taskbox）或淡化可见（dim，编号携带信息）。 */
  markerStyle: InlineStyleKind
}

/** 单行分类 + 行首记号区间（相对行内 offset）。 */
function classifyLine(line: string): LineClass {
  if (line.trim().length === 0)
    return { kind: 'blank', depth: 0, markerEnd: 0, markerStyle: 'marker' }

  const heading = HEADING_RE.exec(line)
  if (heading) {
    const level = Math.min(heading[1].length, 4)
    return {
      kind: (`h${level}`) as MarkdownLineKind,
      depth: 0,
      markerEnd: heading[0].length,
      markerStyle: 'marker',
    }
  }

  const task = TASK_RE.exec(line)
  if (task)
    return { kind: 'task', depth: indentDepth(task[1]), markerEnd: task[0].length, markerStyle: 'taskbox' }

  const bullet = BULLET_RE.exec(line)
  if (bullet) {
    // 「列表里嵌标题」（`- #### 功能点 A: …`）按标题渲染：`- ####` 整段记号隐藏，
    // 层级沿用列表缩进（feature-list 原文的常见形态，裸露 #### 是最扎眼的噪声）。
    const nested = HEADING_RE.exec(line.slice(bullet[0].length))
    if (nested) {
      const level = Math.min(nested[1].length, 4)
      return {
        kind: (`h${level}`) as MarkdownLineKind,
        depth: indentDepth(bullet[1]),
        markerEnd: bullet[0].length + nested[0].length,
        markerStyle: 'marker',
      }
    }
    return { kind: 'bullet', depth: indentDepth(bullet[1]), markerEnd: bullet[0].length, markerStyle: 'marker' }
  }

  const ordered = ORDERED_RE.exec(line)
  if (ordered) {
    // 有序编号携带信息 ⇒ 淡化可见，⛔ 不隐藏。
    return { kind: 'ordered', depth: indentDepth(ordered[1]), markerEnd: ordered[0].length, markerStyle: 'dim' }
  }

  return { kind: 'plain', depth: 0, markerEnd: 0, markerStyle: 'marker' }
}

/**
 * 行内 `**bold**` / `` `code` `` / 句中任务框 `- [ ]` 区间
 * （相对行内 offset；重叠先到先得；`[0, markerEnd)` 已被行首记号占用）。
 */
function inlineStyles(line: string, markerEnd = 0): InlineStyleRange[] {
  const claimed: Array<[number, number]> = markerEnd > 0 ? [[0, markerEnd]] : []
  const out: InlineStyleRange[] = []

  const overlaps = (start: number, end: number): boolean =>
    claimed.some(([s, e]) => start < e && end > s)

  BOLD_RE.lastIndex = 0
  for (const match of line.matchAll(BOLD_RE)) {
    const start = match.index
    const end = start + match[0].length
    if (overlaps(start, end))
      continue
    claimed.push([start, end])
    out.push({ start, end: start + 2, style: 'marker' })
    out.push({ start: start + 2, end: end - 2, style: 'bold' })
    out.push({ start: end - 2, end, style: 'marker' })
  }

  CODE_RE.lastIndex = 0
  for (const match of line.matchAll(CODE_RE)) {
    const start = match.index
    const end = start + match[0].length
    if (overlaps(start, end))
      continue
    claimed.push([start, end])
    out.push({ start, end: start + 1, style: 'marker' })
    out.push({ start: start + 1, end: end - 1, style: 'code' })
    out.push({ start: end - 1, end, style: 'marker' })
  }

  INLINE_TASKBOX_RE.lastIndex = 0
  for (const match of line.matchAll(INLINE_TASKBOX_RE)) {
    const start = match.index
    const end = start + match[0].length
    if (overlaps(start, end))
      continue
    claimed.push([start, end])
    out.push({ start, end, style: 'taskbox' })
  }

  return out.sort((a, b) => a.start - b.start)
}

// ── 渲染映射（真·markdown 预览，quick-260806-gfk v3）────────────────────────────
//
// 记号字符（`##` / `**` / 反引号 / `- ` / `- [ ]`）从渲染文本里**真正删除**，
// 同时维护「源文本 ↔ 渲染文本」的单调保留区间表：
// - 批注锚点（源坐标）→ `toRendered` 后切 <mark>；
// - 选区（DOM 即渲染坐标）→ `toSource` 后上报，`quoted_text` 从源文本切
//   （后端 `blueprint_anchor.reanchor` 的模糊匹配语料是源文本）。
// 有序编号（`1. `）携带信息 ⇒ 保留在渲染文本里（`dim` 淡化）。

export interface MarkdownGlyph {
  /** 渲染坐标（记号删除点）。 */
  rendOffset: number
  glyph: 'taskbox' | 'taskbox-checked'
}

export interface MarkdownRenderModel {
  /** 渲染文本（记号已删除；`\n` 与其余字符逐字保留）。 */
  rendered: string
  /** 行元数据（**渲染坐标**）。 */
  lines: MarkdownLineMeta[]
  /** 可见样式区间（**渲染坐标**，只剩 dim/bold/code）。 */
  styles: InlineStyleRange[]
  /** 任务框等视觉替代物的插入点（渲染坐标）。 */
  glyphs: MarkdownGlyph[]
  /** 渲染偏移 → 源偏移（逐字符精确）。 */
  toSource: (rendOffset: number) => number
  /** 源偏移 → 渲染偏移（落在被删记号里时向后夹到下一个保留字符）。 */
  toRendered: (srcOffset: number) => number
}

interface KeptRange {
  srcStart: number
  srcEnd: number
  rendStart: number
}

const CHECKED_TASKBOX_RE = /\[x\]/i

export function buildMarkdownRender(text: string): MarkdownRenderModel {
  const source = typeof text === 'string' ? text : ''
  const { lines: srcLines, styles: srcStyles } = parseMarkdownLite(source)

  // 1) 删除集：marker / taskbox 区间（其余样式保留可见）。
  const removals = srcStyles
    .filter(style => style.style === 'marker' || style.style === 'taskbox')
    .sort((a, b) => a.start - b.start)

  // 2) 保留区间表 + 渲染文本 + 替代物插入点。
  const kept: KeptRange[] = []
  const glyphs: MarkdownGlyph[] = []
  let renderedParts: string[] = []
  let srcCursor = 0
  let rendCursor = 0
  for (const removal of removals) {
    if (removal.start > srcCursor) {
      kept.push({ srcStart: srcCursor, srcEnd: removal.start, rendStart: rendCursor })
      renderedParts.push(source.slice(srcCursor, removal.start))
      rendCursor += removal.start - srcCursor
    }
    if (removal.style === 'taskbox') {
      glyphs.push({
        rendOffset: rendCursor,
        glyph: CHECKED_TASKBOX_RE.test(source.slice(removal.start, removal.end))
          ? 'taskbox-checked'
          : 'taskbox',
      })
    }
    srcCursor = Math.max(srcCursor, removal.end)
  }
  if (srcCursor < source.length) {
    kept.push({ srcStart: srcCursor, srcEnd: source.length, rendStart: rendCursor })
    renderedParts.push(source.slice(srcCursor))
  }
  const rendered = renderedParts.join('')
  renderedParts = []

  // 3) 双向映射（保留区间单调 ⇒ 线性扫描即可，块文本量级小）。
  function toSource(rendOffset: number): number {
    if (rendOffset <= 0)
      return kept.length ? kept[0].srcStart : 0
    for (const range of kept) {
      const len = range.srcEnd - range.srcStart
      if (rendOffset < range.rendStart + len)
        return range.srcStart + (rendOffset - range.rendStart)
    }
    return source.length
  }
  function toRendered(srcOffset: number): number {
    for (const range of kept) {
      if (srcOffset < range.srcStart)
        return range.rendStart // 落在被删记号里 ⇒ 夹到下一个保留字符
      if (srcOffset < range.srcEnd)
        return range.rendStart + (srcOffset - range.srcStart)
    }
    return rendered.length
  }

  // 4) 行与可见样式换算到渲染坐标。
  const lines: MarkdownLineMeta[] = srcLines.map(line => ({
    ...line,
    start: toRendered(line.start),
    end: line.end >= source.length ? rendered.length : toRendered(line.end),
  }))
  const styles: InlineStyleRange[] = srcStyles
    .filter(style => style.style !== 'marker' && style.style !== 'taskbox')
    .map(style => ({ ...style, start: toRendered(style.start), end: toRendered(style.end) }))
    .filter(style => style.start < style.end)

  return { rendered, lines, styles, glyphs, toSource, toRendered }
}

export function parseMarkdownLite(text: string): MarkdownLiteModel {
  const source = typeof text === 'string' ? text : ''
  const lines: MarkdownLineMeta[] = []
  const styles: InlineStyleRange[] = []
  if (!source)
    return { lines, styles }

  let cursor = 0
  while (cursor <= source.length - 1 || cursor === 0) {
    const newlineAt = source.indexOf('\n', cursor)
    const contentEnd = newlineAt === -1 ? source.length : newlineAt
    const lineEnd = newlineAt === -1 ? source.length : newlineAt + 1
    const lineText = source.slice(cursor, contentEnd)

    const { kind, depth, markerEnd, markerStyle } = classifyLine(lineText)
    lines.push({ start: cursor, end: lineEnd, kind, depth })

    if (markerEnd > 0)
      styles.push({ start: cursor, end: cursor + markerEnd, style: markerStyle })
    // `[0, markerEnd)` 作为已占用区间传入，行内样式绝不与行首记号重叠。
    for (const range of inlineStyles(lineText, markerEnd))
      styles.push({ start: cursor + range.start, end: cursor + range.end, style: range.style })

    if (newlineAt === -1)
      break
    cursor = lineEnd
    if (cursor === source.length) {
      // 文本以 \n 结尾：不再补一个空行条目（尾 \n 已归入上一行）。
      break
    }
  }

  styles.sort((a, b) => a.start - b.start)
  return { lines, styles }
}
