<script setup lang="ts">
import type { SystemUser } from '~/types'
/**
 * AnnouncementEditorDialog —— 系统公告创建/编辑弹窗（仅超级管理员）。
 *
 * 标题 + Markdown 正文 + 可选跳转链接 + 状态（草稿/发布/归档）+ 通知模式（弹窗/静默）
 * + 受众（全部用户 / 指定用户，指定时提供带搜索的用户多选）+ 可选展示时间窗口。
 */
import type { AdminAnnouncement, AnnouncementPayload } from '~/types/announcement'
import { useI18n } from 'vue-i18n'
import { announcementsApi } from '~/api/announcements'
import { listUsers } from '~/api/users'
import MarkdownField from '~/components/feedback/MarkdownField.vue'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { useToast } from '~/composables/useToast'

const props = defineProps<{ open: boolean, announcement: AdminAnnouncement | null }>()
const emit = defineEmits<{ 'update:open': [value: boolean], 'saved': [] }>()

const { t } = useI18n()
const toast = useToast()

const isEdit = computed(() => props.announcement != null)

const form = reactive<Required<AnnouncementPayload>>({
  title: '',
  body: '',
  link: '',
  status: 'draft',
  notify_mode: 'popup',
  audience: 'all',
  target_user_ids: [],
  starts_at: null,
  ends_at: null,
})

const saving = ref(false)

// 用户多选（audience=specific）
const users = ref<SystemUser[]>([])
const usersLoading = ref(false)
const userSearch = ref('')
const filteredUsers = computed(() => {
  const q = userSearch.value.trim().toLowerCase()
  if (!q)
    return users.value
  return users.value.filter(u =>
    u.username.toLowerCase().includes(q) || (u.display_name || '').toLowerCase().includes(q),
  )
})
const selectedSet = computed(() => new Set(form.target_user_ids))

async function loadUsers() {
  if (users.value.length > 0)
    return
  usersLoading.value = true
  try {
    users.value = await listUsers()
  }
  catch {
    toast.error(t('announcements.admin.loadUsersFailed'))
  }
  finally {
    usersLoading.value = false
  }
}

function toggleUser(id: string) {
  const idx = form.target_user_ids.indexOf(id)
  if (idx === -1)
    form.target_user_ids.push(id)
  else
    form.target_user_ids.splice(idx, 1)
}

/** datetime-local <-> ISO 互转。 */
function toLocalInput(iso: string | null): string {
  if (!iso)
    return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function fromLocalInput(v: string): string | null {
  return v ? new Date(v).toISOString() : null
}
const startsAtInput = computed({
  get: () => toLocalInput(form.starts_at),
  set: (v: string) => { form.starts_at = fromLocalInput(v) },
})
const endsAtInput = computed({
  get: () => toLocalInput(form.ends_at),
  set: (v: string) => { form.ends_at = fromLocalInput(v) },
})

function resetForm() {
  const a = props.announcement
  form.title = a?.title ?? ''
  form.body = a?.body ?? ''
  form.link = a?.link ?? ''
  form.status = a?.status ?? 'draft'
  form.notify_mode = a?.notify_mode ?? 'popup'
  form.audience = a?.audience ?? 'all'
  form.target_user_ids = [...(a?.target_user_ids ?? [])]
  form.starts_at = a?.starts_at ?? null
  form.ends_at = a?.ends_at ?? null
  userSearch.value = ''
}

watch(() => props.open, (open) => {
  if (open) {
    resetForm()
    if (form.audience === 'specific')
      loadUsers()
  }
})

watch(() => form.audience, (val) => {
  if (val === 'specific')
    loadUsers()
})

async function onSubmit() {
  if (!form.title.trim()) {
    toast.error(t('announcements.admin.titleRequired'))
    return
  }
  if (!form.body.trim()) {
    toast.error(t('announcements.admin.bodyRequired'))
    return
  }
  if (form.audience === 'specific' && form.target_user_ids.length === 0) {
    toast.error(t('announcements.admin.targetRequired'))
    return
  }

  const payload: AnnouncementPayload = {
    title: form.title.trim(),
    body: form.body,
    link: form.link.trim(),
    status: form.status,
    notify_mode: form.notify_mode,
    audience: form.audience,
    target_user_ids: form.audience === 'specific' ? form.target_user_ids : [],
    starts_at: form.starts_at,
    ends_at: form.ends_at,
  }

  saving.value = true
  try {
    if (isEdit.value && props.announcement)
      await announcementsApi.adminUpdate(props.announcement.id, payload)
    else
      await announcementsApi.adminCreate(payload)
    toast.success(t('announcements.admin.saveSuccess'))
    emit('saved')
    emit('update:open', false)
  }
  catch (e: any) {
    toast.error(e?.detail || t('announcements.admin.saveFailed'))
  }
  finally {
    saving.value = false
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="(v) => emit('update:open', v)">
    <DialogContent class="max-h-[90vh] max-w-2xl overflow-y-auto">
      <DialogHeader>
        <DialogTitle>
          {{ isEdit ? t('announcements.admin.editTitle') : t('announcements.admin.createTitle') }}
        </DialogTitle>
      </DialogHeader>

      <div class="space-y-4">
        <!-- 标题 -->
        <div class="space-y-1.5">
          <Label>{{ t('announcements.admin.fields.title') }}</Label>
          <Input v-model="form.title" :placeholder="t('announcements.admin.fields.titlePlaceholder')" />
        </div>

        <!-- 正文 -->
        <div class="space-y-1.5">
          <Label>{{ t('announcements.admin.fields.body') }}</Label>
          <MarkdownField v-model="form.body" :placeholder="t('announcements.admin.fields.bodyPlaceholder')" />
        </div>

        <!-- 跳转链接 -->
        <div class="space-y-1.5">
          <Label>{{ t('announcements.admin.fields.link') }}</Label>
          <Input v-model="form.link" placeholder="/repositories" />
        </div>

        <!-- 状态 + 通知模式 -->
        <div class="grid grid-cols-2 gap-3">
          <div class="space-y-1.5">
            <Label>{{ t('announcements.admin.fields.status') }}</Label>
            <select
              v-model="form.status"
              class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="draft">
                {{ t('announcements.status.draft') }}
              </option>
              <option value="active">
                {{ t('announcements.status.active') }}
              </option>
              <option value="archived">
                {{ t('announcements.status.archived') }}
              </option>
            </select>
          </div>
          <div class="space-y-1.5">
            <Label>{{ t('announcements.admin.fields.notifyMode') }}</Label>
            <select
              v-model="form.notify_mode"
              class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="popup">
                {{ t('announcements.notifyMode.popup') }}
              </option>
              <option value="silent">
                {{ t('announcements.notifyMode.silent') }}
              </option>
            </select>
          </div>
        </div>

        <!-- 受众 -->
        <div class="space-y-1.5">
          <Label>{{ t('announcements.admin.fields.audience') }}</Label>
          <div class="flex gap-2">
            <button
              type="button"
              class="flex-1 cursor-pointer rounded-md border px-3 py-2 text-sm transition-colors"
              :class="form.audience === 'all'
                ? 'border-primary bg-primary/5 text-foreground'
                : 'border-border text-muted-foreground hover:bg-muted'"
              @click="form.audience = 'all'"
            >
              <span class="icon-[lucide--users] mr-1.5" />
              {{ t('announcements.audience.all') }}
            </button>
            <button
              type="button"
              class="flex-1 cursor-pointer rounded-md border px-3 py-2 text-sm transition-colors"
              :class="form.audience === 'specific'
                ? 'border-primary bg-primary/5 text-foreground'
                : 'border-border text-muted-foreground hover:bg-muted'"
              @click="form.audience = 'specific'"
            >
              <span class="icon-[lucide--user-check] mr-1.5" />
              {{ t('announcements.audience.specific') }}
            </button>
          </div>
        </div>

        <!-- 指定用户多选 -->
        <div v-if="form.audience === 'specific'" class="space-y-1.5">
          <div class="flex items-center justify-between">
            <Label>{{ t('announcements.admin.fields.targetUsers') }}</Label>
            <span class="text-xs text-muted-foreground">
              {{ t('announcements.admin.selectedCount', { count: form.target_user_ids.length }) }}
            </span>
          </div>
          <Input v-model="userSearch" :placeholder="t('announcements.admin.searchUser')" class="h-8" />
          <div class="max-h-48 overflow-y-auto rounded-md border border-border">
            <div v-if="usersLoading" class="px-3 py-4 text-center text-sm text-muted-foreground">
              {{ t('notifications.loading') }}
            </div>
            <div v-else-if="filteredUsers.length === 0" class="px-3 py-4 text-center text-sm text-muted-foreground">
              {{ t('announcements.admin.noUser') }}
            </div>
            <label
              v-for="u in filteredUsers"
              v-else
              :key="u.id"
              class="flex cursor-pointer items-center gap-2 border-b border-border/50 px-3 py-2 text-sm last:border-0 hover:bg-muted/50"
            >
              <input
                type="checkbox"
                :checked="selectedSet.has(u.id)"
                class="h-3.5 w-3.5 rounded border-border"
                @change="toggleUser(u.id)"
              >
              <span class="font-medium text-foreground">{{ u.username }}</span>
              <span v-if="u.display_name" class="text-muted-foreground">{{ u.display_name }}</span>
              <span v-if="u.is_superuser" class="ml-auto rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">admin</span>
            </label>
          </div>
        </div>

        <!-- 展示时间窗口 -->
        <div class="grid grid-cols-2 gap-3">
          <div class="space-y-1.5">
            <Label>{{ t('announcements.admin.fields.startsAt') }}</Label>
            <Input v-model="startsAtInput" type="datetime-local" class="h-9" />
          </div>
          <div class="space-y-1.5">
            <Label>{{ t('announcements.admin.fields.endsAt') }}</Label>
            <Input v-model="endsAtInput" type="datetime-local" class="h-9" />
          </div>
        </div>
        <p class="text-xs text-muted-foreground">
          {{ t('announcements.admin.scheduleHint') }}
        </p>
      </div>

      <DialogFooter>
        <Button variant="outline" :disabled="saving" @click="emit('update:open', false)">
          {{ t('announcements.admin.cancel') }}
        </Button>
        <Button :disabled="saving" @click="onSubmit">
          {{ saving ? t('announcements.admin.saving') : t('announcements.admin.save') }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
