<script setup lang="ts">
import { Download, Pencil, Play, Redo, Save, Undo } from 'lucide-vue-next'
import { ref } from 'vue'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Switch } from '~/components/ui/switch'
import { Textarea } from '~/components/ui/textarea'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'
import RunningExecutionsBadge from './RunningExecutionsBadge.vue'

const props = defineProps<{
  workflowName?: string
  workflowDescription?: string
  workflowId?: string
  isActive?: boolean
  canUndo?: boolean
  canRedo?: boolean
  saving?: boolean
  hasUnsavedChanges?: boolean
  hasTriggers?: boolean
}>()

const emit = defineEmits<{
  (e: 'save'): void
  (e: 'execute'): void
  (e: 'undo'): void
  (e: 'redo'): void
  (e: 'saveDraft'): void
  (e: 'back'): void
  (e: 'history'): void
  (e: 'exportJSON'): void
  (e: 'update:workflowName', value: string): void
  (e: 'update:workflowDescription', value: string): void
  (e: 'update:isActive', value: boolean): void
}>()

const dialogOpen = ref(false)
const editName = ref('')
const editDescription = ref('')

function openEditDialog() {
  editName.value = props.workflowName ?? ''
  editDescription.value = props.workflowDescription ?? ''
  dialogOpen.value = true
}

function confirmEdit() {
  if (editName.value !== props.workflowName) {
    emit('update:workflowName', editName.value)
  }
  if (editDescription.value !== props.workflowDescription) {
    emit('update:workflowDescription', editDescription.value)
  }
  dialogOpen.value = false
}
</script>

<template>
  <TooltipProvider>
    <div class="h-14 flex items-center gap-4 px-4 mx-3 mt-3 rounded-2xl bg-card/80 backdrop-blur-md border border-border/60 shadow-[0_2px_12px_rgba(15,23,42,0.05)]">
      <!-- Left: Back + Name -->
      <div class="flex items-center gap-3 flex-1 min-w-0">
        <!-- Back button -->
        <Tooltip>
          <TooltipTrigger as-child>
            <Button variant="ghost" size="icon" class="h-8 w-8 flex-shrink-0" @click="emit('back')">
              <span class="icon-[lucide--arrow-left] text-lg" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <p>返回列表</p>
          </TooltipContent>
        </Tooltip>

        <!-- Workflow icon -->
        <div class="flex size-8 items-center justify-center rounded-xl gradient-primary shadow-sm flex-shrink-0">
          <span class="icon-[lucide--workflow] text-base text-white" />
        </div>

        <!-- Name (read-only display) + Edit button -->
        <div class="flex items-center gap-1.5 min-w-0">
          <span class="text-base font-medium text-foreground truncate">
            {{ workflowName || '未命名工作流' }}
          </span>
          <span v-if="workflowDescription" class="text-xs text-muted-foreground truncate max-w-[200px]">
            — {{ workflowDescription }}
          </span>
        </div>

        <!-- Edit dialog trigger -->
        <Dialog v-model:open="dialogOpen">
          <DialogTrigger as-child>
            <Button variant="ghost" size="icon" class="h-7 w-7 flex-shrink-0" @click="openEditDialog">
              <Pencil class="w-3 h-3" />
            </Button>
          </DialogTrigger>
          <DialogContent class="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>编辑工作流信息</DialogTitle>
            </DialogHeader>
            <div class="space-y-4 py-2">
              <div class="space-y-2">
                <Label>名称</Label>
                <Input v-model="editName" placeholder="工作流名称" maxlength="100" />
              </div>
              <div class="space-y-2">
                <Label>描述</Label>
                <Textarea
                  v-model="editDescription"
                  placeholder="工作流的简要描述..."
                  rows="3"
                  maxlength="500"
                  class="resize-none"
                />
              </div>
            </div>
            <DialogFooter>
              <DialogClose as-child>
                <Button variant="outline">
                  取消
                </Button>
              </DialogClose>
              <Button @click="confirmEdit">
                确认
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <!-- Unsaved indicator -->
        <div v-if="hasUnsavedChanges" class="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400 flex-shrink-0">
          <span class="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
          <span class="text-xs font-medium">未保存</span>
        </div>
      </div>

      <!-- Center: Enable toggle -->
      <div class="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-muted/30 border border-border/30">
        <span class="text-xs text-muted-foreground">启用</span>
        <Switch
          :model-value="isActive"
          class="scale-90"
          @update:model-value="emit('update:isActive', $event)"
        />
      </div>

      <!-- Right: Actions -->
      <div class="flex items-center gap-1">
        <!-- Undo/Redo -->
        <Tooltip>
          <TooltipTrigger as-child>
            <Button variant="ghost" size="icon" class="h-8 w-8" :disabled="!canUndo" @click="emit('undo')">
              <Undo class="w-4 h-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <p>撤销</p>
          </TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger as-child>
            <Button variant="ghost" size="icon" class="h-8 w-8" :disabled="!canRedo" @click="emit('redo')">
              <Redo class="w-4 h-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <p>重做</p>
          </TooltipContent>
        </Tooltip>

        <div class="w-px h-5 bg-border/50 mx-1" />

        <!-- Running executions badge -->
        <RunningExecutionsBadge v-if="workflowId" :workflow-id="workflowId" />

        <!-- History -->
        <Tooltip>
          <TooltipTrigger as-child>
            <Button variant="ghost" size="sm" class="h-8" @click="emit('history')">
              <span class="icon-[lucide--history] w-4 h-4 mr-1" />
              <span class="text-xs">历史</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <p>执行历史</p>
          </TooltipContent>
        </Tooltip>

        <div class="w-px h-5 bg-border/50 mx-1" />

        <!-- Export JSON -->
        <Tooltip>
          <TooltipTrigger as-child>
            <Button variant="outline" size="sm" class="h-8" @click="emit('exportJSON')">
              <Download class="w-4 h-4 mr-1.5" />
              导出 JSON
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <p>导出为 JSON</p>
          </TooltipContent>
        </Tooltip>

        <!-- Save Draft -->
        <Button
          v-if="hasUnsavedChanges"
          variant="ghost"
          size="sm"
          class="h-8 text-amber-600 hover:text-amber-600 hover:bg-amber-500/10"
          @click="emit('saveDraft')"
        >
          <span class="icon-[lucide--file-clock] w-4 h-4 mr-1.5" />
          存草稿
        </Button>

        <!-- Save -->
        <Button variant="outline" size="sm" class="h-8" :disabled="saving" @click="emit('save')">
          <Save class="w-4 h-4 mr-1.5" />
          {{ saving ? '保存中...' : '保存' }}
        </Button>

        <!-- Execute -->
        <Tooltip>
          <TooltipTrigger as-child>
            <Button
              size="sm"
              class="h-8 bg-emerald-600 hover:bg-emerald-700 disabled:!pointer-events-auto"
              :disabled="!hasTriggers"
              @click="emit('execute')"
            >
              <Play class="w-4 h-4 mr-1.5" />
              运行
            </Button>
          </TooltipTrigger>
          <TooltipContent v-if="!hasTriggers" side="bottom">
            <p>请先添加一个触发器</p>
          </TooltipContent>
        </Tooltip>
      </div>
    </div>
  </TooltipProvider>
</template>
