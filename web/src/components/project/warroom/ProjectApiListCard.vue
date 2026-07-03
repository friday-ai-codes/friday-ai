<script setup lang="ts">
import type { StateApi, StateApiStatus } from '~/api/projectWorkspace'
import type { BadgeVariants } from '~/components/ui/badge'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, markRaw, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import ApiSchemaEditModal from '~/components/project/warroom/ApiSchemaEditModal.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useModal } from '~/composables/useModal'
import { useToast } from '~/composables/useToast'

// P5：项目结构化 API 清单（DOC-02）就地编辑——成员可增删改，非成员只读。
const props = defineProps<{ projectId: string, canManage?: boolean }>()

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { success } = useToast()
const { confirm } = useConfirmDialog()
const queryClient = useQueryClient()
const projectIdRef = toRef(props, 'projectId')

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

// ── 新增 / 编辑（完整 schema 弹窗）──────────────────────────────
function openEditor(existing: StateApi | null) {
  const { open } = useModal({
    component: markRaw(ApiSchemaEditModal),
    attrs: { projectId: props.projectId, existing },
    onConfirm: () => invalidate(),
  })
  void open()
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
      <Button
        v-if="canManage"
        size="sm"
        variant="outline"
        class="h-7"
        data-testid="api-add-btn"
        @click="openEditor(null)"
      >
        <span class="icon-[lucide--plus] mr-1" />{{ t('projects.warroom.apis.add') }}
      </Button>
    </header>

    <div class="p-5 space-y-3">
      <LoadingState v-if="isLoading" variant="skeleton" :count="2" />

      <div v-else-if="isError" class="py-6 text-center space-y-2">
        <p class="text-sm text-destructive">
          {{ t('projects.warroom.apis.loadError') }}
        </p>
        <button class="text-sm text-primary underline" @click="() => refetch()">
          {{ t('projects.retry') }}
        </button>
      </div>

      <CompactEmptyState
        v-else-if="apis.length === 0"
        icon="lucide--webhook"
        :title="t('projects.warroom.apis.empty')"
      >
        <Button
          v-if="canManage"
          size="sm"
          variant="outline"
          class="h-7 text-xs"
          @click="openEditor(null)"
        >
          <span class="icon-[lucide--plus] mr-1" />
          {{ t('projects.warroom.apis.add') }}
        </Button>
      </CompactEmptyState>

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
          <button
            v-if="canManage"
            type="button"
            class="text-sm text-foreground font-mono truncate flex-1 min-w-0 text-left hover:text-primary transition-colors"
            :title="t('projects.warroom.apis.editDetail')"
            data-testid="api-edit"
            @click="openEditor(api)"
          >
            {{ api.path }}
          </button>
          <span v-else class="text-sm text-foreground font-mono truncate flex-1 min-w-0">{{ api.path }}</span>
          <span
            v-if="(api.request_fields?.length || api.response_fields?.length)"
            class="text-[11px] text-muted-foreground tabular-nums shrink-0"
            :title="t('projects.warroom.apis.fieldCountTitle')"
          >
            {{ t('projects.warroom.apis.fieldCount', { req: api.request_fields?.length || 0, res: api.response_fields?.length || 0 }) }}
          </span>

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
