import { useVueFlow } from '@vue-flow/core'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { getNodeDefinition } from '~/types/workflow/registry'
import { generateShortId } from '~/utils/shortId'
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
 timeout: null,
 retryCount: 0,
 retryDelay: 0,
 runCondition: null,
 metadata: {},
 })
 }
 return { onDragOver, onDrop }
}
