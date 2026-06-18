<script setup lang="ts">
/**
 * /admin/feedback —— 反馈管理列表（仅超级管理员）。
 *
 * Data-Dense Dashboard 风格：状态语义色徽章、分类图标、行 hover 高亮、骨架屏加载、
 * 友好空状态。守卫：definePage requiresAdmin + 后端 IsSuperUser 纵深防御。
 */
import type { Feedback, FeedbackCategory, FeedbackStatus } from '~/types/feedback'
import { useI18n } from 'vue-i18n'
import { feedbackApi } from '~/api/feedback'
import {
  categoryColorClass,
  categoryIconClass,
  FEEDBACK_CATEGORIES,
  FEEDBACK_STATUSES,
  statusBadgeClass,
  statusDotClass,
} from '~/components/feedback/feedbackStyles'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { Skeleton } from '~/components/ui/skeleton'

definePage({ meta: { requiresAdmin: true, title: '反馈管理' } })

const { t } = useI18n()
const router = useRouter()

const items = ref<Feedback[]>([])
const total = ref(0)
const loading = ref(false)
const limit = 20
const offset = ref(0)

const filters = reactive<{ status: FeedbackStatus | '', category: FeedbackCategory | '' | 'all', search: string }>({
  status: '',
  category: 'all',
  search: '',
})

async function fetchList() {
  loading.value = true
  try {
    const resp = await feedbackApi.adminList({
      status: filters.status || undefined,
      category: (filters.category && filters.category !== 'all' ? filters.category : undefined) as FeedbackCategory | undefined,
      search: filters.search || undefined,
      limit,
      offset: offset.value,
    })
    items.value = resp.items
    total.value = resp.total
  }
  finally {
    loading.value = false
  }
}

function applyFilters() {
  offset.value = 0
  fetchList()
}

function setStatus(status: FeedbackStatus | '') {
  filters.status = status
  applyFilters()
}

function resetFilters() {
  filters.status = ''
  filters.category = 'all'
  filters.search = ''
  applyFilters()
}

const hasActiveFilters = computed(() =>
  filters.status !== '' || filters.category !== 'all' || filters.search !== '',
)

function prevPage() {
  if (offset.value > 0) {
    offset.value = Math.max(0, offset.value - limit)
    fetchList()
  }
}
function nextPage() {
  if (offset.value + limit < total.value) {
    offset.value += limit
    fetchList()
  }
}

function initial(name: string): string {
  return (name?.trim()?.[0] || '?').toUpperCase()
}

onMounted(fetchList)
</script>

<template>
  <PageContainer>
    <!-- 标题 -->
    <div class="mb-5 flex items-end justify-between gap-3">
      <div>
        <h1 class="flex items-center gap-2 text-xl font-semibold tracking-tight">
          <span class="icon-[lucide--message-square-warning] text-primary" />
          {{ t('feedback.admin.title') }}
        </h1>
        <p class="mt-0.5 text-sm text-muted-foreground">
          {{ t('feedback.admin.subtitle') }}
        </p>
      </div>
      <span class="rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground tabular-nums">
        {{ total }}
      </span>
    </div>

    <!-- 筛选条 -->
    <div class="mb-4 rounded-xl border border-border bg-background p-3 shadow-sm">
      <!-- 状态分段筛选 -->
      <div class="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          class="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-sm font-medium transition-colors cursor-pointer"
          :class="filters.status === ''
            ? 'bg-primary text-primary-foreground shadow-sm'
            : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
          @click="setStatus('')"
        >
          {{ t('feedback.admin.all') }}
        </button>
        <button
          v-for="s in FEEDBACK_STATUSES"
          :key="s"
          type="button"
          class="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-sm font-medium transition-colors cursor-pointer"
          :class="filters.status === s
            ? 'bg-primary text-primary-foreground shadow-sm'
            : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
          @click="setStatus(s)"
        >
          <span
            class="h-1.5 w-1.5 rounded-full"
            :class="filters.status === s ? 'bg-current opacity-80' : statusDotClass(s)"
          />
          {{ t(`feedback.status.${s}`) }}
        </button>
      </div>

      <div class="mt-3 flex flex-wrap items-center gap-2 border-t border-border/60 pt-3">
        <Select v-model="filters.category" @update:model-value="applyFilters">
          <SelectTrigger class="h-9 w-40">
            <SelectValue :placeholder="t('feedback.admin.filterCategory')" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">
              {{ t('feedback.admin.all') }}
            </SelectItem>
            <SelectItem v-for="c in FEEDBACK_CATEGORIES" :key="c" :value="c">
              {{ t(`feedback.categories.${c}`) }}
            </SelectItem>
          </SelectContent>
        </Select>

        <div class="relative min-w-[200px] flex-1">
          <span class="icon-[lucide--search] absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            v-model="filters.search"
            :placeholder="t('feedback.admin.searchPlaceholder')"
            class="h-9 pl-8"
            @keydown.enter="applyFilters"
          />
        </div>

        <Button class="h-9" @click="applyFilters">
          {{ t('feedback.admin.search') }}
        </Button>
        <Button v-if="hasActiveFilters" variant="ghost" class="h-9" @click="resetFilters">
          <span class="icon-[lucide--rotate-ccw] mr-1.5 text-sm" />
          {{ t('feedback.admin.reset') }}
        </Button>
      </div>
    </div>

    <!-- 列表 -->
    <div class="overflow-hidden rounded-xl border border-border bg-background shadow-sm">
      <div class="overflow-x-auto">
        <table class="w-full min-w-[680px] text-sm">
          <thead>
            <tr class="border-b border-border bg-muted/40 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <th class="px-4 py-2.5">
                {{ t('feedback.admin.columns.category') }}
              </th>
              <th class="px-4 py-2.5">
                {{ t('feedback.admin.columns.title') }}
              </th>
              <th class="px-4 py-2.5">
                {{ t('feedback.admin.columns.status') }}
              </th>
              <th class="px-4 py-2.5">
                {{ t('feedback.admin.columns.submitter') }}
              </th>
              <th class="px-4 py-2.5 whitespace-nowrap">
                {{ t('feedback.admin.columns.createdAt') }}
              </th>
              <th class="w-8 px-2 py-2.5" />
            </tr>
          </thead>

          <!-- 骨架屏 -->
          <tbody v-if="loading">
            <tr v-for="i in 6" :key="i" class="border-b border-border/60">
              <td class="px-4 py-3">
                <Skeleton class="h-5 w-16 rounded-md" />
              </td>
              <td class="px-4 py-3">
                <Skeleton class="h-4 w-48 rounded" />
              </td>
              <td class="px-4 py-3">
                <Skeleton class="h-5 w-16 rounded-full" />
              </td>
              <td class="px-4 py-3">
                <Skeleton class="h-4 w-20 rounded" />
              </td>
              <td class="px-4 py-3">
                <Skeleton class="h-4 w-28 rounded" />
              </td>
              <td class="px-2 py-3" />
            </tr>
          </tbody>

          <!-- 空状态 -->
          <tbody v-else-if="items.length === 0">
            <tr>
              <td colspan="6">
                <div class="flex flex-col items-center justify-center gap-2 px-4 py-16 text-center">
                  <div class="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
                    <span class="icon-[lucide--inbox] text-2xl text-muted-foreground" />
                  </div>
                  <p class="text-sm font-medium text-foreground">
                    {{ t('feedback.admin.empty') }}
                  </p>
                  <Button v-if="hasActiveFilters" variant="outline" size="sm" class="mt-1" @click="resetFilters">
                    <span class="icon-[lucide--rotate-ccw] mr-1.5 text-sm" />
                    {{ t('feedback.admin.reset') }}
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>

          <!-- 数据行 -->
          <tbody v-else>
            <tr
              v-for="item in items"
              :key="item.id"
              tabindex="0"
              class="group cursor-pointer border-b border-border/60 outline-none transition-colors last:border-0 hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
              @click="router.push(`/admin/feedback/${item.id}`)"
              @keydown.enter="router.push(`/admin/feedback/${item.id}`)"
            >
              <td class="px-4 py-3">
                <span class="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-muted-foreground">
                  <span :class="[categoryIconClass(item.category), categoryColorClass(item.category)]" class="text-sm" />
                  {{ item.category_label }}
                </span>
              </td>
              <td class="max-w-md px-4 py-3">
                <div class="flex items-center gap-2">
                  <span class="truncate font-medium text-foreground">
                    {{ item.title || item.content.slice(0, 48) }}
                  </span>
                  <span
                    v-if="item.replies.length"
                    class="inline-flex shrink-0 items-center gap-0.5 rounded-full bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground"
                  >
                    <span class="icon-[lucide--message-circle]" />{{ item.replies.length }}
                  </span>
                </div>
                <p v-if="item.title" class="mt-0.5 truncate text-xs text-muted-foreground">
                  {{ item.content.slice(0, 60) }}
                </p>
              </td>
              <td class="px-4 py-3">
                <span
                  class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset"
                  :class="statusBadgeClass(item.status)"
                >
                  <span class="h-1.5 w-1.5 rounded-full" :class="statusDotClass(item.status)" />
                  {{ item.status_label }}
                </span>
              </td>
              <td class="px-4 py-3">
                <span class="inline-flex items-center gap-2 text-muted-foreground">
                  <span class="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary">
                    {{ initial(item.created_by_name) }}
                  </span>
                  <span class="max-w-[120px] truncate">{{ item.created_by_name || '—' }}</span>
                </span>
              </td>
              <td class="whitespace-nowrap px-4 py-3 text-muted-foreground tabular-nums">
                {{ new Date(item.created_at).toLocaleString() }}
              </td>
              <td class="px-2 py-3 text-right">
                <span class="icon-[lucide--chevron-right] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 分页 -->
    <div v-if="total > 0" class="mt-3 flex items-center justify-end gap-3 text-sm">
      <span class="text-muted-foreground tabular-nums">
        {{ offset + 1 }}–{{ Math.min(offset + limit, total) }} / {{ total }}
      </span>
      <div class="flex gap-1">
        <Button variant="outline" size="icon" class="h-8 w-8" :disabled="offset === 0" @click="prevPage">
          <span class="icon-[lucide--chevron-left]" />
        </Button>
        <Button variant="outline" size="icon" class="h-8 w-8" :disabled="offset + limit >= total" @click="nextPage">
          <span class="icon-[lucide--chevron-right]" />
        </Button>
      </div>
    </div>
  </PageContainer>
</template>
