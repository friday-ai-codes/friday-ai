/**
 * 反馈状态/分类的统一视觉映射（语义色徽章 + 分类图标），供反馈相关页面共享，
 * 保证列表、详情、我的反馈三处状态/分类视觉一致（避免 hardcode 散落）。
 *
 * 注意：class 字符串以「完整字面量」形式书写，确保 Tailwind 扫描器能生成对应 CSS。
 * 动态拼接的 icon-[...] 已在 styles/main.css 的 @source inline 中 safelist。
 */
import type { FeedbackCategory, FeedbackStatus } from '~/types/feedback'

/** 状态语义色徽章（含 light/dark 配对，ring 内描边）。 */
export const FEEDBACK_STATUS_BADGE: Record<FeedbackStatus, string> = {
  open: 'bg-amber-50 text-amber-700 ring-amber-600/20 dark:bg-amber-500/10 dark:text-amber-400 dark:ring-amber-400/25',
  in_progress: 'bg-blue-50 text-blue-700 ring-blue-600/20 dark:bg-blue-500/10 dark:text-blue-400 dark:ring-blue-400/25',
  resolved: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-500/10 dark:text-emerald-400 dark:ring-emerald-400/25',
  closed: 'bg-slate-100 text-slate-600 ring-slate-500/20 dark:bg-slate-500/10 dark:text-slate-400 dark:ring-slate-400/25',
  wont_fix: 'bg-rose-50 text-rose-700 ring-rose-600/20 dark:bg-rose-500/10 dark:text-rose-400 dark:ring-rose-400/25',
}

/** 状态小圆点颜色（用于列表/筛选指示）。 */
export const FEEDBACK_STATUS_DOT: Record<FeedbackStatus, string> = {
  open: 'bg-amber-500',
  in_progress: 'bg-blue-500',
  resolved: 'bg-emerald-500',
  closed: 'bg-slate-400',
  wont_fix: 'bg-rose-500',
}

/** 分类图标（lucide）。 */
export const FEEDBACK_CATEGORY_ICON: Record<FeedbackCategory, string> = {
  bug: 'icon-[lucide--bug]',
  question: 'icon-[lucide--circle-help]',
  feature: 'icon-[lucide--lightbulb]',
  other: 'icon-[lucide--tag]',
}

/** 分类图标着色（点缀色，区分类型）。 */
export const FEEDBACK_CATEGORY_COLOR: Record<FeedbackCategory, string> = {
  bug: 'text-rose-500',
  question: 'text-blue-500',
  feature: 'text-amber-500',
  other: 'text-slate-400',
}

export const FEEDBACK_STATUSES: FeedbackStatus[] = [
  'open',
  'in_progress',
  'resolved',
  'closed',
  'wont_fix',
]

export const FEEDBACK_CATEGORIES: FeedbackCategory[] = ['bug', 'question', 'feature', 'other']

export function statusBadgeClass(status: string): string {
  return FEEDBACK_STATUS_BADGE[status as FeedbackStatus] ?? FEEDBACK_STATUS_BADGE.closed
}

export function statusDotClass(status: string): string {
  return FEEDBACK_STATUS_DOT[status as FeedbackStatus] ?? FEEDBACK_STATUS_DOT.closed
}

export function categoryIconClass(category: string): string {
  return FEEDBACK_CATEGORY_ICON[category as FeedbackCategory] ?? FEEDBACK_CATEGORY_ICON.other
}

export function categoryColorClass(category: string): string {
  return FEEDBACK_CATEGORY_COLOR[category as FeedbackCategory] ?? FEEDBACK_CATEGORY_COLOR.other
}
