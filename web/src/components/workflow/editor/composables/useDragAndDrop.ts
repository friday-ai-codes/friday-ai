import { useVueFlow } from '@vue-flow/core'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { getNodeDefinition } from '~/types/workflow/registry'
import { generateShortId } from '~/utils/shortId'
const RECENT_NODES_KEY = 'friday-recent-nodes'
const MAX_RECENT = 10
/**
 * 记录最近使用的节点类型到 localStorage
 */
function recordRecentNode(nodeType: string): void {
 try {
 const stored = JSON.parse(localStorage.getItem(RECENT_NODES_KEY) ?? '') as string
 const filtered = stored.filter(t => t !== nodeType)
 filtered.unshift(nodeType)
 localStorage.setItem(RECENT_NODES_KEY, JSON.stringify(filtered.slice(0, MAX_RECENT)))
 }
 catch { /* localStorage 不可用时静默失败 */ }
}
/**
 * 获取最近使用的节点类型列表
 */
export function getRecentNodes: string {
 try {
 return JSON.parse(localStorage.getItem(RECENT_NODES_KEY) ?? '') as string
 }
 catch { return }
}
/**
 * 侧边栏拖放到画布的 composable
 *
 * 画布端：监听 dragover/drop 事件，将侧边栏拖来的节点添加到 store。
 */
export function useDragAndDrop {
 const { screenToFlowCoordinate } = useVueFlow
 const store = useWorkflowsStore
 function onDragOver(event: DragEvent) {
 event.preventDefault
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
 store.addNode({
 id: crypto.randomUUID,
 shortId: generateShortId,
 nodeType,
 name: dragName || def?.displayName || nodeType,
 description: '',
 position,
 config: def ? (def.schema.parse({}) as Record<string, unknown>): {},
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
