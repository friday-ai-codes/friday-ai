import { useVueFlow } from '@vue-flow/core'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { getNodeDefinition } from '~/types/workflow/registry'
import { generateEndpointToken } from '~/utils/endpointToken'
import { generateShortId } from '~/utils/shortId'
import { randomUUID } from '~/utils/uuid'

const RECENT_NODES_KEY = 'friday-recent-nodes'
const MAX_RECENT = 10

/**
 * 记录最近使用的节点类型到 localStorage
 */
function recordRecentNode(nodeType: string): void {
  try {
    const parsed = JSON.parse(localStorage.getItem(RECENT_NODES_KEY) ?? '[]')
    const stored = Array.isArray(parsed) && parsed.every(t => typeof t === 'string') ? parsed : []
    const filtered = stored.filter((t: string) => t !== nodeType)
    filtered.unshift(nodeType)
    localStorage.setItem(RECENT_NODES_KEY, JSON.stringify(filtered.slice(0, MAX_RECENT)))
    // 触发自定义事件通知 NodePalette 刷新
    window.dispatchEvent(new CustomEvent('friday:recent-nodes-changed'))
  }
  catch { /* localStorage 不可用时静默失败 */ }
}

/**
 * 获取最近使用的节点类型列表
 */
export function getRecentNodes(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(RECENT_NODES_KEY) ?? '[]')
    return Array.isArray(parsed) && parsed.every(t => typeof t === 'string') ? parsed : []
  }
  catch { return [] }
}

/**
 * 侧边栏拖放到画布的 composable。
 *
 * 画布端：监听 dragover/drop 事件，将侧边栏拖来的节点添加到 store。
 * 注：边中插入节点改由边中点 "+" 按钮承担（GradientEdge + NodeInsertMenu），
 * 旧的「拖到连线上按直线距离命中并插入」逻辑（曲线对不准）已移除。
 */
export function useDragAndDrop() {
  const { screenToFlowCoordinate } = useVueFlow()
  const store = useWorkflowsStore()

  function onDragOver(event: DragEvent) {
    event.preventDefault()
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = 'move'
    }
  }

  function onDrop(event: DragEvent) {
    const nodeType = event.dataTransfer?.getData('application/vueflow')
    if (!nodeType)
      return

    const position = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
    const def = getNodeDefinition(nodeType)
    const dragName = event.dataTransfer?.getData('application/vueflow-name')

    // 拖入即时生成节点默认配置；飞书事件触发节点客户端先生成专属端点 token，
    // 这样一拖进画布就能展示端点 URL，无需等保存（后端同步时校验并采纳该 token）。
    const config: Record<string, unknown> = { ...((def?.defaultConfig as Record<string, unknown>) ?? {}) }
    if (nodeType === 'feishu_event_trigger') {
      if (!config.endpoint_token)
        config.endpoint_token = generateEndpointToken()
      // 节点专属校验 token：拖入即生成，飞书规则需随请求发送，webhook 比对后才触发
      if (!config.verification_token)
        config.verification_token = generateEndpointToken()
    }

    store.addNode({
      id: randomUUID(),
      shortId: generateShortId(),
      nodeType,
      name: dragName || def?.displayName || nodeType,
      description: '',
      position,
      config,
      onError: 'abort',
      retryTimes: 0,
      retryDelay: 5,
      nodeTimeoutSeconds: null,
      fallbackValues: null,
      runCondition: null,
      metadata: {},
    })

    recordRecentNode(nodeType)
  }

  return { onDragOver, onDrop }
}
