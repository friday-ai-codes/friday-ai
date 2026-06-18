<script setup lang="ts">
/**
 * /admin/announcements —— 系统公告管理（仅超级管理员）。
 *
 * 列表（状态筛选 + 搜索 + 分页）+ 新建/编辑/删除 + 按用户已读状态查看。
 * 守卫：definePage requiresAdmin + 后端 IsSuperUser 纵深防御。
 */
import type { AdminAnnouncement, AnnouncementStatus } from '~/types/announcement'
import { useI18n } from 'vue-i18n'
import { announcementsApi } from '~/api/announcements'
import AnnouncementEditorDialog from '~/components/admin/AnnouncementEditorDialog.vue'
import AnnouncementReadStatusDialog from '~/components/admin/AnnouncementReadStatusDialog.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Skeleton } from '~/components/ui/skeleton'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useToast } from '~/composables/useToast'

definePage({ meta: { requiresAdmin: true, title: '系统公告' } })

const { t } = useI18n()
const toast = useToast()
const { confirm } = useConfirmDialog()

const items = ref<AdminAnnouncement[]>([])
const total = ref(0)
const loading = ref(false)
const limit = 20
const offset = ref(0)

const filters = reactive<{ status: AnnouncementStatus | '', search: string }>({
  status: '',
  search: '',
})

const STATUSES: AnnouncementStatus[] = ['draft', 'active', 'archived']

function statusBadgeClass(status: string): string {
  switch (status) {
    case 'active':
      return 'bg-emerald-500/10 text-emerald-600 ring-emerald-500/20 dark:text-emerald-400'
    case 'archived':
      return 'bg-muted text-muted-foreground ring-border'
    default:
      return 'bg-amber-500/10 text-amber-600 ring-amber-500/20 dark:text-amber-400'
  }
}

async function fetchList() {
  loading.value = true
  try {
    const resp = await announcementsApi.adminList({
      status: filters.status || undefined,
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
function setStatus(status: AnnouncementStatus | '') {
  filters.status = status
  applyFilters()
}
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

// 编辑/创建弹窗
const editorOpen = ref(false)
const editing = ref<AdminAnnouncement | null>(null)
function openCreate() {
  editing.value = null
  editorOpen.value = true
}
function openEdit(item: AdminAnnouncement) {
  editing.value = item
  editorOpen.value = true
}

// 已读状态弹窗
const readStatusOpen = ref(false)
const readStatusTarget = ref<AdminAnnouncement | null>(null)
function openReadStatus(item: AdminAnnouncement) {
  readStatusTarget.value = item
  readStatusOpen.value = true
}

async function onDelete(item: AdminAnnouncement) {
  const ok = await confirm({
    title: t('announcements.admin.deleteConfirmTitle'),
    description: t('announcements.admin.deleteConfirmDesc', { title: item.title }),
    variant: 'destructive',
  })
  if (!ok)
    return
  try {
    await announcementsApi.adminDelete(item.id)
    toast.success(t('announcements.admin.deleteSuccess'))
    fetchList()
  }
  catch {
    toast.error(t('announcements.admin.deleteFailed'))
  }
}

/** 快捷发布/归档切换。 */
async function togglePublish(item: AdminAnnouncement) {
  const next: AnnouncementStatus = item.status === 'active' ? 'archived' : 'active'
  try {
    await announcementsApi.adminPatch(item.id, { status: next })
    toast.success(t('announcements.admin.saveSuccess'))
    fetchList()
  }
  catch (e: any) {
    toast.error(e?.detail || t('announcements.admin.saveFailed'))
  }
}

onMounted(fetchList)
</script>

<template>
  <PageContainer>
    <div class="mb-5 flex items-end justify-between gap-3">
      <div>
        <h1 class="flex items-center gap-2 text-xl font-semibold tracking-tight">
          <span class="icon-[lucide--megaphone] text-primary" />
          {{ t('announcements.admin.title') }}
        </h1>
        <p class="mt-0.5 text-sm text-muted-foreground">
          {{ t('announcements.admin.subtitle') }}
        </p>
      </div>
      <Button @click="openCreate">
        <span class="icon-[lucide--plus] mr-1.5" />
        {{ t('announcements.admin.create') }}
      </Button>
    </div>

    <!-- 筛选条 -->
    <div class="mb-4 rounded-xl border border-border bg-background p-3 shadow-sm">
      <div class="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          class="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg px-3 text-sm font-medium transition-colors"
          :class="filters.status === ''
            ? 'bg-primary text-primary-foreground shadow-sm'
            : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
          @click="setStatus('')"
        >
          {{ t('announcements.admin.allStatus') }}
        </button>
        <button
          v-for="s in STATUSES"
          :key="s"
          type="button"
          class="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg px-3 text-sm font-medium transition-colors"
          :class="filters.status === s
            ? 'bg-primary text-primary-foreground shadow-sm'
            : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
          @click="setStatus(s)"
        >
          {{ t(`announcements.status.${s}`) }}
        </button>
        <div class="relative ml-auto min-w-[220px]">
          <span class="icon-[lucide--search] absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            v-model="filters.search"
            :placeholder="t('announcements.admin.searchPlaceholder')"
            class="h-9 pl-8"
            @keydown.enter="applyFilters"
          />
        </div>
        <Button class="h-9" @click="applyFilters">
          {{ t('feedback.admin.search') }}
        </Button>
      </div>
    </div>

    <!-- 列表 -->
    <div class="overflow-hidden rounded-xl border border-border bg-background shadow-sm">
      <div class="overflow-x-auto">
        <table class="w-full min-w-[760px] text-sm">
          <thead>
            <tr class="border-b border-border bg-muted/40 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <th class="px-4 py-2.5">
                {{ t('announcements.admin.columns.title') }}
              </th>
              <th class="px-4 py-2.5">
                {{ t('announcements.admin.columns.status') }}
              </th>
              <th class="px-4 py-2.5">
                {{ t('announcements.admin.columns.audience') }}
              </th>
              <th class="px-4 py-2.5">
                {{ t('announcements.admin.columns.notifyMode') }}
              </th>
              <th class="px-4 py-2.5 whitespace-nowrap">
                {{ t('announcements.admin.columns.createdAt') }}
              </th>
              <th class="px-4 py-2.5 text-right">
                {{ t('announcements.admin.columns.actions') }}
              </th>
            </tr>
          </thead>

          <tbody v-if="loading">
            <tr v-for="i in 5" :key="i" class="border-b border-border/60">
              <td class="px-4 py-3">
                <Skeleton class="h-4 w-48 rounded" />
              </td>
              <td class="px-4 py-3">
                <Skeleton class="h-5 w-16 rounded-full" />
              </td>
              <td class="px-4 py-3">
                <Skeleton class="h-4 w-16 rounded" />
              </td>
              <td class="px-4 py-3">
                <Skeleton class="h-4 w-16 rounded" />
              </td>
              <td class="px-4 py-3">
                <Skeleton class="h-4 w-28 rounded" />
              </td>
              <td class="px-4 py-3">
                <Skeleton class="ml-auto h-7 w-24 rounded" />
              </td>
            </tr>
          </tbody>

          <tbody v-else-if="items.length === 0">
            <tr>
              <td colspan="6">
                <div class="flex flex-col items-center justify-center gap-2 px-4 py-16 text-center">
                  <div class="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
                    <span class="icon-[lucide--megaphone] text-2xl text-muted-foreground" />
                  </div>
                  <p class="text-sm font-medium text-foreground">
                    {{ t('announcements.admin.empty') }}
                  </p>
                  <Button variant="outline" size="sm" class="mt-1" @click="openCreate">
                    <span class="icon-[lucide--plus] mr-1.5" />
                    {{ t('announcements.admin.create') }}
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>

          <tbody v-else>
            <tr
              v-for="item in items"
              :key="item.id"
              class="group border-b border-border/60 transition-colors last:border-0 hover:bg-muted/40"
            >
              <td class="max-w-md px-4 py-3">
                <button class="truncate text-left font-medium text-foreground hover:text-primary" @click="openEdit(item)">
                  {{ item.title }}
                </button>
              </td>
              <td class="px-4 py-3">
                <span
                  class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset"
                  :class="statusBadgeClass(item.status)"
                >
                  {{ t(`announcements.status.${item.status}`) }}
                </span>
              </td>
              <td class="px-4 py-3 text-muted-foreground">
                <span class="inline-flex items-center gap-1">
                  <span :class="item.audience === 'all' ? 'icon-[lucide--users]' : 'icon-[lucide--user-check]'" />
                  {{ item.audience === 'all'
                    ? t('announcements.audience.all')
                    : t('announcements.admin.specificCount', { count: item.target_user_ids.length }) }}
                </span>
              </td>
              <td class="px-4 py-3 text-muted-foreground">
                {{ t(`announcements.notifyMode.${item.notify_mode}`) }}
              </td>
              <td class="whitespace-nowrap px-4 py-3 text-muted-foreground tabular-nums">
                {{ new Date(item.created_at).toLocaleString() }}
              </td>
              <td class="px-4 py-3">
                <div class="flex items-center justify-end gap-1">
                  <Button variant="ghost" size="sm" class="h-7" @click="togglePublish(item)">
                    {{ item.status === 'active' ? t('announcements.admin.archive') : t('announcements.admin.publish') }}
                  </Button>
                  <Button variant="ghost" size="icon" class="h-7 w-7" :title="t('announcements.admin.readStatusTitle')" @click="openReadStatus(item)">
                    <span class="icon-[lucide--bar-chart-2]" />
                  </Button>
                  <Button variant="ghost" size="icon" class="h-7 w-7" :title="t('announcements.admin.edit')" @click="openEdit(item)">
                    <span class="icon-[lucide--pencil]" />
                  </Button>
                  <Button variant="ghost" size="icon" class="h-7 w-7 text-destructive hover:text-destructive" :title="t('announcements.admin.delete')" @click="onDelete(item)">
                    <span class="icon-[lucide--trash-2]" />
                  </Button>
                </div>
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

    <AnnouncementEditorDialog
      v-model:open="editorOpen"
      :announcement="editing"
      @saved="fetchList"
    />
    <AnnouncementReadStatusDialog
      v-model:open="readStatusOpen"
      :announcement="readStatusTarget"
    />
  </PageContainer>
</template>
