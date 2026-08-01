/**
 * 批注层的区间切分、越界判据与侧栏分组（Phase 115-02，UI-SPEC §7.1 / §7.3 / §7.7）。
 *
 * **本模块是批注层唯一的算法落点。** 渲染组件只消费它的结构化产出，⛔ 不自行切区间、
 * 不自行判越界、不自行分组。
 *
 * ⭐ **切分函数返回结构化数组而非 HTML 串**（T-115-13）：渲染层只能 `v-for` + mustache，
 * XSS 面因此恒为 0。蓝图正文 / 线程消息 / citation quote 都是半可信文本，任何「拼 HTML 再
 * `v-html`」的写法都是存储型 XSS。
 *
 * ## 三种状态不得混为一谈（P-7）
 *
 * | 状态 | 判定方 | 正文呈现 | 侧栏归属 |
 * |------|--------|---------|---------|
 * | **前端越界降级** | 前端：offset 非整数 / 越界 / `start >= end` | 整块左侧色条 + 计数角标 | 按 `status` 分组（**不进失锚组**） |
 * | **后端失锚** | 后端：`anchor_status === 'orphaned'` | **完全不渲染**任何标记（原文已不存在） | 失锚组（**不看 `status`**） |
 * | **无 anchor 的系统线程** | `anchor === null` 且 `anchor_status === 'anchored'`（规格门 / 确认门 / 无划线的驳回评论） | 正文无任何标记 | 按 `status` 分组 |
 *
 * 第一种和第二种混了会让越界线程被当成「原文已变更」；第三种漏了会让确认门线程在侧栏
 * 凭空消失（它们本来就没有划线，但仍需回复）。
 */

import type { BlueprintAnchor, BlueprintThreadDetail } from '~/types/blueprint'

/** 一条线程在某 block 上的字符区间（切分函数的输入）。 */
export interface BlockAnchorRange {
  threadId: string
  start: number
  end: number
}

/** 切分产出的一个子段：`threadIds` 为空即纯文本段。 */
export interface TextSegment {
  text: string
  /** 覆盖本子段的全部线程 id（**不合并**重叠，故可能多于一条）。 */
  threadIds: string[]
}

/** 侧栏四组（四组两两互斥，任一线程恰好落入一组）。 */
export interface SidebarGroups {
  open: BlueprintThreadDetail[]
  answered: BlueprintThreadDetail[]
  closed: BlueprintThreadDetail[]
  orphaned: BlueprintThreadDetail[]
}

/**
 * anchor 区间是否可用于字符级切分。
 *
 * 判据：`start` / `end` 都是整数、`0 <= start < end <= textLength`。
 * ⚠️ 这是**前端越界降级**的判据，与后端的 `anchor_status === 'orphaned'` **不是一回事**
 * （见文件头三态表）。
 */
export function isValidAnchor(anchor: { start?: unknown, end?: unknown }, textLength: number): boolean {
  const { start, end } = anchor
  if (!Number.isInteger(start) || !Number.isInteger(end))
    return false
  const s = start as number
  const e = end as number
  return s >= 0 && s < e && e <= textLength
}

/**
 * 把 block 的纯文本按 anchor 区间切成 `[纯文本段 | 标注段]` 序列。
 *
 * 算法（UI-SPEC §7.1 第 2–4 步）：
 * 1. 校验每条 anchor，不合法者**剔除**（由 `degradedThreadIds` 单独报出，走整块降级）；
 * 2. 收集全部切点（0、文本长度、每条区间的 start / end）去重升序；
 * 3. **重叠区间不合并**，改为切成不相交子段，每个子段携带**覆盖它的全部** threadId
 *    （一个字符可同时属于多条线程；视觉取优先级最高的一条着色，`aria-label` 列出全部）。
 *
 * 不变式：`result.map(s => s.text).join('') === text` —— 任何切点算术错误都会破坏它。
 */
export function sliceBlockText(text: string, anchors: readonly BlockAnchorRange[]): TextSegment[] {
  const source = typeof text === 'string' ? text : ''
  const valid = (Array.isArray(anchors) ? anchors : []).filter(a => isValidAnchor(a, source.length))

  if (source.length === 0)
    return []
  if (valid.length === 0)
    return [{ text: source, threadIds: [] }]

  const points = new Set<number>([0, source.length])
  for (const anchor of valid) {
    points.add(anchor.start)
    points.add(anchor.end)
  }
  const cuts = [...points].sort((a, b) => a - b)

  const segments: TextSegment[] = []
  for (let i = 0; i < cuts.length - 1; i++) {
    const from = cuts[i]
    const to = cuts[i + 1]
    if (from >= to)
      continue
    const threadIds = valid
      .filter(anchor => anchor.start <= from && anchor.end >= to)
      .map(anchor => anchor.threadId)
    segments.push({ text: source.slice(from, to), threadIds })
  }
  return segments
}

/**
 * 需要走**整块降级**（整块左色条 + 角标）的线程 id。
 *
 * ⚠️ 这些线程**仍然按 `status` 进侧栏分组**，⛔ 绝不进失锚组（§20 断言 8）。
 */
export function degradedThreadIds(text: string, anchors: readonly BlockAnchorRange[]): string[] {
  const length = typeof text === 'string' ? text.length : 0
  return (Array.isArray(anchors) ? anchors : [])
    .filter(anchor => !isValidAnchor(anchor, length))
    .map(anchor => anchor.threadId)
}

/**
 * 收集 `root` 子树内的全部文本节点（**唯一触 DOM 的函数**）。
 *
 * offset 计算刻意做成两段式：本函数触 DOM、`offsetInFlatText` 纯数据。这样即便测试环境
 * （或某次 happy-dom 升级）丢了 `TreeWalker`，纯数据那半仍恒可单测。
 *
 * 实测结论（`utils/__tests__/domCapabilities.test.ts` 的能力锁）：happy-dom 20.10.2 支持
 * `createTreeWalker` 且遍历顺序正确 ⇒ 本函数可被自动化单测覆盖。
 */
export function collectTextNodes(root: Node | null): Text[] {
  if (!root)
    return []
  const nodes: Text[] = []
  if (typeof document.createTreeWalker === 'function') {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    let node = walker.nextNode()
    while (node) {
      nodes.push(node as Text)
      node = walker.nextNode()
    }
    return nodes
  }
  // 兜底：环境无 TreeWalker 时用递归遍历，**签名与语义不变**。
  const visit = (current: Node): void => {
    if (current.nodeType === 3) {
      nodes.push(current as Text)
      return
    }
    current.childNodes.forEach(visit)
  }
  visit(root)
  return nodes
}

/**
 * 把「某个文本节点内的局部 offset」换算成扁平文本坐标系里的绝对 offset。
 *
 * **纯数据、恒可单测**：只累加前序文本节点的长度，不触 DOM API。
 * `container` 不在 `nodes` 里时返回 `-1`（调用方据此走整块降级）。
 */
export function offsetInFlatText(
  nodes: readonly { length?: number, textContent?: string | null }[],
  container: unknown,
  offset: number,
): number {
  let flat = 0
  for (const node of nodes) {
    const length = node.length ?? node.textContent?.length ?? 0
    if (node === container)
      return flat + Math.max(0, Math.min(offset, length))
    flat += length
  }
  return -1
}

/**
 * 由 `Range` 算出该 block 扁平文本坐标系里的 `[start, end]`。
 *
 * 两端任一算不出（选区跨出了 `root`）时返回 `null` —— 调用方据此**不弹 popover**，改提示
 * 「评论只能针对同一段落内的文字」。
 */
export function rangeOffsets(range: Range | null, root: Node | null): { start: number, end: number } | null {
  if (!range || !root)
    return null
  const nodes = collectTextNodes(root)
  const start = offsetInFlatText(nodes, range.startContainer, range.startOffset)
  const end = offsetInFlatText(nodes, range.endContainer, range.endOffset)
  if (start < 0 || end < 0 || start >= end)
    return null
  return { start, end }
}

/**
 * 按 `anchor.block_id` 把线程分到各 block。
 *
 * ⛔ 只收 `anchor_status === 'anchored'` 且 `anchor.block_id` 非空的线程：失锚线程正文不渲染
 * （原文已不存在），无 anchor 的系统线程也不进任何 block 分组（它们本来就没有划线）。
 */
export function groupThreadsByBlock(
  threads: readonly BlueprintThreadDetail[],
): Record<string, BlueprintThreadDetail[]> {
  const grouped: Record<string, BlueprintThreadDetail[]> = {}
  for (const thread of Array.isArray(threads) ? threads : []) {
    if (thread?.anchor_status === 'orphaned')
      continue
    const blockId = thread?.anchor?.block_id
    if (!blockId)
      continue
    grouped[blockId] ??= []
    grouped[blockId].push(thread)
  }
  return grouped
}

/** 该 block 上可用于切分的区间（已按 `anchor.block_id` 过滤后再取 offset）。 */
export function anchorRangesForBlock(
  threads: readonly BlueprintThreadDetail[],
): BlockAnchorRange[] {
  return (Array.isArray(threads) ? threads : [])
    .map(thread => ({
      threadId: thread.thread_id,
      start: (thread.anchor?.start_offset ?? Number.NaN) as number,
      end: (thread.anchor?.end_offset ?? Number.NaN) as number,
    }))
}

const SEVERITY_ORDER: readonly string[] = ['blocker', 'warning', 'info', '']

function sortInGroup(threads: BlueprintThreadDetail[]): BlueprintThreadDetail[] {
  return [...threads].sort((a, b) => {
    const rank = (s: string) => {
      const index = SEVERITY_ORDER.indexOf(s)
      return index === -1 ? SEVERITY_ORDER.length : index
    }
    const bySeverity = rank(a.severity) - rank(b.severity)
    if (bySeverity !== 0)
      return bySeverity
    return String(a.created_at).localeCompare(String(b.created_at))
  })
}

/**
 * 侧栏四组分组（UI-SPEC §7.7）。
 *
 * ⚠️ **前三组的 `&& anchor_status !== 'orphaned'` 不可省。** 失锚是**锚定维度**、`status` 是
 * **处置维度**，两者正交：一条 `open` 的失锚线程同时满足「未决」与「失锚批注」，漏掉这个
 * 否定项就会让它在侧栏出现两次、计数重复、`activeThreadId` 选中时两处同时高亮（§20 断言 11）。
 *
 * ⭐ 失锚组的数据源是**人审快照的 `orphaned_threads`**，⛔ **前端不再二次过滤** ——
 * 114 MJ-02 已保证里面只有真失锚（无定位的系统线程判 `skipped` 而非 `orphaned`），再加一道
 * `.filter(t => t.anchor?.block_id)` 只会把真失锚也滤掉（§20 断言 5）。
 * 快照尚未就绪（`orphanedThreads` 为 `undefined`）时按 `anchor_status` 从 `threads` 里派生
 * ——那是**锚定维度本身**，不是二次过滤。
 *
 * 组内排序：severity（blocker → warning → info → 无）→ `created_at` 升序。
 */
export function sidebarGroups(
  threads: readonly BlueprintThreadDetail[],
  orphanedThreads?: readonly BlueprintThreadDetail[],
): SidebarGroups {
  const list = Array.isArray(threads) ? threads : []
  const anchored = list.filter(thread => thread?.anchor_status !== 'orphaned')
  const orphaned = orphanedThreads === undefined
    ? list.filter(thread => thread?.anchor_status === 'orphaned')
    : [...orphanedThreads]

  return {
    open: sortInGroup(anchored.filter(thread => thread.status === 'open')),
    answered: sortInGroup(anchored.filter(thread => thread.status === 'answered')),
    closed: sortInGroup(
      anchored.filter(thread => thread.status === 'resolved' || thread.status === 'dismissed'),
    ),
    orphaned: sortInGroup(orphaned),
  }
}

/**
 * ⭐ 「未决 BLOCKER」的**唯一**判据 —— 逐字对齐后端 confirm 闸
 * （`blueprint_lifecycle_service.py:441-446` 的三条 AND）。
 *
 * ```python
 * kind=ThreadKind.AI_REVIEW_FINDING,
 * severity=ThreadSeverity.BLOCKER,
 * status__in=[ThreadStatus.OPEN, ThreadStatus.ANSWERED],
 * ```
 *
 * ⛔ **不看 `blocking`**：后端判据里没有这一项，加上它会漏掉 `blocking=false` 的 BLOCKER。
 * ⛔ **不看 `anchor_status`**：失锚是**锚定维度**，与「挡不挡确认」正交 —— 一条锚在某 block
 * 上的 BLOCKER，只要那个 block 在后续版本里被改到重锚失败就落 `orphaned`，而它的 `status`
 * 仍是 `open`、**仍然挡 confirm**。
 *
 * ⚠️ 因此本判据必须作用在**全量 `threads`** 上，⛔ 不能作用在 `sidebarGroups` 的
 * `open` 组上 —— 那一组已经先做过 `anchor_status !== 'orphaned'` 过滤。
 *
 * 口径漂移的后果不是「数字差一点」：顶栏显示「0 条未决 BLOCKER」，用户去点「确认」必吃 409。
 * 信息面在鼓励用户按一个注定失败的按钮。⭐ 页面顶栏优先读人审快照的权威字段
 * `unresolved_blocker_count`，本函数只是快照未就绪时的占位。
 */
export function isUnresolvedBlocker(thread: BlueprintThreadDetail | null | undefined): boolean {
  return thread?.kind === 'ai_review_finding'
    && thread?.severity === 'blocker'
    && (thread?.status === 'open' || thread?.status === 'answered')
}

/**
 * 侧栏顶部的三个语义计数（未决 BLOCKER / 待澄清 / 失锚）+ 一个批注总数。
 *
 * ⭐ **`total` 与三个语义计数不是同一维度，⛔ 不能拿三者相加冒充它**（UI-REVIEW M-1）。
 * 三者的口径彼此**不正交**：`unresolvedBlocker` 刻意作用在全量线程上（含失锚），
 * `pendingClarification` 取 `groups.open`（已排除失锚），`orphaned` 取失锚组 ⇒ 一条 open
 * 的失锚 blocker 被数**两次**，而 open 的人工评论、全部 `answered`、全部已关闭线程
 * **一次都不数**。顶栏「批注 {n}」要的是「侧栏里一共有几条」，那就是**四组之和**
 * —— 四组互斥且穷尽（§20 断言 11 已把这条钉死），加起来天然无重复无遗漏。
 *
 * @param groups 侧栏四组（`pendingClarification` / `orphaned` / `total` 是**呈现维度**，按组算）。
 * @param threads 全量线程 —— `unresolvedBlocker` 必须在 `anchored` 过滤**之前**算。
 */
export function annotationCounts(
  groups: SidebarGroups,
  threads: readonly BlueprintThreadDetail[],
): {
  unresolvedBlocker: number
  pendingClarification: number
  orphaned: number
  total: number
} {
  const list = Array.isArray(threads) ? threads : []
  return {
    unresolvedBlocker: list.filter(isUnresolvedBlocker).length,
    pendingClarification: groups.open.filter(thread => thread.kind === 'ai_clarification').length,
    orphaned: groups.orphaned.length,
    total: groups.open.length + groups.answered.length + groups.closed.length + groups.orphaned.length,
  }
}

/** 判定一条 anchor 是否「有定位信息」（供第三态识别：`anchor === null` 的系统线程）。 */
export function hasAnchorLocator(anchor: BlueprintAnchor | null | undefined): boolean {
  if (!anchor)
    return false
  return Boolean(anchor.block_id)
}
