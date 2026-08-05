/**
 * 蓝图查看器的客户端偏好 Store（Phase 115-02）
 *
 * 职责：只持有查看器的两项**纯客户端偏好** —— 批注侧栏是否折叠、是否显示已关闭批注。
 * 供顶栏工具条、批注侧栏、正文批注层共享。
 *
 * 设计：
 * - 最小 setup store（体例参考 `stores/analyticsFilters.ts`）；
 * - ⛔ **服务端态一律不进本 store**：正文 / 线程 / 人审快照 / 阶段事件 / 版本轨 / 确认门 /
 *   列表全部走 TanStack Query（它管缓存、失效与轮询；再往 Pinia 抄一份必然漂移）。
 * - **持久化：是** —— 与 analog（`analyticsFilters.ts` 明确不持久化）刻意相反。理由：这两项
 *   是**用户偏好**而不是查询语境。「我习惯收起批注栏」「我要看已关闭的批注」应该跨会话
 *   保留；而 analog 那个 `grouping` 是一次查询的参数，切 tab 重置才合语义。
 */

import { useLocalStorage } from '@vueuse/core'
import { defineStore } from 'pinia'

export const useBlueprintViewerStore = defineStore('blueprintViewer', () => {
  const sidebarCollapsed = useLocalStorage<boolean>('blueprint-sidebar-collapsed', false)
  const showClosedAnnotations = useLocalStorage<boolean>('blueprint-show-closed-annotations', false)

  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  return {
    sidebarCollapsed,
    showClosedAnnotations,
    toggleSidebar,
  }
})
