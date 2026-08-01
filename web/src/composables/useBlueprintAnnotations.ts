/**
 * 批注层的**单一状态源**（Phase 115-02，UI-SPEC §7.6）。
 *
 * `activeThreadId` 只此一份：正文 `<mark>` 与侧栏线程卡双向同步全靠它。
 * ⛔ 组件内不得各自再持有一份 —— 两份状态必然出现「点侧栏正文不亮」或「两处同时高亮」。
 *
 * 分组 / 计数 / 按 block 归集全部委托 `~/utils/blueprintAnnotations` 的纯函数，
 * 本 composable 只负责把它们接到响应式数据上并管选中态。
 */

import type { Ref } from 'vue'
import type { BlueprintThreadDetail } from '~/types/blueprint'
import { computed, ref } from 'vue'
import {
  annotationCounts,
  groupThreadsByBlock,
  sidebarGroups,
} from '~/utils/blueprintAnnotations'

/**
 * @param threads 端点 ③ `threads/` 的线程（带 `options` 与多轮消息）。
 * @param orphanedThreads 人审快照的 `orphaned_threads`；⭐ 原样传入，⛔ 调用方不要先过滤。
 */
export function useBlueprintAnnotations(
  threads: Ref<BlueprintThreadDetail[]>,
  orphanedThreads?: Ref<BlueprintThreadDetail[] | undefined>,
) {
  const activeThreadId = ref<string | null>(null)

  const groups = computed(() => sidebarGroups(threads.value ?? [], orphanedThreads?.value))
  const threadsByBlock = computed(() => groupThreadsByBlock(threads.value ?? []))
  // ⭐ 未决 BLOCKER 在 `anchored` 过滤之前从全量线程上算（MJ-03），故这里把原始列表也传进去。
  const counts = computed(() => annotationCounts(groups.value, threads.value ?? []))

  /** 侧栏 / 正文点击都走这一个入口，保证选中态只有一处写。 */
  function selectThread(threadId: string | null): void {
    activeThreadId.value = threadId || null
  }

  function clearActive(): void {
    activeThreadId.value = null
  }

  /** 取某条线程（供深链 `?thread=` 与「一个 mark 覆盖多条」的微型 Popover 使用）。 */
  function findThread(threadId: string): BlueprintThreadDetail | undefined {
    return (threads.value ?? []).find(thread => thread.thread_id === threadId)
  }

  return {
    activeThreadId,
    groups,
    threadsByBlock,
    counts,
    selectThread,
    clearActive,
    findThread,
  }
}
