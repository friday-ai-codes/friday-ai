<script setup lang="ts">
/**
 * 知识库「技术方案」tab 面板（Phase 115-06，UI-SPEC §12.1 / §4.2；VIEW-03 / SC-4）。
 *
 * 三条纪律：
 *
 * 1. ⭐ **搜索走「输入值 / 已提交值分离」**：只有回车或点按钮才提交（逐字抄
 *    `pages/knowledge/index.vue:111-135` 的范式）。输入即请求会把每一次击键变成一次全表
 *    icontains 扫描。
 * 2. ⭐ **筛选与分页全部与 URL query 双向同步**，刷新可复现。query 键取 `bp_status` 而非
 *    `status` —— 与既有 `dep_type` 的「模块前缀」命名习惯一致，也避免与知识库将来的通用
 *    `status` 撞名。写回一律用展开写法，`tab` 等其它 query 天然保留。
 * 3. ⭐ **列表项的状态键是 `current_status`**，而**查询参数名**是 `blueprint_status` ——
 *    两者刻意不同名（115-01 订正），⛔ 不要「统一」。
 *
 * 分页体是**五键手写分页**（`{total, items, page, page_size, has_next}`）：过滤发生在 Python
 * 侧而非 queryset 上，DRF 的分页 helper 用不上。
 *
 * ## ⭐ 四档渲染：loading / error / 有数据 / 空（⛔ 不许把 error 并进空态）
 *
 * `isError` 那一档**不可省**（MJ-04）。没有它，400（手改 URL 传了非 UUID 的 `project_id`）、
 * 503（列表聚合失败）与网络断线全都落进 `v-else` 的「没有匹配的技术方案」—— 读失败与真的
 * 没数据在界面上像素级相同，用户只会以为自己筛没了，而不知道该重试。
 */

import type { BlueprintStatus } from '~/types/blueprint'
import { useQuery } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import blueprintsApi from '~/api/blueprints'
import projectsApi from '~/api/projects'
import { repositoriesApi } from '~/api/repositories'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import FilterBar from '~/components/common/FilterBar.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Pagination } from '~/components/ui/pagination'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { Skeleton } from '~/components/ui/skeleton'
import BlueprintListCard from './BlueprintListCard.vue'

/** 「全部」在 `Select` 里必须有一个非空 value（reka-ui 不接受空串 item）。 */
const ALL = '__all__'
const PAGE_SIZE = 12

/** 12 态（含 `''` 旧版方案），逐字对齐 `~/config/blueprintStatus` 的档位。 */
const STATUS_OPTIONS: ReadonlyArray<{ value: string, labelKey: string }> = [
  { value: 'researching', labelKey: 'researching' },
  { value: 'drafting', labelKey: 'drafting' },
  { value: 'ai_reviewing', labelKey: 'ai_reviewing' },
  { value: 'needs_clarification', labelKey: 'needs_clarification' },
  { value: 'pending_review', labelKey: 'pending_review' },
  { value: 'confirmed', labelKey: 'confirmed' },
  { value: 'implementing', labelKey: 'implementing' },
  { value: 'implemented', labelKey: 'implemented' },
  { value: 'archived', labelKey: 'archived' },
  { value: 'failed', labelKey: 'failed' },
  { value: 'superseded', labelKey: 'superseded' },
]

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

function readParam(raw: unknown): string {
  return typeof raw === 'string' && raw ? raw : ''
}

function readPage(raw: unknown): number {
  const value = Number.parseInt(String(raw ?? ''), 10)
  return Number.isFinite(value) && value > 0 ? value : 1
}

const statusFilter = ref(readParam(route.query.bp_status))
const projectFilter = ref(readParam(route.query.project_id))
const repositoryFilter = ref(readParam(route.query.repository_id))
/** ⭐ 输入框当前值与「已提交」查询词分离。 */
const queryInput = ref(readParam(route.query.q))
const submittedQuery = ref(readParam(route.query.q))
const page = ref(readPage(route.query.page))

/** ⭐ 展开写法保留其它 query（`tab` / `view` / `dep_type` …）；空值直接摘掉。 */
function writeQuery(patch: Record<string, string>): void {
  const query: Record<string, string> = { ...(route.query as Record<string, string>), ...patch }
  for (const [key, value] of Object.entries(patch)) {
    if (!value)
      delete query[key]
  }
  router.replace({ query })
}

watch(() => route.query.bp_status, (raw) => {
  const next = readParam(raw)
  if (next !== statusFilter.value)
    statusFilter.value = next
})
watch(() => route.query.project_id, (raw) => {
  const next = readParam(raw)
  if (next !== projectFilter.value)
    projectFilter.value = next
})
watch(() => route.query.repository_id, (raw) => {
  const next = readParam(raw)
  if (next !== repositoryFilter.value)
    repositoryFilter.value = next
})
watch(() => route.query.q, (raw) => {
  const next = readParam(raw)
  if (next !== submittedQuery.value) {
    submittedQuery.value = next
    queryInput.value = next
  }
})
watch(() => route.query.page, (raw) => {
  const next = readPage(raw)
  if (next !== page.value)
    page.value = next
})

function setStatus(value: string): void {
  statusFilter.value = value === ALL ? '' : value
  page.value = 1
  writeQuery({ bp_status: statusFilter.value, page: '' })
}

function setProject(value: string): void {
  projectFilter.value = value === ALL ? '' : value
  page.value = 1
  writeQuery({ project_id: projectFilter.value, page: '' })
}

function setRepository(value: string): void {
  repositoryFilter.value = value === ALL ? '' : value
  page.value = 1
  writeQuery({ repository_id: repositoryFilter.value, page: '' })
}

/** ⭐ 仅回车 / 点按钮才提交。 */
function onSearch(): void {
  submittedQuery.value = queryInput.value.trim()
  page.value = 1
  writeQuery({ q: submittedQuery.value, page: '' })
}

function setPage(value: number): void {
  page.value = value
  writeQuery({ page: value > 1 ? String(value) : '' })
}

const hasActiveFilters = computed(
  () => Boolean(statusFilter.value || projectFilter.value || repositoryFilter.value || submittedQuery.value),
)

function clearFilters(): void {
  statusFilter.value = ''
  projectFilter.value = ''
  repositoryFilter.value = ''
  queryInput.value = ''
  submittedQuery.value = ''
  page.value = 1
  writeQuery({ bp_status: '', project_id: '', repository_id: '', q: '', page: '' })
}

const listQuery = useQuery({
  queryKey: computed(() => [
    'blueprint',
    'list',
    statusFilter.value,
    projectFilter.value,
    repositoryFilter.value,
    submittedQuery.value,
    page.value,
  ]),
  queryFn: () => blueprintsApi.listBlueprints({
    blueprint_status: statusFilter.value || undefined,
    project_id: projectFilter.value || undefined,
    repository_id: repositoryFilter.value || undefined,
    q: submittedQuery.value || undefined,
    page: page.value,
    page_size: PAGE_SIZE,
  }),
  staleTime: 30_000,
})

/** 项目 / 仓库下拉的选项走既有列表端点（⛔ 零新端点）；失败只让下拉为空。 */
const projectsQuery = useQuery({
  queryKey: ['blueprint', 'filter-projects'],
  queryFn: () => projectsApi.list(),
  staleTime: 5 * 60_000,
  retry: false,
})

const repositoriesQuery = useQuery({
  queryKey: ['blueprint', 'filter-repositories'],
  queryFn: () => repositoriesApi.list(),
  staleTime: 5 * 60_000,
  retry: false,
})

const items = computed(() => listQuery.data.value?.items ?? [])
const total = computed(() => listQuery.data.value?.total ?? 0)
const hasNext = computed(() => listQuery.data.value?.has_next ?? false)

function statusLabel(value: string): string {
  return t(`knowledge.blueprints.status.${value}` as `knowledge.blueprints.status.${BlueprintStatus}`)
}
</script>

<template>
  <div class="space-y-4" data-testid="blueprint-tab-panel">
    <FilterBar :show-clear="hasActiveFilters" @clear="clearFilters">
      <div class="relative min-w-[16rem] flex-1">
        <span class="icon-[lucide--search] pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-base text-muted-foreground" />
        <Input
          v-model="queryInput"
          class="h-9 pl-9 text-sm"
          :placeholder="t('knowledge.blueprints.tabPanel.searchPlaceholder')"
          data-testid="blueprint-search-input"
          @keydown.enter="onSearch"
        />
      </div>
      <Button size="sm" class="h-9" data-testid="blueprint-search-button" @click="onSearch">
        {{ t('knowledge.blueprints.tabPanel.search') }}
      </Button>

      <Select :model-value="statusFilter || ALL" @update:model-value="setStatus(String($event ?? ALL))">
        <SelectTrigger class="h-9 w-[10rem]" data-testid="blueprint-filter-status">
          <SelectValue :placeholder="t('knowledge.blueprints.tabPanel.filterStatus')" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem :value="ALL">
            {{ t('knowledge.blueprints.tabPanel.filterAll') }}
          </SelectItem>
          <SelectItem v-for="option in STATUS_OPTIONS" :key="option.value" :value="option.value">
            {{ statusLabel(option.labelKey) }}
          </SelectItem>
        </SelectContent>
      </Select>

      <Select :model-value="projectFilter || ALL" @update:model-value="setProject(String($event ?? ALL))">
        <SelectTrigger class="h-9 w-[11rem]" data-testid="blueprint-filter-project">
          <SelectValue :placeholder="t('knowledge.blueprints.tabPanel.filterProject')" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem :value="ALL">
            {{ t('knowledge.blueprints.tabPanel.filterAll') }}
          </SelectItem>
          <SelectItem v-for="project in projectsQuery.data.value ?? []" :key="project.id" :value="project.id">
            {{ project.name }}
          </SelectItem>
        </SelectContent>
      </Select>

      <Select :model-value="repositoryFilter || ALL" @update:model-value="setRepository(String($event ?? ALL))">
        <SelectTrigger class="h-9 w-[11rem]" data-testid="blueprint-filter-repository">
          <SelectValue :placeholder="t('knowledge.blueprints.tabPanel.filterRepository')" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem :value="ALL">
            {{ t('knowledge.blueprints.tabPanel.filterAll') }}
          </SelectItem>
          <SelectItem v-for="repository in repositoriesQuery.data.value ?? []" :key="repository.id" :value="repository.id">
            {{ repository.name }}
          </SelectItem>
        </SelectContent>
      </Select>
    </FilterBar>

    <div v-if="listQuery.isLoading.value" class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <Skeleton v-for="n in 6" :key="n" class="h-32 w-full rounded-2xl" />
    </div>

    <!--
      ⭐ 读失败与「真的没数据」必须**分档**（MJ-04）：这一档缺席时，400 / 503 / 网络断线
      一律落进下面的 `v-else` 空态，显示成「没有匹配的技术方案」—— 用户会以为自己筛没了，
      而不是「读不到，重试一下」。⚠️ 顺序必须在 `items.length` 之前。
    -->
    <div
      v-else-if="listQuery.isError.value"
      class="flex flex-col items-center gap-3 rounded-2xl border border-border bg-muted/20 px-6 py-10 text-center"
      role="alert"
      data-testid="blueprint-list-error"
    >
      <span class="icon-[lucide--cloud-off] text-2xl text-muted-foreground" aria-hidden="true" />
      <p class="text-sm text-muted-foreground">
        {{ t('knowledge.blueprints.error.unavailable') }}
      </p>
      <Button variant="outline" size="sm" data-testid="blueprint-list-retry" @click="listQuery.refetch()">
        {{ t('knowledge.blueprints.error.retry') }}
      </Button>
    </div>

    <template v-else-if="items.length">
      <p class="text-xs text-muted-foreground">
        {{ t('knowledge.blueprints.tabPanel.resultCount', { total }) }}
      </p>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <BlueprintListCard v-for="item in items" :key="item.artifact_id" :item="item" />
      </div>
      <div v-if="total > PAGE_SIZE || hasNext" class="flex justify-end">
        <Pagination
          :page="page"
          :total="total"
          :items-per-page="PAGE_SIZE"
          :sibling-count="1"
          show-edges
          data-testid="blueprint-pagination"
          @update:page="setPage"
        />
      </div>
    </template>

    <CompactEmptyState
      v-else
      icon="lucide--file-x"
      :title="t('knowledge.blueprints.tabPanel.emptyTitle')"
      :description="t('knowledge.blueprints.tabPanel.emptyBody')"
    />
  </div>
</template>
