<script setup lang="ts">
/**
 * 告警阈值规则配置面板（UI-03 §4.2）。
 *
 * 自取数 listAlertRules（vue-query，queryKey 与父页共享缓存避免重复请求）。
 * 规则列表：人读 expr + 级别徽标 + 窗口 / 冷却 + 通道徽标 + 启用 switch（切换即
 * updateAlertRule + invalidate）+ 编辑（打开 dialog）+ 删除（alert-dialog 二次确认）。
 * 任一变更后 invalidate ['obs-alert-rules'] 并 emit changed（父页据此刷新事件表规则筛选选项）。
 */
import type { AlertRule } from '~/api/system'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { deleteAlertRule, listAlertRules, updateAlertRule } from '~/api/system'
import { alertSeverityClass } from '~/components/observability/status'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '~/components/ui/alert-dialog'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Skeleton } from '~/components/ui/skeleton'
import { Switch } from '~/components/ui/switch'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import AlertRuleFormDialog from './AlertRuleFormDialog.vue'

const emit = defineEmits<{
  changed: []
}>()

const { success } = useToast()
const { handleError } = useErrorHandler()
const queryClient = useQueryClient()

const { data, isLoading, isError } = useQuery({
  queryKey: ['obs-alert-rules'],
  queryFn: () => listAlertRules(),
  retry: 1,
})

const rules = computed<AlertRule[]>(() => data.value?.items ?? [])

const OP_SYMBOL: Record<string, string> = { gt: '>', gte: '≥', lt: '<', lte: '≤' }
const METRIC_LABEL: Record<string, string> = {
  qps: 'QPS',
  error_rate: '错误率',
  ttft: 'TTFT',
  cpu: 'CPU',
  memory: '内存',
  db_connections: '数据库连接',
  redis_clients: 'Redis 连接',
  qdrant: 'Qdrant',
  queue_depth: '队列深度',
}
const SEVERITY_LABEL: Record<string, string> = { P0: 'P0', P1: 'P1', P2: 'P2' }

function ruleExpr(r: AlertRule): string {
  return `${METRIC_LABEL[r.metric] ?? r.metric} ${OP_SYMBOL[r.op] ?? r.op} ${r.value}`
}
function ruleDimension(r: AlertRule): string {
  const entries = Object.entries(r.dimension ?? {})
  if (!entries.length)
    return 'overall'
  return entries.map(([k, v]) => `${k}=${v}`).join(' · ')
}

function invalidate() {
  queryClient.invalidateQueries({ queryKey: ['obs-alert-rules'] })
  emit('changed')
}

// ── 新建 / 编辑 dialog ──────────────────────────────────────────────
const dialogOpen = ref(false)
const editingRule = ref<AlertRule | null>(null)

function openCreate() {
  editingRule.value = null
  dialogOpen.value = true
}
function openEdit(rule: AlertRule) {
  editingRule.value = rule
  dialogOpen.value = true
}
function onSaved() {
  invalidate()
}

// ── 启用 / 禁用切换 ─────────────────────────────────────────────────
const togglingId = ref<number | null>(null)
async function onToggle(rule: AlertRule, enabled: boolean) {
  togglingId.value = rule.id
  try {
    await updateAlertRule(rule.id, { enabled })
    success(enabled ? '规则已启用' : '规则已禁用')
    invalidate()
  }
  catch (e) {
    handleError(e, '更新规则')
  }
  finally {
    togglingId.value = null
  }
}

// ── 删除确认 ────────────────────────────────────────────────────────
const deleteOpen = ref(false)
const deletingRule = ref<AlertRule | null>(null)
const deleting = ref(false)

function askDelete(rule: AlertRule) {
  deletingRule.value = rule
  deleteOpen.value = true
}
async function confirmDelete() {
  if (!deletingRule.value)
    return
  deleting.value = true
  try {
    await deleteAlertRule(deletingRule.value.id)
    success('规则已删除')
    deleteOpen.value = false
    invalidate()
  }
  catch (e) {
    handleError(e, '删除规则')
  }
  finally {
    deleting.value = false
  }
}
</script>

<template>
  <section class="rounded-xl border border-border/60 bg-card">
    <header class="flex items-center justify-between gap-3 border-b border-border/50 p-4">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--shield-alert] text-lg text-primary" />
        <div>
          <h2 class="text-sm font-semibold">
            阈值规则
          </h2>
          <p class="text-xs text-muted-foreground">
            配置 CPU / 错误率 / TTFT / 队列深等触发条件与通知
          </p>
        </div>
      </div>
      <Button size="sm" aria-label="新建规则" @click="openCreate">
        <span class="icon-[lucide--plus]" />
        新建规则
      </Button>
    </header>

    <div class="p-4">
      <!-- 骨架 -->
      <div v-if="isLoading && !rules.length" class="space-y-2">
        <Skeleton v-for="i in 3" :key="i" class="h-14 w-full rounded-lg" />
      </div>

      <!-- 错误 -->
      <p v-else-if="isError" class="py-8 text-center text-sm text-destructive">
        <span class="icon-[lucide--circle-alert] mr-1.5 align-middle" />
        加载规则失败
      </p>

      <!-- 空态 -->
      <div v-else-if="!rules.length" class="py-10 text-center">
        <span class="icon-[lucide--shield-off] mb-2 block text-2xl text-muted-foreground opacity-60" />
        <p class="text-sm text-muted-foreground">
          还没有任何告警规则
        </p>
        <Button size="sm" variant="outline" class="mt-3" @click="openCreate">
          <span class="icon-[lucide--plus]" />
          创建第一条规则
        </Button>
      </div>

      <!-- 规则列表 -->
      <ul v-else class="space-y-2">
        <li
          v-for="rule in rules"
          :key="rule.id"
          class="flex flex-wrap items-center gap-3 rounded-lg border border-border/50 p-3 transition-colors hover:bg-muted/30"
        >
          <span
            class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold"
            :class="alertSeverityClass(rule.severity)"
          >{{ SEVERITY_LABEL[rule.severity] ?? rule.severity }}</span>

          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="truncate text-sm font-medium">{{ rule.name }}</span>
              <span class="font-mono text-xs text-muted-foreground tabular-nums">{{ ruleExpr(rule) }}</span>
            </div>
            <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span class="tabular-nums">窗口 {{ rule.window }}s · 冷却 {{ rule.cooldown }}s</span>
              <span class="font-mono">{{ ruleDimension(rule) }}</span>
              <span v-if="rule.channels.length" class="flex items-center gap-1">
                <Badge v-for="ch in rule.channels" :key="ch" variant="muted" class="text-[10px]">
                  {{ ch }}
                </Badge>
              </span>
            </div>
          </div>

          <div class="flex items-center gap-1.5">
            <Switch
              :model-value="rule.enabled"
              :disabled="togglingId === rule.id"
              :aria-label="rule.enabled ? '禁用规则' : '启用规则'"
              @update:model-value="(v: boolean) => onToggle(rule, v)"
            />
            <Button variant="ghost" size="icon-sm" aria-label="编辑规则" @click="openEdit(rule)">
              <span class="icon-[lucide--pencil]" />
            </Button>
            <Button variant="ghost" size="icon-sm" aria-label="删除规则" @click="askDelete(rule)">
              <span class="icon-[lucide--trash-2] text-destructive" />
            </Button>
          </div>
        </li>
      </ul>
    </div>

    <!-- 新建 / 编辑 dialog -->
    <AlertRuleFormDialog v-model:open="dialogOpen" :rule="editingRule" @saved="onSaved" />

    <!-- 删除二次确认 -->
    <AlertDialog v-model:open="deleteOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>删除告警规则</AlertDialogTitle>
          <AlertDialogDescription>
            确定删除规则「{{ deletingRule?.name }}」？此操作不可逆，删除后将停止其告警评估。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel :disabled="deleting">
            取消
          </AlertDialogCancel>
          <AlertDialogAction :disabled="deleting" @click="confirmDelete">
            <span v-if="deleting" class="icon-[lucide--loader-2] mr-1.5 animate-spin" />
            删除
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </section>
</template>
