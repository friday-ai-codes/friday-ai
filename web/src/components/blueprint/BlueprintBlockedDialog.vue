<script setup lang="ts">
/**
 * approve 409 `blocked` 的「解药面板」（Phase 115-04，UI-SPEC §8.2 / §16 / §20 断言 3）。
 *
 * ⭐ **本组件存在的全部理由：把 `unresolved_blocker_thread_ids` 逐条渲染成可点跳转的
 * 处置入口。** 点一条 = 关闭本弹窗 → 父层打开侧栏 → 选中该线程 → 正文滚动定位，用户由此
 * 走到 `resolve/` / `dismiss/`。
 * ⛔ **只显示一句「不可确认」即视为不合格** —— 那份清单是**超界死锁的唯一解药入口**
 * （114-05 原话）：BLOCKER 未处置时 approve 恒 409，而处置入口只在侧栏里，用户若拿不到
 * 这份清单就只剩「驳回重跑」一条路。
 *
 * ⭐ **条目数必须等于 `threadIds.length`**：`threads` 里查不到的那条**回落显示 id 前 8 位**，
 * ⛔ 绝不因为查不到就跳过 —— 跳过等于让那条 BLOCKER 从用户视野里消失，死锁依旧无解。
 *
 * a11y：severity 不以颜色为唯一载体（`Badge` 带中文 severity 名，§18.3）；
 * `DialogTitle` 必填，这里就用 §16 的那句 blocked 文案本身（全弹窗只有这一句说明）。
 */

import type { BlueprintThreadDetail } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'

const props = withDefaults(defineProps<{
  open: boolean
  /** approve 409 响应体的 `unresolved_blocker_thread_ids`。 */
  threadIds?: string[]
  /** 已取到的线程（用于取摘要）；查不到的条目回落显示 id 前 8 位。 */
  threads?: BlueprintThreadDetail[]
}>(), {
  threadIds: () => [],
  threads: () => [],
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  'goto-thread': [threadId: string]
}>()

const { t } = useI18n()

const SEVERITY_LABEL_KEY: Record<string, string> = {
  'blocker': 'severityBlocker',
  'warning': 'severityWarning',
  'info': 'severityInfo',
  '': 'severityNone',
}

const SEVERITY_VARIANT: Record<string, 'destructive' | 'warning' | 'info' | 'muted'> = {
  'blocker': 'destructive',
  'warning': 'warning',
  'info': 'info',
  '': 'muted',
}

/** finding 首行摘要上限（§8.2「finding 首行摘要」）。 */
const SUMMARY_LIMIT = 40

interface BlockedItem {
  threadId: string
  severity: string
  severityLabel: string
  severityVariant: 'destructive' | 'warning' | 'info' | 'muted'
  summary: string
}

const items = computed<BlockedItem[]>(() =>
  props.threadIds.map((threadId) => {
    const thread = props.threads.find(item => item.thread_id === threadId)
    const severity = thread?.severity ?? 'blocker'
    const body = thread?.messages?.[0]?.body ?? ''
    return {
      threadId,
      severity,
      severityLabel: t(`knowledge.blueprints.thread.${SEVERITY_LABEL_KEY[severity] ?? 'severityNone'}`),
      severityVariant: SEVERITY_VARIANT[severity] ?? 'muted',
      // ⭐ 查不到线程时回落 id 前 8 位，⛔ 不跳过该条。
      summary: body ? body.slice(0, SUMMARY_LIMIT) : threadId.slice(0, 8),
    }
  }),
)

function setOpen(value: boolean): void {
  emit('update:open', value)
}

function gotoThread(threadId: string): void {
  emit('goto-thread', threadId)
  emit('update:open', false)
}
</script>

<template>
  <Dialog :open="open" @update:open="setOpen">
    <DialogContent data-testid="blueprint-blocked-dialog" class="max-w-lg">
      <DialogHeader>
        <DialogTitle>
          {{ t('knowledge.blueprints.error.blocked', { n: threadIds.length }) }}
        </DialogTitle>
      </DialogHeader>

      <ul class="space-y-1.5">
        <li v-for="item in items" :key="item.threadId">
          <button
            type="button"
            data-testid="blueprint-blocked-item"
            :data-thread-id="item.threadId"
            class="flex w-full items-center gap-2 rounded-lg border border-border/60 px-2.5 py-2 text-left transition-colors hover:bg-muted"
            @click="gotoThread(item.threadId)"
          >
            <Badge :variant="item.severityVariant">
              {{ item.severityLabel }}
            </Badge>
            <span class="min-w-0 flex-1 truncate text-xs text-foreground">{{ item.summary }}</span>
            <span class="icon-[lucide--chevron-right] text-muted-foreground" aria-hidden="true" />
          </button>
        </li>
      </ul>
    </DialogContent>
  </Dialog>
</template>
