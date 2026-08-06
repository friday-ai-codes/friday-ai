/**
 * 批注视觉令牌（Phase 115，UI-SPEC §7.5 的**唯一来源**）；另含 §18.3 的焦点环令牌
 * `FOCUS_RING_CLASS`（本相位新增可聚焦目标共用一份，⛔ 不在各组件里各写一串）。
 *
 * 形状照 `~/components/knowledge/artifactDisplay.ts`：模块级 `Record` 常量 + 查表函数。
 * ⛔ **批注相关组件内不得再写任何颜色字面量** —— 四色相 × 四处置态 × 选中态的全部组合都
 * 由本模块的 `annotationClass()` 给出。
 *
 * ## 为什么色值是「暗一档」的
 *
 * 下划线是**非文本图形**，受 WCAG 1.4.11 的 3:1 约束（下表括号内是 sRGB 相对亮度实算 vs 白底）：
 * - ⛔ **不用 `--color-primary` 原值（teal-500，白底仅 2.49:1）作描边** ⇒ teal 一律降一档到
 *   `--color-primary-600` = `hsl(167_76%_32%)`（3.74:1）。底纹才用 teal-500 的低透明度叠加。
 * - ⛔ amber 原值（`hsl(38_92%_50%)`，2.14:1）**只能作底纹**，描边用 `hsl(26_90%_37%)`（5.02:1）。
 * - 选中态的 outline 用**不透明** teal-600；⛔ 不复制既有焦点环那个半透明 teal-500 值
 *   （50% 透明，实算仅 1.59:1，本相位新增面不得沿用）。
 *
 * ## 为什么类名是写死的字面量而不是运行期拼的
 *
 * Tailwind 的 content 扫描只认**源码里出现的完整类名**。底纹透明度随处置态与选中态变化
 * （满档 / ×0.6 / ×1.4 封顶 0.20），若在运行期算出 `hsl(... / ${alpha})` 塞进 class，
 * Tailwind 根本不会生成对应规则 ⇒ **底纹整片消失且不报错**。故这里把 22 种组合逐条写成
 * 字面量，⛔ 不做字符串插值。
 *
 * ## `<mark>` 黄底重置的落点
 *
 * `<mark>` 的浏览器默认黄底必须被重置。`annotationClass()` 的返回值**恒含且仅含一条**
 * `bg-*` 声明（无底纹档是 `bg-transparent`）—— 刻意不在共享前缀里再放一个 `bg-transparent`，
 * 否则同一元素上会出现两条同优先级的 `background-color`，谁生效取决于 Tailwind 的产出顺序。
 * 不走 `annotationClass()` 的场景（如越界降级的整块左色条）用 `MARK_BASE_CLASS`。
 */

import type { BlueprintThreadDetail } from '~/types/blueprint'

/** 五个色相档（`teal` 服务澄清与确认门两种 kind，`violet` 服务人工评论）。 */
export type AnnotationHue = 'blocker' | 'warning' | 'info' | 'teal' | 'violet'

/**
 * 重叠区间的着色优先级（**从高到低**）：一个字符可同时属于多条线程，视觉取排名最高的一条，
 * `title` / `aria-label` 仍列出全部。
 */
export const ANNOTATION_PRIORITY: readonly string[] = [
  'blocker',
  'warning',
  'human_comment',
  'info',
  'ai_clarification',
]

/** 同优先级时的处置态排序（**从高到低**）。 */
export const ANNOTATION_STATUS_PRIORITY: readonly string[] = [
  'open',
  'answered',
  'resolved',
  'dismissed',
]

/** 线程 → `ANNOTATION_PRIORITY` 里的令牌（finding 按 severity，其余按 kind）。 */
function priorityToken(kind: string, severity: string): string {
  if (kind === 'ai_review_finding')
    return severity === 'blocker' || severity === 'warning' ? severity : 'info'
  if (kind === 'human_comment')
    return 'human_comment'
  return 'ai_clarification'
}

function rank(list: readonly string[], token: string): number {
  const index = list.indexOf(token)
  // 未登记的取值排在最后，⛔ 不抛异常（半可信数据）。
  return index === -1 ? list.length : index
}

/**
 * 比较两条线程的着色优先级：返回负数表示 `a` 更该被用来着色。
 *
 * 先比色相档（blocker → warning → human_comment → info/ai_clarification），
 * 同档再比处置态（open → answered → resolved/dismissed）。
 */
export function compareAnnotationPriority(
  a: Pick<BlueprintThreadDetail, 'kind' | 'severity' | 'status'>,
  b: Pick<BlueprintThreadDetail, 'kind' | 'severity' | 'status'>,
): number {
  const byKind
    = rank(ANNOTATION_PRIORITY, priorityToken(a.kind, a.severity))
      - rank(ANNOTATION_PRIORITY, priorityToken(b.kind, b.severity))
  if (byKind !== 0)
    return byKind
  return rank(ANNOTATION_STATUS_PRIORITY, a.status) - rank(ANNOTATION_STATUS_PRIORITY, b.status)
}

/** 从覆盖同一子段的多条线程里挑出用来着色的那条；空数组返回 `null`。 */
export function pickTopThread<T extends Pick<BlueprintThreadDetail, 'kind' | 'severity' | 'status'>>(
  threads: readonly T[],
): T | null {
  if (!Array.isArray(threads) || threads.length === 0)
    return null
  return threads.reduce((best, current) =>
    compareAnnotationPriority(current, best) < 0 ? current : best)
}

/** 线程种类 + 严重级 → 色相档（`repo_confirmation` 与 `ai_clarification` 同档）。 */
export function annotationHue(kind: string, severity: string): AnnotationHue {
  if (kind === 'ai_review_finding') {
    if (severity === 'blocker')
      return 'blocker'
    if (severity === 'warning')
      return 'warning'
    return 'info'
  }
  if (kind === 'human_comment')
    return 'violet'
  if (kind === 'ai_clarification' || kind === 'repo_confirmation')
    return 'teal'
  return 'info'
}

/**
 * 侧栏分组头的 kind 色点（quick-260806-tsb）：与批注下划线的色相档取同一批 `hsl()` 字面量
 * （澄清 teal、人工评论 violet；审查组混合 severity 取警示 amber 作组级指征；确认门取 sky
 * 与其余三档拉开）。
 *
 * ⭐ 落在本模块而不是组件里：批注功能色的 `hsl()` 字面量**只许集中在这里**（源码守卫
 * §15 对扫描面内的裸 Tailwind 调色板色零容忍，`annotationTokens.ts` 是唯一豁免区）。
 * 仅作装饰，调用方需配 `aria-hidden`。
 */
export const KIND_DOT_CLASS: Record<string, string> = {
  ai_clarification: 'bg-[hsl(168_76%_42%)]',
  ai_review_finding: 'bg-[hsl(38_92%_50%)]',
  human_comment: 'bg-[hsl(263_70%_50%)]',
  repo_confirmation: 'bg-[hsl(199_89%_48%)]',
}

/**
 * 本相位**新增可聚焦目标**的统一焦点环（UI-SPEC §18.3 逐字：`outline: 2px solid
 * var(--color-primary-600); outline-offset: 2px`，不透明 teal-600，实算 3.74:1 ✓）。
 *
 * ⛔ **不得复制既有 `.btn:focus-visible` 的 50% 透明 teal-500**（白底合成后仅 1.59:1，
 * 未过 WCAG 2.4.11）—— 既有面本相位不修，但新增面不许沿用那个值。
 *
 * ⚠️ `outline-none` 必须留在串内：`<mark>` 等元素要压掉浏览器默认环，否则焦点态会叠出两圈。
 * 压掉之后**必须**有 `focus-visible:` 变体接上，否则键盘用户完全看不到焦点落在哪里。
 */
export const FOCUS_RING_CLASS = 'outline-none focus-visible:[outline:2px_solid_var(--color-primary-600)] focus-visible:[outline-offset:2px]'

/**
 * 与批注无关的共享形态（⚠️ 刻意不含任何 `bg-*`，见文件头 docstring）。
 *  `transition-colors`：hover/选中态底纹加深的过渡（飞书文档划线手感，quick-260806-j1z）。
 */
const MARK_SHAPE_CLASS = `text-foreground rounded-sm cursor-pointer align-baseline transition-colors duration-150 ${FOCUS_RING_CLASS}`

/**
 * `<mark>` 的独立重置类（含黄底重置），供**不经 `annotationClass()`** 的场景使用
 * （如越界降级时的整块左色条容器）。
 */
export const MARK_BASE_CLASS = `${MARK_SHAPE_CLASS} bg-transparent`

/** 选中态叠加：不透明 teal-600 outline（3.74:1），⛔ 不用半透明值。 */
const ACTIVE_OUTLINE_CLASS = '[outline:2px_solid_hsl(167_76%_32%)] [outline-offset:1px]'

/**
 * 「色相 × 处置态 × 选中态」的字面量类名表。
 *
 * 底纹透明度：满档（open）→ ×0.6（answered）→ 无（resolved/dismissed）；选中态在此基础上
 * ×1.4 并封顶 0.20。描边：2px solid（open）/ 2px dashed（answered）/ 1px dotted 且色改灰
 * （resolved/dismissed）；选中态描边一律加粗到 3px。
 */
const HUE_CLASS: Record<AnnotationHue, Record<'open' | 'answered', { normal: string, active: string }>> = {
  blocker: {
    open: {
      normal: '[border-bottom:2px_solid_hsl(0_72%_45%)] bg-[hsl(0_72%_51%/0.12)] hover:bg-[hsl(0_72%_51%/0.168)]',
      active: '[border-bottom:3px_solid_hsl(0_72%_45%)] bg-[hsl(0_72%_51%/0.168)]',
    },
    answered: {
      normal: '[border-bottom:2px_dashed_hsl(0_72%_45%)] bg-[hsl(0_72%_51%/0.072)] hover:bg-[hsl(0_72%_51%/0.101)]',
      active: '[border-bottom:3px_dashed_hsl(0_72%_45%)] bg-[hsl(0_72%_51%/0.101)]',
    },
  },
  warning: {
    open: {
      normal: '[border-bottom:2px_solid_hsl(26_90%_37%)] bg-[hsl(38_92%_50%/0.12)] hover:bg-[hsl(38_92%_50%/0.168)]',
      active: '[border-bottom:3px_solid_hsl(26_90%_37%)] bg-[hsl(38_92%_50%/0.168)]',
    },
    answered: {
      normal: '[border-bottom:2px_dashed_hsl(26_90%_37%)] bg-[hsl(38_92%_50%/0.072)] hover:bg-[hsl(38_92%_50%/0.101)]',
      active: '[border-bottom:3px_dashed_hsl(26_90%_37%)] bg-[hsl(38_92%_50%/0.101)]',
    },
  },
  info: {
    open: {
      normal: '[border-bottom:2px_solid_hsl(215_16%_40%)] bg-[hsl(215_16%_47%/0.10)] hover:bg-[hsl(215_16%_47%/0.14)]',
      active: '[border-bottom:3px_solid_hsl(215_16%_40%)] bg-[hsl(215_16%_47%/0.14)]',
    },
    answered: {
      normal: '[border-bottom:2px_dashed_hsl(215_16%_40%)] bg-[hsl(215_16%_47%/0.06)] hover:bg-[hsl(215_16%_47%/0.084)]',
      active: '[border-bottom:3px_dashed_hsl(215_16%_40%)] bg-[hsl(215_16%_47%/0.084)]',
    },
  },
  teal: {
    open: {
      normal: '[border-bottom:2px_solid_hsl(167_76%_32%)] bg-[hsl(168_76%_42%/0.12)] hover:bg-[hsl(168_76%_42%/0.168)]',
      active: '[border-bottom:3px_solid_hsl(167_76%_32%)] bg-[hsl(168_76%_42%/0.168)]',
    },
    answered: {
      normal: '[border-bottom:2px_dashed_hsl(167_76%_32%)] bg-[hsl(168_76%_42%/0.072)] hover:bg-[hsl(168_76%_42%/0.101)]',
      active: '[border-bottom:3px_dashed_hsl(167_76%_32%)] bg-[hsl(168_76%_42%/0.101)]',
    },
  },
  violet: {
    open: {
      normal: '[border-bottom:2px_solid_hsl(263_70%_50%)] bg-[hsl(263_70%_50%/0.10)] hover:bg-[hsl(263_70%_50%/0.14)]',
      active: '[border-bottom:3px_solid_hsl(263_70%_50%)] bg-[hsl(263_70%_50%/0.14)]',
    },
    answered: {
      normal: '[border-bottom:2px_dashed_hsl(263_70%_50%)] bg-[hsl(263_70%_50%/0.06)] hover:bg-[hsl(263_70%_50%/0.084)]',
      active: '[border-bottom:3px_dashed_hsl(263_70%_50%)] bg-[hsl(263_70%_50%/0.084)]',
    },
  },
}

/** `resolved` / `dismissed`：色相退成灰、无底纹（默认隐藏，由「显示已关闭批注」开关放出）。 */
const CLOSED_CLASS = {
  normal: '[border-bottom:1px_dotted_hsl(215_16%_47%)] bg-transparent',
  active: '[border-bottom:3px_dotted_hsl(215_16%_47%)] bg-transparent',
} as const

/**
 * 取 `<mark>` 的完整类名串（形态重置 + 色相 + 处置态 + 选中态叠加）。
 *
 * 返回值**恒含且仅含一条** `bg-*`（无底纹档是 `bg-transparent`），因此可以直接作为 `<mark>`
 * 的 `:class`，黄底一定被压掉。
 *
 * @example annotationClass('ai_review_finding', 'blocker', 'open', false)
 * @example annotationClass('human_comment', '', 'resolved', true)
 */
export function annotationClass(
  kind: string,
  severity: string,
  status: string,
  active = false,
): string {
  const state = active ? 'active' : 'normal'
  const tone
    = status === 'resolved' || status === 'dismissed'
      ? CLOSED_CLASS[state]
      : HUE_CLASS[annotationHue(kind, severity)][status === 'answered' ? 'answered' : 'open'][state]
  return active
    ? `${MARK_SHAPE_CLASS} ${tone} ${ACTIVE_OUTLINE_CLASS}`
    : `${MARK_SHAPE_CLASS} ${tone}`
}
