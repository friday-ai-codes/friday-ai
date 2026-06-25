/**
 * 运维大盘共享格式化纯函数（无副作用，供 75-02/03/04 三页 tabular 展示复用）。
 *
 * 口径约定：所有函数对 null / undefined / NaN 一律返回占位符 '—'，绝不抛异常。
 * 千分位/分位用 `tabular-nums` 等宽对齐由调用方在模板加 class，本层只产出字符串。
 */

/** 无数据占位符（统一全大盘空值展示）。 */
export const EMPTY = '—'

function isNil(v: number | null | undefined): v is null | undefined {
  return v === null || v === undefined || Number.isNaN(v)
}

/** 千分位整数/定点数（digits 指定小数位，默认 0）。null/NaN → '—'。 */
export function formatNumber(v: number | null | undefined, digits = 0): string {
  if (isNil(v))
    return EMPTY
  return v.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

/**
 * 比率口径：入参为 0..1 的小数（如 SLA availability=0.999），输出百分比字符串。
 * 例：formatRatio(0.999) → '99.90%'。null/NaN → '—'。
 */
export function formatRatio(v: number | null | undefined, digits = 2): string {
  if (isNil(v))
    return EMPTY
  return `${(v * 100).toFixed(digits)}%`
}

/**
 * 百分比口径：入参已是百分数（如 cpu_percent=42.5），直接补 '%'。
 * 例：formatPercent(42.5) → '42.50%'。null/NaN → '—'。
 */
export function formatPercent(v: number | null | undefined, digits = 2): string {
  if (isNil(v))
    return EMPTY
  return `${v.toFixed(digits)}%`
}

/**
 * 时长（毫秒）人性化：<1000 → `${ms}ms`；<60000 → `${s}s`；否则 `${m}m`。
 * null/NaN → '—'。
 */
export function formatDurationMs(ms: number | null | undefined): string {
  if (isNil(ms))
    return EMPTY
  if (ms < 1000)
    return `${Math.round(ms)}ms`
  if (ms < 60000)
    return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}

/** 千分缩写（TPS 等大数）：≥1000 → `${(v/1000).toFixed(1)}k`，否则原值。null/NaN → '—'。 */
export function formatThousands(v: number | null | undefined): string {
  if (isNil(v))
    return EMPTY
  if (Math.abs(v) >= 1000)
    return `${(v / 1000).toFixed(1)}k`
  return formatNumber(v)
}

/** 相对时间（如「3 分钟前」/「刚刚」）。无效 iso → '—'。 */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso)
    return EMPTY
  const t = new Date(iso).getTime()
  if (Number.isNaN(t))
    return EMPTY
  const diffSec = Math.round((Date.now() - t) / 1000)
  if (diffSec < 0)
    return '刚刚'
  if (diffSec < 60)
    return diffSec <= 5 ? '刚刚' : `${diffSec} 秒前`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60)
    return `${diffMin} 分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24)
    return `${diffHour} 小时前`
  const diffDay = Math.floor(diffHour / 24)
  return `${diffDay} 天前`
}

/** 时钟（HH:mm:ss，本地时区）。无效 iso → '—'。 */
export function formatClock(iso: string | null | undefined): string {
  if (!iso)
    return EMPTY
  const d = new Date(iso)
  if (Number.isNaN(d.getTime()))
    return EMPTY
  return d.toLocaleTimeString('zh-CN', { hour12: false })
}

/** 本地化日期时间（YYYY/MM/DD HH:mm:ss 风格，本地时区）。无效 iso → '—'。 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso)
    return EMPTY
  const d = new Date(iso)
  if (Number.isNaN(d.getTime()))
    return EMPTY
  return d.toLocaleString('zh-CN', { hour12: false })
}
