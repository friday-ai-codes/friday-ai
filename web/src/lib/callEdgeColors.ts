/**
 * 调用关系 DAG 边颜色常量
 * Vue Flow SVG 边不支持 Tailwind 类，必须用 HSL hex 值
 * key 与 DagEdge.call_type 枚举对齐（来自 codegraph.ts DagEdge）
 */
export const CALL_EDGE_COLORS = {
 DIRECT_CALL: 'hsl(217, 91%, 60%)', // blue-500
 METHOD_CALL: 'hsl(142, 71%, 45%)', // emerald-500
 ATTRIBUTE_ACCESS: 'hsl(215, 16%, 47%)', // slate-500
 INHERITANCE: 'hsl(270, 95%, 75%)', // violet-500（future-proof，当前 CallEdge 无此类型）
} as const
export type CallType = keyof typeof CALL_EDGE_COLORS
