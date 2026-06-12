/**
 * 变量引用统一构造 util（VAR-03）。
 *
 * 统一格式契约：节点输出引用一律为 `{{nodes.<short_id>.<field.path>}}`，
 * 禁止生成 UUID 形式（`{{nodes.<uuid>.*}}`）或 UUID 前 8 位截断形式的引用。
 *
 * 变量选择器（VariablePicker）、端口复制（NodePortsDisplay）、
 * SmartInput（经 useDesignTimeVariables）及 schema 展示（useNodeSchema）
 * 的全部引用生成点必须 import 本模块构造，杜绝各处手写拼接。
 *
 * 非节点前缀（input/trigger/global/context/config）引用同样必须经
 * buildPrefixPath / buildPrefixRef 构造（锁定决策 VAR-03）。
 */

/** 非节点前缀类型（与后端解析器支持的前缀一致，nodes 前缀走 buildNodePath） */
export type VariablePrefix = 'input' | 'trigger' | 'global' | 'context' | 'config'

/**
 * 构造节点变量路径（无大括号），供 picker 的 path 字段使用，
 * 选中时由 selectVariable 包裹 {{}}。
 *
 * @example buildNodePath('aB1', 'data.name') // 'nodes.aB1.data.name'
 */
export function buildNodePath(shortId: string, fieldPath: string): string {
  return `nodes.${shortId}.${fieldPath}`
}

/**
 * 构造完整节点引用（含大括号），供端口复制 / schema 展示直接使用。
 *
 * @example buildNodeRef('aB1', 'output') // '{{nodes.aB1.output}}'
 */
export function buildNodeRef(shortId: string, fieldPath: string): string {
  return `{{${buildNodePath(shortId, fieldPath)}}}`
}

/**
 * 构造非节点前缀变量路径（无大括号），供 picker 的 path 字段使用。
 *
 * @example buildPrefixPath('trigger', 'event_type') // 'trigger.event_type'
 */
export function buildPrefixPath(prefix: VariablePrefix, fieldPath: string): string {
  return `${prefix}.${fieldPath}`
}

/**
 * 构造完整非节点前缀引用（含大括号）。
 *
 * @example buildPrefixRef('trigger', 'event_type') // '{{trigger.event_type}}'
 */
export function buildPrefixRef(prefix: VariablePrefix, fieldPath: string): string {
  return `{{${buildPrefixPath(prefix, fieldPath)}}}`
}
