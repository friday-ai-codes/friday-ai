<script setup lang="ts">
import { Play, Redo, Save, Undo } from 'lucide-vue-next'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Switch } from '~/components/ui/switch'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
const props = defineProps<{
 workflowName?: string
 isActive?: boolean
 canUndo?: boolean
 canRedo?: boolean
 saving?: boolean
 hasUnsavedChanges?: boolean
}>
const emit = defineEmits<{
 (e: 'save'): void
 (e: 'execute'): void
 (e: 'undo'): void
 (e: 'redo'): void
 (e: 'saveDraft'): void
 (e: 'back'): void
 (e: 'update:workflowName', value: string): void
 (e: 'update:isActive', value: boolean): void
}>
</script>
<template>
 <TooltipProvider>
 <div class=" flex items-center gap-4 px-4 mx-3 mt-3 rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50">
 <!-- Left: Back + Name -->
 <div class="flex items-center gap-3 flex-1 min-w-0">
 <!-- Back button -->
 <Tooltip>
 <TooltipTrigger as-child>
 <Button variant="ghost" size="icon" class=" w-8 flex-shrink-0" @click="emit('back')">
 <span class="icon-[lucide--arrow-left] text-lg" />
 </Button>
 </TooltipTrigger>
 <TooltipContent side="bottom">
 <p>返回列表</p>
 </TooltipContent>
 </Tooltip>
 <!-- Workflow icon -->
 <div class=".5 rounded-lg bg-gradient-to-br from-amber-500/20 to-orange-500/10 flex-shrink-0">
 <span class="icon-[lucide--workflow] text-lg text-amber-500" />
 </div>
 <!-- Editable name -->
 <Input:model-value="workflowName"
 placeholder="工作流名称"
 maxlength="100"
 class=" text-base font-medium bg-transparent border-transparent hover:border-border/50 focus:border-primary/50 max-w-[300px]"
 @update:model-value="emit('update:workflowName', $event as string)"
 />
 <!-- Unsaved indicator -->
 <div v-if="hasUnsavedChanges" class="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400 flex-shrink-0">
 <span class="w-1.5 .5 rounded-full bg-amber-500 animate-pulse" />
 <span class="text-xs font-medium">未保存</span>
 </div>
 </div>
 <!-- Center: Enable toggle -->
 <div class="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-muted/30 border border-border/30">
 <span class="text-xs text-muted-foreground">启用</span>
 <Switch:checked="isActive"
 class="scale-90"
 @update:checked="emit('update:isActive', $event)"
 />
 </div>
 <!-- Right: Actions -->
 <div class="flex items-center gap-1">
 <!-- Undo/Redo -->
 <Tooltip>
 <TooltipTrigger as-child>
 <Button variant="ghost" size="icon" class=" w-8":disabled="!canUndo" @click="emit('undo')">
 <Undo class="w-4 " />
 </Button>
 </TooltipTrigger>
 <TooltipContent side="bottom">
 <p>撤销</p>
 </TooltipContent>
 </Tooltip>
 <Tooltip>
 <TooltipTrigger as-child>
 <Button variant="ghost" size="icon" class=" w-8":disabled="!canRedo" @click="emit('redo')">
 <Redo class="w-4 " />
 </Button>
 </TooltipTrigger>
 <TooltipContent side="bottom">
 <p>重做</p>
 </TooltipContent>
 </Tooltip>
 <div class="w-px bg-border/50 mx-1" />
 <!-- Save Draft -->
 <Button
 v-if="hasUnsavedChanges"
 variant="ghost"
 size="sm"
 class=" text-amber-600 hover:text-amber-600 hover:bg-amber-500/10"
 @click="emit('saveDraft')"
 >
 <span class="icon-[lucide--file-clock] w-4 mr-1.5" />
 存草稿
 </Button>
 <!-- Save -->
 <Button variant="outline" size="sm" class="":disabled="saving" @click="emit('save')">
 <Save class="w-4 mr-1.5" />
 {{ saving ? '保存中...': '保存' }}
 </Button>
 <!-- Execute -->
 <Tooltip>
 <TooltipTrigger as-child>
 <Button
 size="sm"
 class=" bg-emerald-600 hover:bg-emerald-700":disabled="!isActive"
 @click="emit('execute')"
 >
 <Play class="w-4 mr-1.5" />
 运行
 </Button>
 </TooltipTrigger>
 <TooltipContent v-if="!isActive" side="bottom">
 <p>工作流已禁用</p>
 </TooltipContent>
 </Tooltip>
 </div>
 </div>
 </TooltipProvider>
</template>
