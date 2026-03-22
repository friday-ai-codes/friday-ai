/**
 * useDownstreamVarCheck — 下游变量依赖检查
 *
 * 提供三个纯函数，用于检测编辑节点输出数据时
 * 是否会破坏下游节点的变量引用。
 */
/**
 * 从 config 对象中递归提取对指定节点的变量引用 key。
 * 匹配模式：{{nodes.<nodeIdentifier>.<key>}}
 * 支持 dot notation 路径（如 data.name）。
 */
export function extractNodeVarRefs(
 config: Record<string, unknown>,
 nodeIdentifier: string,
): string {
 const keys = new Set<string>
 // 转义 nodeIdentifier 中的特殊正则字符（如连字符）
 const escaped = nodeIdentifier.replace(/[.*+?^${}|[\]\\]/g, '\\$&')
 const pattern = new RegExp(`\\{\\{nodes\\.${escaped}\\.([\\w.]+)\\}\\}`, 'g')
 function walk(obj: unknown): void {
 if (typeof obj === 'string') {
 let match: RegExpExecArray | null
 // eslint-disable-next-line no-cond-assign
 while ((match = pattern.exec(obj)) !== null) {
 keys.add(match[1])
 }
 }
 else if (obj !== null && typeof obj === 'object') {
 for (const value of Object.values(obj as Record<string, unknown>)) {
 walk(value)
 }
 }
 }
 walk(config)
 return Array.from(keys)
}
/**
 * 获取下游节点对当前节点的所有变量依赖。
 * 同时检查 full id 和 short_id 两种引用方式。
 */
export function getDownstreamVarDeps(
 nodes: Array<{ id: string, short_id?: string, name: string, config: Record<string, unknown> }>,
 edges: Array<{ source: string, target: string }>,
 currentNodeId: string,
 currentNodeShortId?: string,
): Array<{ nodeId: string, nodeName: string, keys: string }> {
 // 找到所有从当前节点出发的边的目标节点
 const downstreamIds = new Set(
 edges
 .filter(e => e.source === currentNodeId)
 .map(e => e.target),
 )
 const result: Array<{ nodeId: string, nodeName: string, keys: string }> =
 for (const node of nodes) {
 if (!downstreamIds.has(node.id))
 continue
 // 合并 full id 和 short_id 两种引用的 key
 const keysSet = new Set<string>
 for (const key of extractNodeVarRefs(node.config, currentNodeId)) {
 keysSet.add(key)
 }
 if (currentNodeShortId) {
 for (const key of extractNodeVarRefs(node.config, currentNodeShortId)) {
 keysSet.add(key)
 }
 }
 const keys = Array.from(keysSet)
 if (keys.length > 0) {
 result.push({ nodeId: node.id, nodeName: node.name, keys })
 }
 }
 return result
}
/**
 * 检查编辑后数据是否缺少下游依赖的 key。
 * 支持 dot notation 路径检查（如 "data.name" 检查 editedData.data.name）。
 */
export function checkMissingKeys(
 editedData: Record<string, any>,
 deps: Array<{ nodeId: string, nodeName: string, keys: string }>,
): Array<{ nodeName: string, missingKeys: string }> {
 const warnings: Array<{ nodeName: string, missingKeys: string }> =
 for (const dep of deps) {
 const missingKeys: string =
 for (const key of dep.keys) {
 if (key.includes('.')) {
 // dot notation 路径检查
 const parts = key.split('.')
 let current: any = editedData
 let found = true
 for (const part of parts) {
 if (current === null || current === undefined || typeof current !== 'object' || !(part in current)) {
 found = false
 break
 }
 current = current[part]
 }
 if (!found) {
 missingKeys.push(key)
 }
 }
 else {
 // 顶级 key 检查
 if (!(key in editedData)) {
 missingKeys.push(key)
 }
 }
 }
 if (missingKeys.length > 0) {
 warnings.push({ nodeName: dep.nodeName, missingKeys })
 }
 }
 return warnings
}
