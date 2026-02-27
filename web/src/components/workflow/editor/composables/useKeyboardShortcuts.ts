/**
 * useKeyboardShortcuts - 工作流画布键盘快捷键集中管理
 *
 * 快捷键：Delete/Backspace 删除、Ctrl+C 复制、Ctrl+V 粘贴、Ctrl+A 全选
 * 注意：输入框聚焦时不拦截键盘事件（防止在 NodeConfigPanel 输入框中误触）
 */
import type { GraphNode } from '@vue-flow/core'
import { useVueFlow } from '@vue-flow/core'
import { onMounted, onUnmounted, ref } from 'vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { generateShortId } from '~/utils/shortId'
export function useKeyboardShortcuts {
 const store = useWorkflowsStore
 const { getSelectedNodes, addSelectedNodes, getNodes } = useVueFlow
 // 剪贴板状态 -- 存储复制的节点快照
 const clipboard = ref<GraphNode>
 function isInputFocused(event: KeyboardEvent): boolean {
 const target = event.target as HTMLElement
 const tag = target.tagName.toLowerCase
 return tag === 'input' || tag === 'textarea' || tag === 'select' || target.isContentEditable
 }
 function handleKeyDown(event: KeyboardEvent) {
 // 输入框聚焦时不拦截
 if (isInputFocused(event)) return
 const isModifier = event.ctrlKey || event.metaKey
 // Delete / Backspace -> 删除选中节点（直接执行，不弹确认）
 if (event.key === 'Delete' || event.key === 'Backspace') {
 const selected = getSelectedNodes.value
 if (selected.length > 0) {
 event.preventDefault
 selected.forEach(node => store.removeNode(node.id))
 }
 }
 // Ctrl+A -> 全选
 if (isModifier && event.key === 'a') {
 event.preventDefault
 addSelectedNodes(getNodes.value)
 }
 // Ctrl+C -> 复制选中节点到剪贴板
 if (isModifier && event.key === 'c') {
 const selected = getSelectedNodes.value
 if (selected.length > 0) {
 event.preventDefault
 clipboard.value = selected.map(n => JSON.parse(JSON.stringify(n)))
 }
 }
 // Ctrl+V -> 粘贴剪贴板节点
 if (isModifier && event.key === 'v') {
 if (clipboard.value.length > 0) {
 event.preventDefault
 clipboard.value.forEach(copiedNode => {
 const storeNode = store.nodes.find(n => n.id === copiedNode.id)
 // 从 store 节点或剪贴板快照构造新节点
 const source = storeNode ?? copiedNode
 // 优先使用 store 数据（含最新编辑），回退到 VueFlow GraphNode 的 data 字段
 const sourceData = storeNode
 ? JSON.parse(JSON.stringify(storeNode)): {
 ...JSON.parse(JSON.stringify(source.data ?? {})),
 id: source.id,
 nodeType: source.type ?? (source.data as Record<string, unknown>)?.nodeType ?? '',
 name: (source.data as Record<string, unknown>)?.name ?? '',
 description: (source.data as Record<string, unknown>)?.description ?? '',
 config: (source.data as Record<string, unknown>)?.config ?? {},
 timeout: null,
 retryCount: 0,
 retryDelay: 0,
 runCondition: null,
 metadata: {},
 }
 const newNode = {
 ...sourceData,
 id: crypto.randomUUID,
 shortId: generateShortId,
 position: {
 x: (copiedNode.position?.x ?? 0) + 50,
 y: (copiedNode.position?.y ?? 0) + 50,
 },
 }
 if (sourceData.name) {
 newNode.name = `${sourceData.name} (副本)`
 }
 store.addNode(newNode)
 })
 }
 }
 }
 onMounted( => document.addEventListener('keydown', handleKeyDown))
 onUnmounted( => document.removeEventListener('keydown', handleKeyDown))
 return { clipboard }
}
