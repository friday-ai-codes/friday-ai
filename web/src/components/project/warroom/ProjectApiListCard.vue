<script setup lang="ts">
import type { StateApi, StateApiStatus } from '~/api/projectWorkspace'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import LoadingState from '~/components/common/LoadingState.vue'
import { Badge, type BadgeVariants } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

// P5：项目结构化 API 清单（DOC-02）就地编辑——成员可增删改，非成员只读。
const props = defineProps<{ projectId: string, canManage?: boolean }>()

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { success } = useToast()
const { confirm } = useConfirmDialog()
const queryClient = useQueryClient()
const projectIdRef = toRef(props, 'projectId')

const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']
const STATUSES: StateApiStatus[] = ['planned', 'in_progress', 'done']

const { data, isLoading, isError, refetch } = useQuery({
  queryKey: ['project-state-apis', projectIdRef],
  queryFn: () => projectWorkspaceApi.listStateApis(props.projectId),
})
const apis = computed<StateApi[]>(() => data.value ?? [])

function invalidate() {
  queryClient.invalidateQueries({ queryKey: ['project-state-apis', projectIdRef] })
}

function apiStatusVariant(status: string): BadgeVariants['variant'] {
  switch (status) {
    case 'in_progress':
      return 'info'
    case 'done':
      return 'success'
    default:
      return 'muted'
  }
}

// ── 新增 ─────────────────────────────────────────────────────
const draftMethod = ref('GET')
const draftPath = ref('')
const draftStatus = ref<StateApiStatus>('planned')

const addMutation = useMutation({
  mutationFn: () => projectWorkspaceApi.upsertStateApi(props.projectId, {
    method: draftMethod.value,
    path: draftPath.value.trim(),
    status: draftStatus.value,
  }),
  onSuccess: () => {
    success(t('projects.warroom.apis.added'))
    draftPath.value = ''
    invalidate()
  },
  onError: (e: unknown) => handleError(e, t('projects.warroom.apis.addFailed')),
})

function add() {
  if (!draftPath.value.trim() || addMutation.isPending.value)
    return
  addMutation.mutate()
}

const patchMutation = useMutation({
  mutationFn: (vars: { id: string, status: StateApiStatus }) =>
    projectWorkspaceApi.patchStateApi(props.projectId, vars.id, { status: vars.status }),
  onSuccess: () => invalidate(),
  onError: (e: unknown) => handleError(e, t('projects.warroom.apis.updateFailed')),
})

async function removeApi(api: StateApi) {
  const ok = await confirm({
    title: t('projects.warroom.apis.deleteTitle'),
    description: `${api.method} ${api.path}`,
    confirmText: t('projects.warroom.apis.confirmDelete'),
    variant: 'destructive',
  })
  if (!ok)
    return
  try {
    await projectWorkspaceApi.deleteStateApi(props.projectId, api.id)
    success(t('projects.warroom.apis.deleted'))
    invalidate()
  }
  catch (e: unknown) {
    handleError(e, t('projects.warroom.apis.deleteFailed'))
  }
}
</script>

<template>
  <section class="card" data-testid="warroom-api-list-card">
    <header class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2.5">
      <span class="section-chip"><span class="icon-[lucide--webhook]" /></span>
      <h2 class="text-sm font-semibold text-foreground">
        {{ t('projects.warroom.apis.title') }}
      </h2>
      <span class="ml-auto text-xs text-muted-foreground tabular-nums">{{ apis.length }}</span>
    </header>

    <div class="p-5 space-y-3">
      <!-- 新增表单（仅成员） -->
      <div v-if="canManage" class="flex flex-wrap items-center gap-2" data-testid="api-add-form">
        <Select v-model="draftMethod">
          <SelectTrigger class="h-8 w-24 text-xs" :aria-label="t('projects.warroom.apis.methodLabel')">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="m in METHODS" :key="m" :value="m">
              {{ m }}
            </SelectItem>
          </SelectContent>
        </Select>
        <Input
          v-model="draftPath"
          class="h-8 flex-1 min-w-40 text-xs"
          :placeholder="t('projects.warroom.apis.pathPlaceholder')"
          :aria-label="t('projects.warroom.apis.pathLabel')"
          spellcheck="false"
          autocomplete="off"
          data-testid="api-add-path"
          @keydown.enter="add"
        />
        <Select v-model="draftStatus">
          <SelectTrigger class="h-8 w-28 text-xs" :aria-label="t('projects.warroom.apis.statusLabel')">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="st in STATUSES" :key="st" :value="st">
              {{ t(`projects.warroom.apis.status.${st}`) }}
            </SelectItem>
          </SelectContent>
        </Select>
        <Button size="sm" :disabled="!draftPath.trim() || addMutation.isPending.value" data-testid="api-add-btn" @click="add">
          <span class="icon-[lucide--plus] mr-1" />{{ t('projects.warroom.apis.add') }}
        </Button>
      </div>

      <LoadingState v-if="isLoading" variant="skeleton" :count="2" />

      <div v-else-if="isError" class="py-6 text-center space-y-2">
        <p class="text-sm text-destructive">
          {{ t('projects.warroom.apis.loadError') }}
        </p>
        <button class="text-sm text-primary underline" @click="() => refetch()">
          {{ t('projects.retry') }}
        </button>
      </div>

      <p v-else-if="apis.length === 0" class="py-6 text-center text-sm text-muted-foreground">
        {{ t('projects.warroom.apis.empty') }}
      </p>

      <ul v-else class="divide-y divide-border/40">
        <li
          v-for="api in apis"
          :key="api.id"
          class="flex items-center gap-2 py-2"
          data-testid="api-row"
        >
          <span class="text-[11px] font-mono font-semibold px-1.5 py-0.5 rounded bg-muted text-muted-foreground shrink-0">
            {{ api.method }}
          </span>
          <span class="text-sm text-foreground font-mono truncate flex-1 min-w-0">{{ api.path }}</span>

          <Select
            v-if="canManage"
            :model-value="api.status"
            @update:model-value="(v) => patchMutation.mutate({ id: api.id, status: v as StateApiStatus })"
          >
            <SelectTrigger class="h-7 w-28 text-xs shrink-0" :aria-label="t('projects.warroom.apis.statusLabel')">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="st in STATUSES" :key="st" :value="st">
                {{ t(`projects.warroom.apis.status.${st}`) }}
              </SelectItem>
            </SelectContent>
          </Select>
          <Badge v-else :variant="apiStatusVariant(api.status)" class="shrink-0">
            {{ t(`projects.warroom.apis.status.${api.status}`) }}
          </Badge>

          <button
            v-if="canManage"
            class="text-muted-foreground hover:text-destructive shrink-0"
            :aria-label="t('projects.warroom.apis.delete')"
            data-testid="api-delete"
            @click="removeApi(api)"
          >
            <span class="icon-[lucide--trash-2] text-sm" />
          </button>
        </li>
      </ul>
    </div>
  </section>
</template>
