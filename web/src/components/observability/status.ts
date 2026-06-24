/**
 * 运维大盘共享状态语义色纯函数（对齐 UI-SPEC §0.3 绿/琥珀/红三档）。
 *
 * class 风格复用既有 observability/index.vue：`text-<color>-500 bg-<color>-500/10`，
 * 亮暗双主题均由 Tailwind 语义色自适应。全部为纯函数，无副作用。
 */

/** 中性/未知态色（muted）。 */
const MUTED = 'text-muted-foreground bg-muted'

/** 日志级别 → 语义色：error/critical 红、warn 琥珀、debug muted、info 蓝、其余 muted。 */
export function logLevelClass(level: string): string {
  const v = (level || '').trim().toLowerCase()
  if (v === 'error' || v === 'critical' || v === 'fatal')
    return 'text-rose-500 bg-rose-500/10'
  if (v === 'warn' || v === 'warning')
    return 'text-amber-500 bg-amber-500/10'
  if (v === 'info')
    return 'text-blue-500 bg-blue-500/10'
  if (v === 'debug' || v === 'trace')
    return MUTED
  return MUTED
}

/** 告警级别 → 语义色：P0 红 / P1 琥珀 / P2 蓝。 */
export function alertSeverityClass(sev: 'P0' | 'P1' | 'P2' | string): string {
  if (sev === 'P0')
    return 'text-rose-500 bg-rose-500/10'
  if (sev === 'P1')
    return 'text-amber-500 bg-amber-500/10'
  if (sev === 'P2')
    return 'text-blue-500 bg-blue-500/10'
  return MUTED
}

/** 告警状态 → 语义色：firing 红（进行中）/ resolved 绿（已恢复）。 */
export function alertStatusClass(status: 'firing' | 'resolved' | string): string {
  if (status === 'firing')
    return 'text-rose-500 bg-rose-500/10'
  if (status === 'resolved')
    return 'text-emerald-500 bg-emerald-500/10'
  return MUTED
}

/**
 * 阈值变色：默认「越大越危险」——value≥crit 红、≥warn 琥珀、否则绿。
 * invert=true 时「越小越危险」（如可用率）：value≤crit 红、≤warn 琥珀、否则绿。
 * 返回文本 + 背景 class。
 */
export function healthBandClass(value: number, warn: number, crit: number, invert = false): string {
  if (Number.isNaN(value))
    return MUTED
  const red = 'text-rose-500 bg-rose-500/10'
  const amber = 'text-amber-500 bg-amber-500/10'
  const green = 'text-emerald-500 bg-emerald-500/10'
  if (invert) {
    if (value <= crit)
      return red
    if (value <= warn)
      return amber
    return green
  }
  if (value >= crit)
    return red
  if (value >= warn)
    return amber
  return green
}

/** 健康分档：≥80 健康（绿）/ 60–79 警告（琥珀）/ <60 严重（红）。返回 label + class。 */
export function healthScoreBand(score: number): { label: string, class: string } {
  if (Number.isNaN(score))
    return { label: '未知', class: MUTED }
  if (score >= 80)
    return { label: '健康', class: 'text-emerald-500 bg-emerald-500/10' }
  if (score >= 60)
    return { label: '警告', class: 'text-amber-500 bg-amber-500/10' }
  return { label: '严重', class: 'text-rose-500 bg-rose-500/10' }
}
