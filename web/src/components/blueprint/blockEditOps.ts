/**
 * block 级人工编辑的纯判据与 patch 构造（CLAR-03 闭环相位）。
 *
 * 与 `annotationTokens.ts` 同款定位：**组件旁的纯逻辑模块**，`<script setup>` 不能带值导出，
 * 而这三件都必须能被单独证伪 —— CLAR-03 正是栽在「后端齐备、产品面不可达而守卫全绿」上，
 * 可达性判据尤其不该藏成一段内联布尔表达式。
 *
 * ⛔ 无 IO、无 ORM、无 i18n：只有坐标系映射与闸门判定。
 */

import type { BlueprintBlock } from '~/types/blueprint'
import { isBlueprintEditable } from '~/config/blueprintStatus'

/** 可写回的字段落点；`null` = 该块不提供文本编辑面。 */
export type BlockEditTarget = 'text' | 'text_lines' | 'code_source' | null

/**
 * 判定某个块的文本写回落点 —— 读侧 `blockText`（`~/utils/blueprintBlocks`）的逆运算。
 *
 * ⛔ **绝不按 `block.type` 分派，一律按字段优先级**，与 `blockText` / 后端 `_block_text`
 * 三处同源。按 type 分派会造出「读取自 `text`、写回进 `code.source`」这种把原文复制成两份
 * 的块 —— 症状不是报错，而是编辑看着生效了、下次打开又变回旧文。
 *
 * 优先级：非空字符串 `text` → 数组 `text` → 非空 `code.source` → `rows`（**不可编辑**）
 * → 兜底当作字符串 `text`（空块也要能被写出内容）。
 *
 * ⛔ `rows`（table）判 `null`：它的文本坐标系是「单元格扁平后 `\n` 连接」，单框文本编辑
 * 压平行列后无法还原成 `rows`。与 115 对 table 强制整块批注的处置同源。
 */
export function blockEditTarget(block: BlueprintBlock | null | undefined): BlockEditTarget {
  if (!block || typeof block !== 'object')
    return null
  const raw = block as unknown as Record<string, unknown>

  if (typeof raw.text === 'string' && raw.text)
    return 'text'
  if (Array.isArray(raw.text))
    return 'text_lines'

  const code = raw.code
  if (code !== null && typeof code === 'object') {
    const source = (code as Record<string, unknown>).source
    if (typeof source === 'string' && source)
      return 'code_source'
  }

  if (Array.isArray(raw.rows))
    return null

  return 'text'
}

/**
 * 把编辑后的文本写回块，返回**新对象**（⛔ 不原地改入参 —— 它来自 TanStack Query 的缓存，
 * 原地改会让缓存里那份正文在请求还没回来时就先变了样）。
 *
 * `block_id` / `type` / `citations` 逐字保留：前者是 anchor 与 block 级 diff 的对齐键（改它
 * 会把该块上的全部线程 anchor 打散），后两项不属本面的编辑范围。
 */
export function withBlockText(block: BlueprintBlock, text: string): BlueprintBlock {
  const target = blockEditTarget(block)
  const next = { ...block } as BlueprintBlock & Record<string, unknown>
  if (target === 'text_lines')
    next.text = text.split('\n')
  else if (target === 'code_source')
    next.code = { ...(block.code ?? {}), source: text }
  else
    next.text = text
  return next
}

/**
 * ⭐ **编辑入口的可达性闸**（本能力唯一的一份判据，查看器直接消费）。
 *
 * 三条 AND，与查看器 `readonly` 的三个条件逐条同构：
 *
 * 1. 历史版本 / diff 视图 ⇒ 一律不可编辑（那两档看的都不是当前正文）；
 * 2. `isBlueprintEditable(currentStatus)` —— 白名单成员与后端
 *    `blueprint_lifecycle_service.EDITABLE_BLUEPRINT_STATUSES` 逐字对齐 ⇒ 一份已
 *    `confirmed` 的蓝图**拿不到编辑入口**（要改必须先驳回，`confirmed → drafting` 是合法边）；
 * 3. 该块有可写回的文本落点（查不到块 / table 块判假）。
 *
 * ⛔ 这不是权限判断：权威闸在后端（越界一律 400），本闸只决定入口渲染与否。
 */
export function canEditBlueprintBlock(
  currentStatus: string,
  block: BlueprintBlock | null | undefined,
  options: { historicalVersion?: boolean, diffMode?: boolean } = {},
): boolean {
  if (options.historicalVersion || options.diffMode)
    return false
  if (!isBlueprintEditable(currentStatus))
    return false
  return blockEditTarget(block) !== null
}
