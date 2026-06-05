/**
 * GraphRAG 二跳扩散边颜色常量
 *
 * Vue Flow SVG 边不支持 Tailwind 类，必须用 hex 字面值；
 * key 与 server/code_relations EdgeType TextChoices 严格对齐（CALL / IMPORT /
 * SAME_FILE / TEST_OF / CO_CHANGED / SEMANTIC）。
 *
 * 与 web/src/lib/callEdgeColors.ts 结构同构；任何模板硬编码 hex 均视为偏离
 * （UI-SPEC §10 硬约束 3）。
 */
export const DIFFUSION_EDGE_COLORS = {
  CALL: '#3b82f6',
  IMPORT: '#10b981',
  SAME_FILE: '#6b7280',
  TEST_OF: '#f97316',
  CO_CHANGED: '#a855f7',
  SEMANTIC: '#ec4899',
} as const

export type EdgeType = keyof typeof DIFFUSION_EDGE_COLORS
