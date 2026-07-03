<script setup lang="ts">
import type { ProjectWorkItem } from '~/api/projects'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { projectsApi } from '~/api/projects'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'

const props = defineProps<{ projectId: string, canManage: boolean }>()

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { confirm } = useConfirmDialog()
const { success } = useToast()
const queryClient = useQueryClient()

const projectIdRef = toRef(props, 'projectId')

const { data, isLoading, isError, refetch } = useQuery({
  queryKey: ['project-work-items', projectIdRef],
  queryFn: () => projectsApi.listWorkItems(props.projectId),
})
const items = computed<ProjectWorkItem[]>(() => data.value ?? [])

// 并入表单默认收起（空项目一进来满屏输入框视觉噪声大），点「并入」再展开。
const showAttach = ref(false)
const attachId = ref('')
const attaching = ref(false)

function invalidate() {
  queryClient.invalidateQueries({ queryKey: ['project-work-items', projectIdRef] })
}

function typeBadgeClass(type: string): string {
  return /bug|defect|issue|缺陷/i.test(type)
    ? 'bg-destructive/10 text-destructive'
    : 'bg-sky-500/10 text-sky-600 dark:text-sky-400'
}

async function attach() {
  const id = attachId.value.trim()
  if (!id)
    return
  attaching.value = true
  try {
    await projectsApi.attachWorkItem(props.projectId, id)
    success(t('projects.workItems.attached'))
    attachId.value = ''
    invalidate()
  }
  catch (e: unknown) {
    handleError(e, t('projects.workItems.attachFailed'))
  }
  finally {
    attaching.value = false
  }
}

async function detach(item: ProjectWorkItem) {
  const ok = await confirm({
    title: t('projects.workItems.detachTitle'),
    description: t('projects.workItems.detachConfirm', { title: item.title }),
    confirmText: t('projects.workItems.detachConfirmText'),
    variant: 'destructive',
  })
  if (!ok)
    return
  try {
    await projectsApi.detachWorkItem(props.projectId, item.id)
    success(t('projects.workItems.detached'))
    invalidate()
  }
  catch (e: unknown) {
    handleError(e, t('projects.workItems.detachFailed'))
  }
}
</script>

<template>
  <div class="space-y-3">
    <!-- 手动并入（默认收起，点「并入」展开） -->
    <div
      v-if="canManage && showAttach"
      class="rounded-lg border border-border/60 bg-muted/20 p-3 space-y-2"
      data-testid="attach-work-item-form"
    >
      <div class="flex items-center justify-between gap-2">
        <p class="text-xs text-muted-foreground">
          {{ t('projects.workItems.attachHint') }}
        </p>
        <button
          type="button"
          class="cursor-pointer text-muted-foreground/60 hover:text-foreground transition-colors"
          aria-label="收起并入表单"
          @click="showAttach = false"
        >
          <span class="icon-[lucide--x] text-sm" />
        </button>
      </div>
      <div class="flex gap-2">
        <Input
          v-model="attachId"
          :placeholder="t('projects.workItems.attachPlaceholder')"
          class="h-9 flex-1"
          data-testid="attach-work-item-input"
        />
        <Button :disabled="attaching || !attachId.trim()" size="sm" @click="attach">
          <span class="icon-[lucide--plus] mr-1.5" />
          {{ t('projects.workItems.attach') }}
        </Button>
      </div>
    </div>

    <div v-if="isLoading" class="text-sm text-muted-foreground py-8 text-center">
      {{ t('projects.loading') }}
    </div>
    <div v-else-if="isError" class="py-8 text-center space-y-2">
      <p class="text-sm text-destructive">
        {{ t('projects.workItems.loadError') }}
      </p>
      <button class="text-sm text-primary underline" @click="() => refetch()">
        {{ t('projects.retry') }}
      </button>
    </div>
    <CompactEmptyState
      v-else-if="items.length === 0"
      icon="lucide--list-checks"
      :title="t('projects.workItems.empty')"
    >
      <Button
        v-if="canManage && !showAttach"
        size="sm"
        variant="outline"
        class="h-7 text-xs"
        data-testid="attach-work-item-toggle"
        @click="showAttach = true"
      >
        <span class="icon-[lucide--plus] mr-1" />
        {{ t('projects.workItems.attach') }}
      </Button>
    </CompactEmptyState>

    <template v-else>
      <div v-if="canManage && !showAttach" class="flex justify-end">
        <Button
          size="sm"
          variant="ghost"
          class="h-7 text-xs text-muted-foreground hover:text-primary"
          data-testid="attach-work-item-toggle"
          @click="showAttach = true"
        >
          <span class="icon-[lucide--plus] mr-1" />
          {{ t('projects.workItems.attach') }}
        </Button>
      </div>
    </template>

    <ul v-if="!isLoading && !isError && items.length > 0" class="divide-y divide-border/40 rounded-lg border border-border/40 bg-card">
      <li
        v-for="item in items"
        :key="item.id"
        class="flex items-center justify-between gap-3 px-4 py-3"
        data-testid="work-item-row"
      >
        <div class="min-w-0 space-y-1">
          <div class="flex items-center gap-2">
            <span class="px-1.5 py-0.5 rounded text-xs font-medium" :class="typeBadgeClass(item.work_item_type)">
              {{ item.work_item_type }}
            </span>
            <p class="text-sm font-medium text-foreground truncate">
              {{ item.title || `#${item.feishu_work_item_id}` }}
            </p>
          </div>
          <p class="text-xs text-muted-foreground">
            #{{ item.feishu_work_item_id }} · {{ item.feishu_project_key }}
            · {{ t(`projects.workItems.provenance.${item.provenance}`) }}
          </p>
        </div>
        <button
          v-if="canManage"
          class="text-xs text-muted-foreground hover:text-destructive transition-colors shrink-0"
          :title="t('projects.workItems.detach')"
          @click="detach(item)"
        >
          <span class="icon-[lucide--x] text-base" />
        </button>
      </li>
    </ul>
  </div>
</template>
