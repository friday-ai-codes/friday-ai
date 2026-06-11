/**
 * Galaxy Sigma 渲染引擎 composable（借鉴 GitNexus useSigma 架构）
 *
 * 职责：
 * - Sigma (WebGL 2D) 实例生命周期管理
 * - ForceAtlas2 Web Worker 短时布局精修 + noverlap 收尾（主线程零阻塞）
 * - nodeReducer / edgeReducer：类型过滤（hidden）+ 选中/hover 高亮（邻居提亮、其余 dim）
 * - 自定义 canvas hover pill（深色底 + 节点光环，替代 DOM tooltip）
 * - 相机控制（zoom / fit / focusNode）与 FPS 监控
 */
import type { Attributes } from 'graphology-types'
import type { Settings } from 'sigma/settings'
import type { GalaxyEdgeType, GalaxyNodeType } from '~/api/galaxy'
import type { GalaxyGraph } from '~/lib/galaxy/graph-adapter'
import EdgeCurveProgram from '@sigma/edge-curve'
import forceAtlas2 from 'graphology-layout-forceatlas2'
import FA2Layout from 'graphology-layout-forceatlas2/worker'
import noverlap from 'graphology-layout-noverlap'
import Sigma from 'sigma'
import { onBeforeUnmount, ref } from 'vue'
import {
  brightenColor,
  dimColor,
  NODE_TYPE_LABELS,
} from '~/lib/galaxy/graph-adapter'

export interface UseGalaxySigmaOptions {
  onNodeClick?: (nodeId: string) => void
  onNodeHover?: (nodeId: string | null) => void
  onStageClick?: () => void
  onFpsUpdate?: (fps: number) => void
}

const NOVERLAP_SETTINGS = {
  maxIterations: 30,
  ratio: 1.1,
  margin: 3,
  expansion: 1.05,
}

/** 按节点数自适应 FA2 精修时长（ms）——初始布局已接近终态，无需长跑 */
function layoutDuration(nodeCount: number): number {
  if (nodeCount > 2000)
    return 9000
  if (nodeCount > 800)
    return 6000
  if (nodeCount > 300)
    return 4000
  return 2500
}

export function useGalaxySigma(options: UseGalaxySigmaOptions = {}) {
  let sigma: Sigma<Attributes, Attributes, Attributes> | null = null
  let graph: GalaxyGraph | null = null
  let fa2: InstanceType<typeof FA2Layout> | null = null
  let layoutTimer: ReturnType<typeof setTimeout> | null = null

  // FPS 监控
  let animFrameId = 0
  let fpsFrameCount = 0
  let fpsLastTime = 0

  // 交互状态（闭包内供 reducers 读取，变化后手动 refresh）
  let hoveredId: string | null = null
  let selectedId: string | null = null
  let activeNeighbors = new Set<string>()
  let visibleNodeTypes: Set<GalaxyNodeType> | null = null
  let visibleEdgeTypes: Set<GalaxyEdgeType> | null = null

  const layoutRunning = ref(false)

  // -------------------------------------------------------------------------
  // 高亮辅助
  // -------------------------------------------------------------------------

  function activeNodeId(): string | null {
    return selectedId ?? hoveredId
  }

  function rebuildNeighbors(): void {
    activeNeighbors = new Set()
    const active = activeNodeId()
    if (!active || !graph || !graph.hasNode(active))
      return
    graph.forEachNeighbor(active, (neighbor) => {
      activeNeighbors.add(neighbor)
    })
  }

  // -------------------------------------------------------------------------
  // Reducers：类型过滤 + 高亮/暗化
  // -------------------------------------------------------------------------

  function nodeReducer(node: string, data: Attributes): Attributes {
    const res = { ...data }
    const nodeType = data.nodeType as GalaxyNodeType | undefined

    if (visibleNodeTypes && nodeType && !visibleNodeTypes.has(nodeType)) {
      res.hidden = true
      return res
    }

    const active = activeNodeId()
    if (active) {
      if (node === active) {
        res.size = (data.size as number) * 1.5
        res.zIndex = 3
        res.highlighted = true
      }
      else if (activeNeighbors.has(node)) {
        res.size = (data.size as number) * 1.15
        res.color = brightenColor(data.color as string, 1.25)
        res.zIndex = 2
      }
      else {
        res.color = dimColor(data.color as string, 0.18)
        res.size = (data.size as number) * 0.7
        res.zIndex = 0
        res.label = ''
      }
    }

    return res
  }

  function edgeReducer(edge: string, data: Attributes): Attributes {
    const res = { ...data }
    const edgeType = data.edgeType as GalaxyEdgeType | undefined

    if (visibleEdgeTypes && edgeType && !visibleEdgeTypes.has(edgeType)) {
      res.hidden = true
      return res
    }

    const active = activeNodeId()
    if (active && graph) {
      const [source, target] = graph.extremities(edge)
      if (source === active || target === active) {
        res.color = brightenColor(data.color as string, 1.6)
        res.size = Math.max(1.6, (data.size as number) * 2)
        res.zIndex = 2
      }
      else {
        res.color = dimColor(data.color as string, 0.1)
        res.size = Math.max(0.2, (data.size as number) * 0.5)
        res.zIndex = 0
      }
    }

    return res
  }

  // -------------------------------------------------------------------------
  // 自定义 hover：深色 pill 标签（标题 + 文件路径 + 类型/degree）+ 节点光环
  // -------------------------------------------------------------------------

  function drawNodeHover(
    context: CanvasRenderingContext2D,
    data: { x: number, y: number, size: number, label: string | null, color: string },
    settings: Settings<Attributes, Attributes, Attributes>,
  ): void {
    const title = data.label ?? ''
    if (!title)
      return

    const lines: Array<{ text: string, font: string, color: string }> = [
      {
        text: title,
        font: `600 12px ${settings.labelFont}`,
        color: '#f5f6fa',
      },
    ]

    if (hoveredId && graph?.hasNode(hoveredId)) {
      const filePath = graph.getNodeAttribute(hoveredId, 'filePath') as string
      const nodeType = graph.getNodeAttribute(hoveredId, 'nodeType') as string
      const degree = graph.getNodeAttribute(hoveredId, 'degree') as number
      if (filePath) {
        lines.push({
          text: filePath,
          font: `400 10px ${settings.labelFont}`,
          color: '#9aa2bd',
        })
      }
      lines.push({
        text: `${NODE_TYPE_LABELS[nodeType] ?? nodeType} · ${degree} 连接`,
        font: `400 10px ${settings.labelFont}`,
        color: '#7c84a3',
      })
    }

    const paddingX = 10
    const paddingY = 7
    const lineHeight = 16
    let maxWidth = 0
    for (const line of lines) {
      context.font = line.font
      maxWidth = Math.max(maxWidth, context.measureText(line.text).width)
    }
    const width = maxWidth + paddingX * 2
    const height = lines.length * lineHeight + paddingY * 2

    const x = data.x
    const y = data.y - data.size - height / 2 - 10

    // 深色 pill 背景 + 节点色描边
    context.save()
    context.fillStyle = 'rgba(13, 14, 28, 0.92)'
    context.strokeStyle = data.color
    context.lineWidth = 1.5
    context.beginPath()
    context.roundRect(x - width / 2, y - height / 2, width, height, 6)
    context.fill()
    context.stroke()

    // 逐行文字
    context.textAlign = 'center'
    context.textBaseline = 'middle'
    lines.forEach((line, i) => {
      context.font = line.font
      context.fillStyle = line.color
      context.fillText(
        line.text,
        x,
        y - height / 2 + paddingY + lineHeight * (i + 0.5),
      )
    })

    // 节点光环
    context.beginPath()
    context.arc(data.x, data.y, data.size + 4, 0, Math.PI * 2)
    context.strokeStyle = data.color
    context.lineWidth = 2
    context.globalAlpha = 0.55
    context.stroke()
    context.restore()
  }

  // -------------------------------------------------------------------------
  // FPS 监控
  // -------------------------------------------------------------------------

  function measureFps(): void {
    fpsFrameCount++
    const now = performance.now()
    if (now - fpsLastTime >= 1000) {
      const fps = Math.round((fpsFrameCount * 1000) / (now - fpsLastTime))
      fpsFrameCount = 0
      fpsLastTime = now
      options.onFpsUpdate?.(fps)
    }
    animFrameId = requestAnimationFrame(measureFps)
  }

  function startFpsMonitor(): void {
    if (animFrameId)
      return
    fpsLastTime = performance.now()
    fpsFrameCount = 0
    animFrameId = requestAnimationFrame(measureFps)
  }

  function stopFpsMonitor(): void {
    if (animFrameId) {
      cancelAnimationFrame(animFrameId)
      animFrameId = 0
    }
  }

  // -------------------------------------------------------------------------
  // 布局：FA2 worker 短时精修 + noverlap 收尾
  // -------------------------------------------------------------------------

  function stopLayout(settle = false): void {
    if (layoutTimer) {
      clearTimeout(layoutTimer)
      layoutTimer = null
    }
    if (fa2) {
      fa2.stop()
      fa2.kill()
      fa2 = null
    }
    layoutRunning.value = false

    if (settle && graph && sigma) {
      noverlap.assign(graph, NOVERLAP_SETTINGS)
      sigma.refresh()
      // 布局精修后节点可能外扩，重新 fit 视野
      sigma.getCamera().animatedReset({ duration: 600 })
    }
  }

  function runLayout(): void {
    if (!graph || graph.order < 3)
      return
    stopLayout()

    const inferred = forceAtlas2.inferSettings(graph)
    fa2 = new FA2Layout(graph, {
      settings: {
        ...inferred,
        gravity: 0.6,
        outboundAttractionDistribution: true,
        adjustSizes: true,
        edgeWeightInfluence: 1,
        barnesHutOptimize: graph.order > 200,
      },
    })
    fa2.start()
    layoutRunning.value = true
    layoutTimer = setTimeout(stopLayout, layoutDuration(graph.order), true)
  }

  // -------------------------------------------------------------------------
  // 初始化 / 数据更新
  // -------------------------------------------------------------------------

  function init(container: HTMLElement, initialGraph: GalaxyGraph): void {
    destroy()
    graph = initialGraph

    sigma = new Sigma(initialGraph, container, {
      allowInvalidContainer: true,
      renderLabels: true,
      labelFont: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      labelSize: 11,
      labelWeight: '500',
      labelColor: { color: '#dbe0ee' },
      labelRenderedSizeThreshold: 7,
      labelDensity: 0.08,
      labelGridCellSize: 80,
      defaultNodeColor: '#8b93a7',
      defaultEdgeColor: '#2e3245',
      edgeProgramClasses: { curved: EdgeCurveProgram },
      minCameraRatio: 0.01,
      maxCameraRatio: 30,
      hideEdgesOnMove: true,
      zIndex: true,
      stagePadding: 40,
      defaultDrawNodeHover: drawNodeHover,
      nodeReducer,
      edgeReducer,
    })

    sigma.on('clickNode', ({ node }) => {
      selectedId = node
      rebuildNeighbors()
      sigma?.refresh()
      options.onNodeClick?.(node)
    })

    sigma.on('clickStage', () => {
      if (selectedId) {
        selectedId = null
        rebuildNeighbors()
        sigma?.refresh()
      }
      options.onStageClick?.()
    })

    sigma.on('enterNode', ({ node }) => {
      hoveredId = node
      rebuildNeighbors()
      sigma?.refresh()
      options.onNodeHover?.(node)
      container.style.cursor = 'pointer'
    })

    sigma.on('leaveNode', () => {
      hoveredId = null
      rebuildNeighbors()
      sigma?.refresh()
      options.onNodeHover?.(null)
      container.style.cursor = 'grab'
    })

    container.style.cursor = 'grab'
    startFpsMonitor()
    runLayout()
  }

  function setGraph(nextGraph: GalaxyGraph): void {
    if (!sigma) {
      graph = nextGraph
      return
    }
    stopLayout()
    hoveredId = null
    selectedId = null
    activeNeighbors = new Set()
    graph = nextGraph
    sigma.setGraph(nextGraph)
    sigma.refresh()
    sigma.getCamera().animatedReset({ duration: 0 })
    runLayout()
  }

  // -------------------------------------------------------------------------
  // 外部控制
  // -------------------------------------------------------------------------

  function setVisibleTypes(
    nodeTypes: Set<GalaxyNodeType> | null,
    edgeTypes: Set<GalaxyEdgeType> | null,
  ): void {
    visibleNodeTypes = nodeTypes
    visibleEdgeTypes = edgeTypes
    sigma?.refresh()
  }

  function setSelectedNode(nodeId: string | null): void {
    selectedId = nodeId
    rebuildNeighbors()
    sigma?.refresh()
  }

  function focusNode(nodeId: string): void {
    if (!sigma || !graph?.hasNode(nodeId))
      return
    const display = sigma.getNodeDisplayData(nodeId)
    if (!display)
      return
    const camera = sigma.getCamera()
    camera.animate(
      { x: display.x, y: display.y, ratio: Math.min(camera.ratio, 0.25) },
      { duration: 700 },
    )
  }

  function zoomIn(): void {
    sigma?.getCamera().animatedZoom({ duration: 250 })
  }

  function zoomOut(): void {
    sigma?.getCamera().animatedUnzoom({ duration: 250 })
  }

  function resetCamera(): void {
    sigma?.getCamera().animatedReset({ duration: 500 })
  }

  function destroy(): void {
    stopLayout()
    stopFpsMonitor()
    if (sigma) {
      sigma.kill()
      sigma = null
    }
    graph = null
    hoveredId = null
    selectedId = null
    activeNeighbors = new Set()
  }

  onBeforeUnmount(destroy)

  return {
    layoutRunning,
    init,
    setGraph,
    setVisibleTypes,
    setSelectedNode,
    focusNode,
    zoomIn,
    zoomOut,
    resetCamera,
    runLayout,
    stopLayout,
    destroy,
  }
}
