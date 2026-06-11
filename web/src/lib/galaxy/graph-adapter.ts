/**
 * Galaxy 数据适配层：GalaxyNode/GalaxyEdge → graphology 图实例
 *
 * 集中维护视觉编码（颜色/尺寸），供 Sigma 渲染、reducers 高亮与图例组件共用，
 * 保证整个 Galaxy 体验的配色单一来源。
 */
import type { GalaxyEdge, GalaxyEdgeType, GalaxyNode, GalaxyNodeType, GalaxyRepoEdge, GalaxyRepoNode } from '~/api/galaxy'
import Graph from 'graphology'
import { calculateCirclesLayout } from './circles-layout'

export type GalaxyGraphNode = GalaxyNode | GalaxyRepoNode
export type GalaxyGraphEdge = GalaxyEdge | GalaxyRepoEdge

// ---------------------------------------------------------------------------
// 视觉编码（单一来源）
// ---------------------------------------------------------------------------

/** Galaxy 画布背景色 —— dim/brighten 混色的基准 */
export const GALAXY_BG = '#0a0a1f'

export const NODE_COLORS: Record<string, string> = {
  chunk_registry: '#8b93a7',
  symbol: '#60a5fa',
  endpoint: '#f59e0b',
  api_wrapper: '#34d399',
  api_call_site: '#22d3ee',
  repository: '#fbbf24',
}

export const NODE_TYPE_LABELS: Record<string, string> = {
  chunk_registry: 'Chunk',
  symbol: 'Symbol',
  endpoint: 'Endpoint',
  api_wrapper: 'API Wrapper',
  api_call_site: 'API Call Site',
  repository: 'Repository',
}

/** 节点基础尺寸（sigma px） */
export const NODE_BASE_SIZES: Record<string, number> = {
  chunk_registry: 3,
  symbol: 4,
  endpoint: 6,
  api_wrapper: 6,
  api_call_site: 2.5,
  repository: 14,
}

export const EDGE_COLORS: Record<string, string> = {
  CALL: '#5b8dd9',
  IMPORT: '#3fbf8f',
  SAME_FILE: '#2e3245',
  TEST_OF: '#d98e4a',
  CO_CHANGED: '#9b6fd4',
  SEMANTIC: '#d4548f',
  API_CALLS: '#f4587a',
  IMPLEMENTS: '#8b5cf6',
  REPO_API_CALL: '#f472b6',
}

export const EDGE_SIZES: Record<string, number> = {
  CALL: 1.2,
  IMPORT: 1.0,
  SAME_FILE: 0.5,
  TEST_OF: 1.0,
  CO_CHANGED: 0.8,
  SEMANTIC: 0.8,
  API_CALLS: 1.8,
  IMPLEMENTS: 1.0,
  REPO_API_CALL: 2.2,
}

// ---------------------------------------------------------------------------
// 颜色工具（dim = 向背景混合，brighten = 向白色混合）
// ---------------------------------------------------------------------------

function hexToRgb(hex: string): { r: number, g: number, b: number } {
  const match = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex)
  return match
    ? {
        r: Number.parseInt(match[1], 16),
        g: Number.parseInt(match[2], 16),
        b: Number.parseInt(match[3], 16),
      }
    : { r: 100, g: 100, b: 100 }
}

function rgbToHex(r: number, g: number, b: number): string {
  return `#${[r, g, b]
    .map((x) => {
      const v = Math.max(0, Math.min(255, Math.round(x))).toString(16)
      return v.length === 1 ? `0${v}` : v
    })
    .join('')}`
}

const BG_RGB = hexToRgb(GALAXY_BG)

/** 将颜色向画布背景色混合（amount ∈ [0,1]，越小越暗淡） */
export function dimColor(hex: string, amount: number): string {
  const rgb = hexToRgb(hex)
  return rgbToHex(
    BG_RGB.r + (rgb.r - BG_RGB.r) * amount,
    BG_RGB.g + (rgb.g - BG_RGB.g) * amount,
    BG_RGB.b + (rgb.b - BG_RGB.b) * amount,
  )
}

/** 提亮颜色（向白色靠拢，factor > 1） */
export function brightenColor(hex: string, factor: number): string {
  const rgb = hexToRgb(hex)
  return rgbToHex(
    rgb.r + ((255 - rgb.r) * (factor - 1)) / factor,
    rgb.g + ((255 - rgb.g) * (factor - 1)) / factor,
    rgb.b + ((255 - rgb.b) * (factor - 1)) / factor,
  )
}

// ---------------------------------------------------------------------------
// graphology 属性类型
// ---------------------------------------------------------------------------

export interface SigmaNodeAttributes {
  x: number
  y: number
  size: number
  color: string
  label: string
  nodeType: GalaxyNodeType
  filePath: string
  degree: number
  hidden?: boolean
  zIndex?: number
  highlighted?: boolean
  [key: string]: unknown
}

export interface SigmaEdgeAttributes {
  size: number
  color: string
  edgeType: GalaxyEdgeType
  weight: number
  type?: string
  hidden?: boolean
  zIndex?: number
  [key: string]: unknown
}

export type GalaxyGraph = Graph<SigmaNodeAttributes, SigmaEdgeAttributes>

// ---------------------------------------------------------------------------
// 图构建
// ---------------------------------------------------------------------------

/** 节点尺寸 = 类型基准 + degree 加成（开方衰减，封顶） */
export function nodeSize(type: string, degree: number): number {
  const base = NODE_BASE_SIZES[type] ?? 4
  return base + Math.min(6, Math.sqrt(Math.max(0, degree)) * 0.5)
}

/**
 * 把 Galaxy API 返回的节点/边转换为带初始布局坐标的 graphology 图。
 *
 * - 初始坐标由 circles-layout 确定性计算（首屏即成型）
 * - 跨仓 API_CALLS 等长程边使用 curved 渲染（需注册 EdgeCurveProgram）
 */
export function buildGalaxyGraph(
  nodes: GalaxyGraphNode[],
  edges: GalaxyGraphEdge[],
): GalaxyGraph {
  const graph = new Graph<SigmaNodeAttributes, SigmaEdgeAttributes>({
    multi: true,
    type: 'undirected',
  })

  const positions = calculateCirclesLayout(nodes)

  for (const node of nodes) {
    const pos = positions.get(node.id) ?? { x: 0, y: 0, ring: 0, angle: 0 }
    graph.addNode(node.id, {
      x: pos.x,
      y: pos.y,
      size: nodeSize(node.type, node.degree),
      color: NODE_COLORS[node.type] ?? '#8b93a7',
      label: node.label,
      nodeType: node.type,
      filePath: node.file_path ?? '',
      degree: node.degree,
    })
  }

  for (const edge of edges) {
    if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target))
      continue
    // 自环对力导向与渲染都没有意义
    if (edge.source === edge.target)
      continue

    const edgeType = edge.edge_type
    // 长程关系边走曲线，短程结构边走默认直线，减少视觉交叉
    const curved = edgeType === 'API_CALLS' || edgeType === 'REPO_API_CALL' || edgeType === 'SEMANTIC'
    graph.addEdgeWithKey(edge.id, edge.source, edge.target, {
      size: EDGE_SIZES[edgeType] ?? 1,
      color: EDGE_COLORS[edgeType] ?? '#2e3245',
      edgeType,
      weight: edge.weight ?? 1,
      ...(curved ? { type: 'curved', curvature: 0.2 } : {}),
    })
  }

  return graph
}
