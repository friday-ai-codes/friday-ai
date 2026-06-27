/**
 * 拖拽连接态共享 holder（SLOT-03 磁吸视觉态数据源）。
 *
 * 职责：
 * - 用模块级单例响应式状态记录"当前是否在拖拽连线 + 源 handle/shape"，
 *   使 `BaseWorkflowNode`（handle 的 compatible-highlight/forbidden 类）与
 *   `WorkflowCanvas`（connect-start/end + 吸附端点）跨组件共享同一拖拽态，
 *   避免两个 UI 组件互改文件（对齐既有 alignment overlay 单例思路）。
 * - `isCompatibleTarget`：据源 shape 判定任一目标 input handle 是否契约兼容
 *   （compatible-highlight 的数据源），复用 `portShapes` 纯函数。
 *
 * 边界：本 composable 只管"拖拽态 + 兼容判定"，不做 DOM/几何计算
 * （吸附几何归 `usePortSnap.ts`）。纯响应式逻辑、不打日志，安全用于高频拖拽。
 *
 * 合法性：兼容判定仅驱动视觉高亮，最终落点仍经
 * `isValidConnection` + `getValidationError` 双重校验（吸附/高亮不绕过合法性）。
 */
import type { Ref } from 'vue'
import { readonly, ref } from 'vue'
import { arePortShapesCompatible, resolvePortShape } from './portShapes'

interface ConnectSource {
  nodeId: string
  handleId: string
  shape: string | undefined
}

// 模块级单例：跨组件共享同一拖拽态（在 composable 外定义，与 alignment overlay 同范式）。
const dragging = ref(false)
const source = ref<ConnectSource | null>(null)

/**
 * 拖拽连接态 holder。多次调用返回的 `dragging`/`source` 指向同一单例引用，
 * 任一组件 `startConnect`/`endConnect` 对所有消费者即时可见。
 */
export function useConnectionDragState(): {
  dragging: Readonly<Ref<boolean>>
  source: Readonly<Ref<ConnectSource | null>>
  startConnect: (nodeId: string, handleId: string, shape: string | undefined) => void
  endConnect: () => void
  isCompatibleTarget: (targetNodeType: string, targetHandleId: string) => boolean
} {
  /**
   * 拖拽连线开始：记录源 handle 与其 output shape。
   */
  function startConnect(nodeId: string, handleId: string, shape: string | undefined): void {
    dragging.value = true
    source.value = { nodeId, handleId, shape }
  }

  /**
   * 拖拽连线结束（成功/取消统一调用）：清空拖拽态。
   */
  function endConnect(): void {
    dragging.value = false
    source.value = null
  }

  /**
   * 目标 input handle 是否与当前拖拽源契约兼容。
   *
   * - 未拖拽 / 无源 → false（无高亮态）。
   * - 否则解析目标 input shape，按 `arePortShapesCompatible` 判定
   *   （空契约通配：源或目标 shape 为空 → true，零回归命门）。
   */
  function isCompatibleTarget(targetNodeType: string, targetHandleId: string): boolean {
    if (!dragging.value || !source.value)
      return false
    const targetShape = resolvePortShape(targetNodeType, targetHandleId, 'input')
    return arePortShapesCompatible(source.value.shape, targetShape)
  }

  return {
    dragging: readonly(dragging),
    source: readonly(source),
    startConnect,
    endConnect,
    isCompatibleTarget,
  }
}
