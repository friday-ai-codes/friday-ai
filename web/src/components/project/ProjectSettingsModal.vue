<script setup lang="ts">
import type { Project, ProjectStatus } from '~/api/projects'
import type { Space } from '~/types'
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { VueFinalModal } from 'vue-final-modal'
import { projectsApi } from '~/api/projects'
import spacesApi from '~/api/spaces'
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

// #8 项目配置：改名 / 换空间（rehome）/ 状态流转（归档·终止·恢复）收纳到一处，
// 不再把「归档/终止」裸放在页头。确认任意变更后 emit('confirm') 触发父级 refetch。
const props = defineProps<{ project: Project }>()
const emit = defineEmits<{ confirm: [], cancel: [], closed: [] }>()

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { confirm } = useConfirmDialog()
const { success } = useToast()

const name = ref(props.project.name)
const spaceId = ref(props.project.space_id)
const spaces = ref<Space[]>([])
const saving = ref(false)
const dirtyFromAction = ref(false)

onMounted(async () => {
  try {
    spaces.value = await spacesApi.list()
  }
  catch (e: unknown) {
    handleError(e, '加载空间列表')
  }
})

// 状态流转动作（与既有流转规则一致）。
const STATUS_FLOW: Record<ProjectStatus, { to: ProjectStatus, label: string, variant: 'outline' | 'destructive' }[]> = {
  developing: [
    { to: 'archived', label: '归档项目', variant: 'outline' },
    { to: 'terminated', label: '终止项目', variant: 'destructive' },
  ],
  archived: [
    { to: 'developing', label: '恢复为开发中', variant: 'outline' },
    { to: 'terminated', label: '终止项目', variant: 'destructive' },
  ],
  terminated: [],
}

async function applyTransition(to: ProjectStatus, label: string) {
  const ok = await confirm({
    title: '确认变更项目状态',
    description: `确定要「${label}」吗？`,
    confirmText: '确认',
    variant: to === 'terminated' ? 'destructive' : 'default',
  })
  if (!ok)
    return
  saving.value = true
  try {
    await projectsApi.transition(props.project.id, to)
    success('项目状态已更新')
    dirtyFromAction.value = true
    emit('confirm')
  }
  catch (e: unknown) {
    handleError(e, '变更项目状态失败')
  }
  finally {
    saving.value = false
  }
}

async function handleSave() {
  saving.value = true
  try {
    const trimmed = name.value.trim()
    if (trimmed && trimmed !== props.project.name)
      await projectsApi.update(props.project.id, { name: trimmed })
    if (spaceId.value && spaceId.value !== props.project.space_id)
      await projectsApi.rehome(props.project.id, spaceId.value)
    success('项目配置已保存')
    emit('confirm')
  }
  catch (e: unknown) {
    handleError(e, '保存项目配置失败')
  }
  finally {
    saving.value = false
  }
}
</script>

<template>
  <VueFinalModal
    class="flex justify-center items-center"
    content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-lg w-full mx-4"
    overlay-transition="vfm-fade"
    content-transition="vfm-zoom"
    @closed="emit('closed')"
  >
    <header class="flex items-center gap-2.5 px-5 py-4 border-b border-border/50">
      <span class="inline-flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <span class="icon-[lucide--settings]" />
      </span>
      <h2 class="text-sm font-semibold text-foreground">
        项目配置
      </h2>
    </header>

    <div class="px-5 py-4 space-y-5">
      <!-- 改名 -->
      <div class="space-y-1.5">
        <label class="text-sm font-medium text-foreground">项目名称</label>
        <Input v-model="name" class="h-9" data-testid="settings-name" />
      </div>

      <!-- 换空间 -->
      <div class="space-y-1.5">
        <label class="text-sm font-medium text-foreground">所属空间</label>
        <Select v-model="spaceId">
          <SelectTrigger class="h-9" data-testid="settings-space">
            <SelectValue placeholder="选择空间" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="s in spaces" :key="s.id" :value="s.id">
              {{ s.name }}
            </SelectItem>
          </SelectContent>
        </Select>
        <p class="text-xs text-muted-foreground">
          改归空间会影响该项目可用的仓库池与召回范围。
        </p>
      </div>

      <!-- 状态管理（归档/终止/恢复收纳于此） -->
      <div class="space-y-2 pt-1 border-t border-border/50">
        <label class="text-sm font-medium text-foreground">项目状态</label>
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-xs text-muted-foreground">
            当前：{{ t(`projects.status.${project.status}`) }}
          </span>
          <Button
            v-for="action in STATUS_FLOW[project.status]"
            :key="action.to"
            size="sm"
            :variant="action.variant"
            :disabled="saving"
            :data-testid="`settings-status-${action.to}`"
            @click="applyTransition(action.to, action.label)"
          >
            {{ action.label }}
          </Button>
          <span v-if="STATUS_FLOW[project.status].length === 0" class="text-xs text-muted-foreground/70">
            该状态无可用流转
          </span>
        </div>
      </div>
    </div>

    <footer class="flex items-center justify-end gap-2 px-5 py-4 border-t border-border/50">
      <Button variant="ghost" :disabled="saving" @click="emit('cancel')">
        关闭
      </Button>
      <Button :disabled="saving" data-testid="settings-save" @click="handleSave">
        保存
      </Button>
    </footer>
  </VueFinalModal>
</template>
