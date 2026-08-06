/**
 * 蓝图标题 / 列表时间派生（与后端 `format_blueprint_title` 同口径）。
 *
 * 模板：`{projectName} - 技术方案 - YYYY-MM-DD HH:mm`（Asia/Shanghai 墙钟）。
 * 列表时间精确到分钟，⛔ 不含秒。
 */

const FALLBACK_PROJECT_NAME = '未关联项目'
const SHANGHAI = 'Asia/Shanghai'

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

/** 把 ISO / Date 转到上海墙钟的年月日时分；非法输入返回 null。 */
function shanghaiParts(whenIso: string | null | undefined): {
  year: number
  month: number
  day: number
  hour: number
  minute: number
} | null {
  if (!whenIso)
    return null
  const date = new Date(whenIso)
  if (Number.isNaN(date.getTime()))
    return null
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: SHANGHAI,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date)
  const get = (type: string) => Number(parts.find(p => p.type === type)?.value ?? NaN)
  const year = get('year')
  const month = get('month')
  const day = get('day')
  let hour = get('hour')
  const minute = get('minute')
  // 部分环境对 24:00 会给出 hour=24
  if (hour === 24)
    hour = 0
  if ([year, month, day, hour, minute].some(n => Number.isNaN(n)))
    return null
  return { year, month, day, hour, minute }
}

function formatShanghaiMinute(whenIso: string | null | undefined): string {
  const p = shanghaiParts(whenIso)
  if (!p)
    return ''
  return `${p.year}-${pad2(p.month)}-${pad2(p.day)} ${pad2(p.hour)}:${pad2(p.minute)}`
}

/** 与后端 `format_blueprint_title` 同模板。 */
export function formatBlueprintTitle(
  projectName: string | null | undefined,
  whenIso: string | null | undefined,
): string {
  const name = (projectName ?? '').trim() || FALLBACK_PROJECT_NAME
  const stamp = formatShanghaiMinute(whenIso)
  if (!stamp)
    return `${name} - 技术方案`
  return `${name} - 技术方案 - ${stamp}`
}

/** 列表创建时间：固定 `YYYY-MM-DD HH:mm`（上海墙钟，无秒）。 */
export function formatBlueprintListTime(iso: string | null | undefined): string {
  return formatShanghaiMinute(iso)
}
