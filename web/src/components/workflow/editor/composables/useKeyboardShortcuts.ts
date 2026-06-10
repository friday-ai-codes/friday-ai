/**
 * useKeyboardShortcuts - 工作流画布键盘快捷键集中管理
 *
 * 快捷键：Ctrl+C 复制、Ctrl+V 粘贴、Ctrl+A 全选、Ctrl+Z 撤销、Ctrl+Y/Ctrl+Shift+Z 重做、Ctrl+Shift+F fit-view
 * Delete/Backspace 删除由 VueFlow 内置处理，通过 @nodes-change 回写 store。
 * 注意：输入框聚焦时不拦截键盘事件（防止在 NodeConfigPanel 输入框中误触）
 */
import type { GraphNode } from '@vue-flow/core'
import { useVueFlow } from '@vue-flow/core'
import { onMounted, onUnmounted, ref } from 'vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { generateShortId } from '~/utils/shortId'
import { randomUUID } from '~/utils/uuid'

export function useKeyboardShortcuts() {
  const store = useWorkflowsStore()
  const { getSelectedNodes, addSelectedNodes, getNodes, fitView } = useVueFlow()

  // 剪贴板状态 -- 存储复制的节点快照
  const clipboard = ref<GraphNode[]>([])

  function isInputFocused(event: KeyboardEvent): boolean {
    const target = event.target as HTMLElement
    const tag = target.tagName.toLowerCase()
    return tag === 'input' || tag === 'textarea' || tag === 'select' || target.isContentEditable
  }

  function handleKeyDown(event: KeyboardEvent) {
    // 输入框聚焦时不拦截
    if (isInputFocused(event))
      return

    const isModifier = event.ctrlKey || event.metaKey

    // Delete/Backspace 由 VueFlow 内置处理，通过 @nodes-change 回写 store

    // Ctrl+A -> 全选
    if (isModifier && event.key === 'a') {
      event.preventDefault()
      addSelectedNodes(getNodes.value)
    }

    // Ctrl+C -> 复制选中节点到剪贴板
    if (isModifier && event.key === 'c') {
      const selected = getSelectedNodes.value
      if (selected.length > 0) {
        event.preventDefault()
        clipboard.value = selected.map(n => JSON.parse(JSON.stringify(n)))
      }
    }

    // Ctrl+V -> 粘贴剪贴板节点
    if (isModifier && event.key === 'v') {
      if (clipboard.value.length > 0) {
        event.preventDefault()
        clipboard.value.forEach((copiedNode) => {
          const storeNode = store.nodes.find(n => n.id === copiedNode.id)
          // 优先使用 store 数据（含最新编辑），回退到 VueFlow GraphNode 的 data 字段
          const data = copiedNode.data as Record<string, unknown> | undefined
          const sourceData = storeNode
            ? JSON.parse(JSON.stringify(storeNode))
            : {
                id: copiedNode.id,
                nodeType: copiedNode.type ?? data?.nodeType ?? '',
                name: data?.name ?? '',
                description: data?.description ?? '',
                config: data?.config ?? {},
                onError: 'abort',
                retryTimes: 0,
                retryDelay: 5,
                nodeTimeoutSeconds: null,
                fallbackValues: null,
                runCondition: null,
                metadata: {},
              }
          const newNode = {
            ...sourceData,
            id: randomUUID(),
            shortId: generateShortId(),
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

    // Ctrl+Shift+F -> fit-view 带平滑动画
    if (isModifier && event.shiftKey && event.key === 'F') {
      event.preventDefault()
      fitView({ duration: 300 })
    }

    // Ctrl+Z (无 Shift) -> 撤销
    if (isModifier && !event.shiftKey && event.key === 'z') {
      event.preventDefault()
      store.undo()
    }

    // Ctrl+Shift+Z 或 Ctrl+Y -> 重做
    if ((isModifier && event.shiftKey && (event.key === 'Z' || event.key === 'z')) || (isModifier && event.key === 'y')) {
      event.preventDefault()
      store.redo()
    }
  }

  onMounted(() => document.addEventListener('keydown', handleKeyDown))
  onUnmounted(() => document.removeEventListener('keydown', handleKeyDown))

  return { clipboard }
}
