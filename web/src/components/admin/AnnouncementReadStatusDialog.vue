<script setup lang="ts">
/**
 * AnnouncementReadStatusDialog —— 公告按用户已读状态查看（仅超级管理员）。
 *
 * 以系统用户为基底，标注是否在受众内（eligible）与已读时间，支持搜索 + 分页。
 */
import type { AdminAnnouncement, AnnouncementReadStatusRow } from '~/types/announcement'
import { useI18n } from 'vue-i18n'
import { announcementsApi } from '~/api/announcements'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'

const props = defineProps<{ open: boolean, announcement: AdminAnnouncement | null }>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()

const { t } = useI18n()

const rows = ref<AnnouncementReadStatusRow[]>([])
const total = ref(0)
const loading = ref(false)
const search = ref('')
const limit = 20
const offset = ref(0)

async function fetchRows() {
  if (!props.announcement)
    return
  loading.value = true
  try {
    const resp = await announcementsApi.adminReadStatus(props.announcement.id, {
      search: search.value || undefined,
      limit,
      offset: offset.value,
    })
    rows.value = resp.items
    total.value = resp.total
  }
  finally {
    loading.value = false
  }
}

function applySearch() {
  offset.value = 0
  fetchRows()
}
function prevPage() {
  if (offset.value > 0) {
    offset.value = Math.max(0, offset.value - limit)
    fetchRows()
  }
}
function nextPage() {
  if (offset.value + limit < total.value) {
    offset.value += limit
    fetchRows()
  }
}

watch(() => props.open, (open) => {
  if (open) {
    search.value = ''
    offset.value = 0
    fetchRows()
  }
})
</script>

<template>
  <Dialog :open="open" @update:open="(v) => emit('update:open', v)">
    <DialogContent class="max-h-[85vh] max-w-2xl overflow-y-auto">
      <DialogHeader>
        <DialogTitle class="truncate">
          {{ t('announcements.admin.readStatusTitle') }} · {{ announcement?.title }}
        </DialogTitle>
      </DialogHeader>

      <div class="mb-3 flex gap-2">
        <Input
          v-model="search"
          :placeholder="t('announcements.admin.searchUser')"
          class="h-9"
          @keydown.enter="applySearch"
        />
        <Button class="h-9" @click="applySearch">
          {{ t('feedback.admin.search') }}
        </Button>
      </div>

      <div class="overflow-hidden rounded-lg border border-border">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-border bg-muted/40 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <th class="px-3 py-2">
                {{ t('announcements.admin.readStatus.user') }}
              </th>
              <th class="px-3 py-2">
                {{ t('announcements.admin.readStatus.eligible') }}
              </th>
              <th class="px-3 py-2">
                {{ t('announcements.admin.readStatus.readAt') }}
              </th>
            </tr>
          </thead>
          <tbody v-if="loading">
            <tr>
              <td colspan="3" class="px-3 py-6 text-center text-muted-foreground">
                {{ t('notifications.loading') }}
              </td>
            </tr>
          </tbody>
          <tbody v-else-if="rows.length === 0">
            <tr>
              <td colspan="3" class="px-3 py-6 text-center text-muted-foreground">
                {{ t('announcements.admin.noUser') }}
              </td>
            </tr>
          </tbody>
          <tbody v-else>
            <tr v-for="r in rows" :key="r.user_id" class="border-b border-border/50 last:border-0">
              <td class="px-3 py-2">
                <span class="font-medium text-foreground">{{ r.username }}</span>
                <span v-if="r.email" class="ml-1 text-xs text-muted-foreground">{{ r.email }}</span>
              </td>
              <td class="px-3 py-2">
                <span
                  v-if="r.eligible"
                  class="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-600 dark:text-emerald-400"
                >
                  <span class="icon-[lucide--check]" />{{ t('announcements.admin.readStatus.inScope') }}
                </span>
                <span v-else class="text-xs text-muted-foreground">—</span>
              </td>
              <td class="px-3 py-2">
                <span v-if="r.read_at" class="text-muted-foreground tabular-nums">
                  {{ new Date(r.read_at).toLocaleString() }}
                </span>
                <span v-else class="inline-flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
                  <span class="icon-[lucide--circle-dot]" />{{ t('announcements.admin.readStatus.unread') }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

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
    </DialogContent>
  </Dialog>
</template>
