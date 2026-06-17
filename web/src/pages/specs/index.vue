<script setup lang="ts">
import type { SddSpec, SddSpecStatus } from '~/api/specs'
import { useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { specsApi } from '~/api/specs'
import EmptyState from '~/components/common/EmptyState.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import SddSpecStatusBadge from '~/components/spec/SddSpecStatusBadge.vue'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'

const { t } = useI18n()
const router = useRouter()

const ALL = '__all__'
const STATUSES: SddSpecStatus[] = ['draft', 'in_review', 'approved', 'implemented', 'archived']

const statusFilter = ref<string>(ALL)
const repositoryFilter = ref<string>(ALL)

const queryParams = computed(() => {
  const params: { status?: SddSpecStatus, repository_id?: string } = {}
  if (statusFilter.value !== ALL)
    params.status = statusFilter.value as SddSpecStatus
  if (repositoryFilter.value !== ALL)
    params.repository_id = repositoryFilter.value
  return params
})

const { data, isLoading, isError } = useQuery({
  queryKey: ['specs', queryParams],
  queryFn: () => specsApi.list(queryParams.value),
})

const specs = computed<SddSpec[]>(() => data.value ?? [])
const isEmpty = computed(() => specs.value.length === 0)
const isFiltered = computed(() => statusFilter.value !== ALL || repositoryFilter.value !== ALL)

// 仓库过滤选项：从当前列表派生（无 specs 的仓库不进入筛选器）。
const repoOptions = computed(() => {
  const map = new Map<string, string>()
  for (const spec of specs.value)
    map.set(spec.repository_id, spec.repository_name)
  return Array.from(map, ([id, name]) => ({ id, name }))
})

const statusLabel = computed(() =>
  statusFilter.value === ALL
    ? t('specs.filter.all')
    : t(`specs.status.${statusFilter.value}`),
)
const repoLabel = computed(() =>
  repositoryFilter.value === ALL
    ? t('specs.filter.all')
    : repoOptions.value.find(r => r.id === repositoryFilter.value)?.name ?? t('specs.filter.all'),
)

function goDetail(id: string) {
  router.push(`/specs/${id}`)
}
</script>

<template>
  <PageContainer>
    <PageHeader
      icon="lucide--file-check-2"
      :title="t('specs.title')"
      :description="t('specs.subtitle')"
    />

    <div class="flex flex-wrap items-center gap-3">
      <Select v-model="statusFilter">
        <SelectTrigger class="w-[160px]" :aria-label="t('specs.filter.status')">
          <span class="icon-[lucide--filter] mr-1.5 text-sm text-muted-foreground" />
          <SelectValue>{{ statusLabel }}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem :value="ALL">
            {{ t('specs.filter.all') }}
          </SelectItem>
          <SelectItem v-for="s in STATUSES" :key="s" :value="s">
            {{ t(`specs.status.${s}`) }}
          </SelectItem>
        </SelectContent>
      </Select>

      <Select v-model="repositoryFilter">
        <SelectTrigger class="w-[200px]" :aria-label="t('specs.filter.repository')">
          <span class="icon-[lucide--git-branch] mr-1.5 text-sm text-muted-foreground" />
          <SelectValue>{{ repoLabel }}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem :value="ALL">
            {{ t('specs.filter.all') }}
          </SelectItem>
          <SelectItem v-for="r in repoOptions" :key="r.id" :value="r.id">
            {{ r.name }}
          </SelectItem>
        </SelectContent>
      </Select>
    </div>

    <LoadingState v-if="isLoading" variant="card" :text="t('specs.loading')" />
    <div v-else-if="isError" class="text-sm text-destructive py-8 text-center">
      {{ t('specs.loadError') }}
    </div>
    <EmptyState
      v-else-if="isEmpty"
      icon="lucide--file-check-2"
      :title="t('specs.empty')"
      :description="isFiltered ? t('specs.emptyFiltered') : t('specs.emptyDescription')"
    />
    <ul v-else class="divide-y divide-border/40 rounded-lg border border-border/40 bg-card">
      <li
        v-for="spec in specs"
        :key="spec.id"
        class="flex items-center justify-between gap-3 px-4 py-3 cursor-pointer hover:bg-muted/40 transition-colors"
        data-testid="spec-row"
        @click="goDetail(spec.id)"
      >
        <div class="min-w-0 space-y-1">
          <p class="text-sm font-medium truncate text-primary">
            {{ spec.work_item?.title || spec.repository_name }}
          </p>
          <p class="text-xs text-muted-foreground truncate">
            {{ spec.repository_name }}
          </p>
        </div>
        <div class="flex items-center gap-3 shrink-0">
          <SddSpecStatusBadge :status="spec.status" />
          <span class="text-xs text-muted-foreground">{{ spec.updated_at }}</span>
        </div>
      </li>
    </ul>
  </PageContainer>
</template>
