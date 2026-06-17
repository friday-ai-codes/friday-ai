<script setup lang="ts">
/**
 * /admin/audit — 操作审计查询页（v0.10.0 AUDITUI-02）
 *
 * 路由：unplugin-vue-router 文件系统注册 `/admin/audit`。
 * 守卫：definePage({ meta: { requiresAdmin: true } }) —— 全局导航守卫拦截非 superuser；
 *       后端 IsSuperUser 纵深防御。
 * 只读：仅查询 / 详情 / 导出，无任何编辑/删除入口（呼应 AuditEvent append-only）。
 */
import type { AuditEvent, AuditExportFormat, AuditQuery } from '~/api/audit'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { auditApi } from '~/api/audit'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

definePage({ meta: { requiresAdmin: true } })

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { success } = useToast()

// 与后端 taxonomy.ALL_ACTIONS 对齐的动作选项（下拉过滤）
const ACTION_OPTIONS = [
  'member.created',
  'member.updated',
  'member.deleted',
  'user.activated',
  'user.deactivated',
  'role.changed',
  'project.config_changed',
  'repository.permission_changed',
  'credential.created',
  'credential.updated',
  'credential.deleted',
  'pat.created',
  'pat.revoked',
  'feishu_sync.triggered',
  'exclusion_rule.changed',
  'purge.started',
  'purge.completed',
]
const SOURCE_OPTIONS = ['web', 'api', 'feishu_webhook', 'purge', 'system', 'invitation']
const PAGE_SIZES = [20, 50, 100]

// ==================== 过滤 + 分页状态 ====================
const filters = reactive({
  action: '',
  source: '',
  actor_id: '',
  target_type: '',
  target_id: '',
  occurred_from: '',
  occurred_to: '',
  q: '',
})
const limit = ref(50)
const offset = ref(0)

// 已应用的查询参数（点「查询」才刷新，避免边输入边请求）
const appliedQuery = ref<AuditQuery>({ limit: limit.value, offset: offset.value })

function buildQuery(): AuditQuery {
  const q: AuditQuery = { limit: limit.value, offset: offset.value }
  if (filters.action)
    q.action = filters.action
  if (filters.source)
    q.source = filters.source
  if (filters.actor_id.trim())
    q.actor_id = filters.actor_id.trim()
  if (filters.target_type.trim())
    q.target_type = filters.target_type.trim()
  if (filters.target_id.trim())
    q.target_id = filters.target_id.trim()
  if (filters.occurred_from)
    q.occurred_from = new Date(filters.occurred_from).toISOString()
  if (filters.occurred_to)
    q.occurred_to = new Date(filters.occurred_to).toISOString()
  if (filters.q.trim())
    q.q = filters.q.trim()
  return q
}

function applyFilters() {
  offset.value = 0
  appliedQuery.value = buildQuery()
}

function resetFilters() {
  filters.action = ''
  filters.source = ''
  filters.actor_id = ''
  filters.target_type = ''
  filters.target_id = ''
  filters.occurred_from = ''
  filters.occurred_to = ''
  filters.q = ''
  offset.value = 0
  appliedQuery.value = { limit: limit.value, offset: 0 }
}

const queryKey = computed(() => ['audit-events', appliedQuery.value] as const)
const { data, isLoading, isError } = useQuery({
  queryKey,
  queryFn: () => auditApi.list(appliedQuery.value),
  placeholderData: keepPreviousData,
})

const events = computed<AuditEvent[]>(() => data.value?.items ?? [])
const total = computed(() => data.value?.total ?? 0)
const rangeStart = computed(() => (total.value === 0 ? 0 : offset.value + 1))
const rangeEnd = computed(() => Math.min(offset.value + limit.value, total.value))
const canPrev = computed(() => offset.value > 0)
const canNext = computed(() => offset.value + limit.value < total.value)

function prevPage() {
  if (!canPrev.value)
    return
  offset.value = Math.max(0, offset.value - limit.value)
  appliedQuery.value = { ...appliedQuery.value, offset: offset.value }
}
function nextPage() {
  if (!canNext.value)
    return
  offset.value += limit.value
  appliedQuery.value = { ...appliedQuery.value, offset: offset.value }
}
function changePageSize(size: number) {
  limit.value = size
  offset.value = 0
  appliedQuery.value = { ...buildQuery(), limit: size, offset: 0 }
}

// ==================== 详情弹窗 ====================
const detailOpen = ref(false)
const detailEvent = ref<AuditEvent | null>(null)
function openDetail(ev: AuditEvent) {
  detailEvent.value = ev
  detailOpen.value = true
}
function pretty(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2)
  }
  catch {
    return String(value)
  }
}

// ==================== 导出 ====================
const exporting = ref(false)
async function exportAs(fmt: AuditExportFormat) {
  exporting.value = true
  try {
    await auditApi.exportFile(buildQuery(), fmt)
    success(t('audit.export.success'))
  }
  catch (e) {
    handleError(e, t('audit.export.error'))
  }
  finally {
    exporting.value = false
  }
}

function fmtTime(iso: string): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}
</script>

<template>
  <PageContainer show-background>
    <div class="card overflow-hidden">
      <!-- 页头 -->
      <div class="flex items-center justify-between gap-3 p-6 border-b border-border/50">
        <div class="flex items-center gap-3 min-w-0">
          <div class="p-2.5 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
            <span class="icon-[lucide--shield-check] text-2xl text-primary" />
          </div>
          <div class="min-w-0">
            <h2 class="text-lg font-semibold">
              {{ t('audit.title') }}
            </h2>
            <p class="text-sm text-muted-foreground">
              {{ t('audit.subtitle') }}
            </p>
          </div>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <Button variant="outline" size="sm" :disabled="exporting" @click="exportAs('csv')">
            <span class="icon-[lucide--file-down]" />
            {{ t('audit.export.csv') }}
          </Button>
          <Button variant="outline" size="sm" :disabled="exporting" @click="exportAs('json')">
            <span class="icon-[lucide--braces]" />
            {{ t('audit.export.json') }}
          </Button>
        </div>
      </div>

      <!-- 过滤栏 -->
      <div class="p-6 border-b border-border/50 space-y-4">
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <Label class="text-xs text-muted-foreground mb-1.5 block">{{ t('audit.filters.action') }}</Label>
            <select v-model="filters.action" class="h-9 w-full rounded-lg border border-border/50 bg-background px-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary">
              <option value="">
                {{ t('audit.filters.all') }}
              </option>
              <option v-for="a in ACTION_OPTIONS" :key="a" :value="a">
                {{ a }}
              </option>
            </select>
          </div>
          <div>
            <Label class="text-xs text-muted-foreground mb-1.5 block">{{ t('audit.filters.source') }}</Label>
            <select v-model="filters.source" class="h-9 w-full rounded-lg border border-border/50 bg-background px-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary">
              <option value="">
                {{ t('audit.filters.all') }}
              </option>
              <option v-for="s in SOURCE_OPTIONS" :key="s" :value="s">
                {{ s }}
              </option>
            </select>
          </div>
          <div>
            <Label class="text-xs text-muted-foreground mb-1.5 block">{{ t('audit.filters.targetType') }}</Label>
            <Input v-model="filters.target_type" :placeholder="t('audit.filters.targetTypePlaceholder')" class="bg-background/50" />
          </div>
          <div>
            <Label class="text-xs text-muted-foreground mb-1.5 block">{{ t('audit.filters.q') }}</Label>
            <Input v-model="filters.q" :placeholder="t('audit.filters.qPlaceholder')" class="bg-background/50" />
          </div>
          <div>
            <Label class="text-xs text-muted-foreground mb-1.5 block">{{ t('audit.filters.actorId') }}</Label>
            <Input v-model="filters.actor_id" :placeholder="t('audit.filters.actorIdPlaceholder')" class="bg-background/50" />
          </div>
          <div>
            <Label class="text-xs text-muted-foreground mb-1.5 block">{{ t('audit.filters.targetId') }}</Label>
            <Input v-model="filters.target_id" class="bg-background/50" />
          </div>
          <div>
            <Label class="text-xs text-muted-foreground mb-1.5 block">{{ t('audit.filters.from') }}</Label>
            <Input v-model="filters.occurred_from" type="datetime-local" class="bg-background/50" />
          </div>
          <div>
            <Label class="text-xs text-muted-foreground mb-1.5 block">{{ t('audit.filters.to') }}</Label>
            <Input v-model="filters.occurred_to" type="datetime-local" class="bg-background/50" />
          </div>
        </div>
        <div class="flex items-center gap-2">
          <Button size="sm" @click="applyFilters">
            <span class="icon-[lucide--search]" />
            {{ t('audit.filters.search') }}
          </Button>
          <Button variant="ghost" size="sm" @click="resetFilters">
            {{ t('audit.filters.reset') }}
          </Button>
        </div>
      </div>

      <!-- 列表 -->
      <div class="p-6 space-y-4">
        <div v-if="isLoading" class="text-sm text-muted-foreground">
          <span class="icon-[lucide--loader-2] animate-spin mr-1.5" />
          {{ t('audit.loading') }}
        </div>
        <div v-else-if="isError" class="text-sm text-destructive">
          {{ t('audit.loadError') }}
        </div>
        <div v-else-if="events.length === 0" class="text-sm text-muted-foreground py-8 text-center">
          {{ t('audit.empty') }}
        </div>

        <table v-else class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs text-muted-foreground border-b border-border/50">
              <th class="py-2 pr-3 font-medium">
                {{ t('audit.columns.time') }}
              </th>
              <th class="py-2 pr-3 font-medium">
                {{ t('audit.columns.actor') }}
              </th>
              <th class="py-2 pr-3 font-medium">
                {{ t('audit.columns.action') }}
              </th>
              <th class="py-2 pr-3 font-medium">
                {{ t('audit.columns.target') }}
              </th>
              <th class="py-2 pr-3 font-medium">
                {{ t('audit.columns.source') }}
              </th>
              <th class="py-2 pr-3 font-medium text-right">
                {{ t('audit.columns.detail') }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="ev in events"
              :key="ev.id"
              class="border-b border-border/30 last:border-0 hover:bg-muted/30 cursor-pointer"
              @click="openDetail(ev)"
            >
              <td class="py-2.5 pr-3 whitespace-nowrap text-xs text-muted-foreground">
                {{ fmtTime(ev.occurred_at) }}
              </td>
              <td class="py-2.5 pr-3">
                {{ ev.actor_repr || t('audit.systemActor') }}
              </td>
              <td class="py-2.5 pr-3">
                <Badge variant="outline" class="text-xs font-mono">
                  {{ ev.action }}
                </Badge>
              </td>
              <td class="py-2.5 pr-3 text-muted-foreground">
                <span class="font-mono text-xs">{{ ev.target_type }}</span>
                <span v-if="ev.target_repr"> · {{ ev.target_repr }}</span>
              </td>
              <td class="py-2.5 pr-3">
                <Badge variant="secondary" class="text-xs">
                  {{ ev.source || '—' }}
                </Badge>
              </td>
              <td class="py-2.5 pr-3 text-right">
                <Button variant="ghost" size="sm" @click.stop="openDetail(ev)">
                  <span class="icon-[lucide--eye]" />
                </Button>
              </td>
            </tr>
          </tbody>
        </table>

        <!-- 分页 -->
        <div v-if="events.length > 0" class="flex items-center justify-between gap-3 pt-2">
          <div class="flex items-center gap-2 text-xs text-muted-foreground">
            <span>{{ t('audit.pagination.range', { start: rangeStart, end: rangeEnd, total }) }}</span>
            <select
              :value="limit"
              class="h-7 rounded-md border border-border/50 bg-background px-1 text-xs"
              @change="changePageSize(Number(($event.target as HTMLSelectElement).value))"
            >
              <option v-for="s in PAGE_SIZES" :key="s" :value="s">
                {{ t('audit.pagination.perPage', { size: s }) }}
              </option>
            </select>
          </div>
          <div class="flex items-center gap-1">
            <Button variant="outline" size="sm" :disabled="!canPrev" @click="prevPage">
              <span class="icon-[lucide--chevron-left]" />
              {{ t('audit.pagination.prev') }}
            </Button>
            <Button variant="outline" size="sm" :disabled="!canNext" @click="nextPage">
              {{ t('audit.pagination.next') }}
              <span class="icon-[lucide--chevron-right]" />
            </Button>
          </div>
        </div>
      </div>
    </div>

    <!-- 详情弹窗 -->
    <Dialog v-model:open="detailOpen">
      <DialogContent class="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{{ t('audit.detail.title') }}</DialogTitle>
          <DialogDescription>
            {{ detailEvent?.action }} · {{ fmtTime(detailEvent?.occurred_at ?? '') }}
          </DialogDescription>
        </DialogHeader>
        <div v-if="detailEvent" class="space-y-4 text-sm">
          <div class="grid grid-cols-2 gap-3">
            <div>
              <div class="text-xs text-muted-foreground">
                {{ t('audit.columns.actor') }}
              </div>
              <div>{{ detailEvent.actor_repr || t('audit.systemActor') }}</div>
            </div>
            <div>
              <div class="text-xs text-muted-foreground">
                {{ t('audit.columns.source') }}
              </div>
              <div>{{ detailEvent.source || '—' }}</div>
            </div>
            <div>
              <div class="text-xs text-muted-foreground">
                {{ t('audit.columns.target') }}
              </div>
              <div class="font-mono text-xs">
                {{ detailEvent.target_type }}:{{ detailEvent.target_id }}
              </div>
            </div>
            <div>
              <div class="text-xs text-muted-foreground">
                {{ t('audit.detail.recordedAt') }}
              </div>
              <div>{{ fmtTime(detailEvent.recorded_at) }}</div>
            </div>
          </div>
          <div class="grid sm:grid-cols-2 gap-4">
            <div>
              <div class="text-xs font-medium text-muted-foreground mb-1">
                {{ t('audit.detail.before') }}
              </div>
              <pre class="text-xs bg-muted/40 rounded-lg p-3 overflow-auto max-h-64">{{ pretty(detailEvent.before) }}</pre>
            </div>
            <div>
              <div class="text-xs font-medium text-muted-foreground mb-1">
                {{ t('audit.detail.after') }}
              </div>
              <pre class="text-xs bg-muted/40 rounded-lg p-3 overflow-auto max-h-64">{{ pretty(detailEvent.after) }}</pre>
            </div>
          </div>
          <div>
            <div class="text-xs font-medium text-muted-foreground mb-1">
              {{ t('audit.detail.metadata') }}
            </div>
            <pre class="text-xs bg-muted/40 rounded-lg p-3 overflow-auto max-h-48">{{ pretty(detailEvent.metadata) }}</pre>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  </PageContainer>
</template>
