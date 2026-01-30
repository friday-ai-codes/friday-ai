<script setup lang="ts">
import { Play, Redo, Save, Settings, Undo } from 'lucide-vue-next'
import { Button } from '~/components/ui/button'
defineProps<{
 canUndo?: boolean
 canRedo?: boolean
 saving?: boolean
 hasUnsavedChanges?: boolean
}>
const emit = defineEmits(['save', 'execute', 'undo', 'redo', 'settings', 'saveDraft'])
</script>
<template>
 <div class=" flex items-center justify-between px-4 mx-3 mt-3 rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50">
 <div class="flex items-center space-x-1">
 <Button variant="ghost" size="icon" class="hover:bg-muted/50":disabled="!canUndo" @click="emit('undo')">
 <Undo class="w-4 " />
 </Button>
 <Button variant="ghost" size="icon" class="hover:bg-muted/50":disabled="!canRedo" @click="emit('redo')">
 <Redo class="w-4 " />
 </Button>
 <!-- Unsaved changes indicator -->
 <div v-if="hasUnsavedChanges" class="flex items-center gap-1.5 ml-2 px-2 py-1 rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400">
 <span class="w-1.5 .5 rounded-full bg-amber-500 animate-pulse" />
 <span class="text-xs font-medium">未保存</span>
 </div>
 </div>
 <div class="flex items-center space-x-2">
 <Button variant="ghost" size="sm" class="hover:bg-muted/50" @click="emit('settings')">
 <Settings class="w-4 mr-2" />
 设置
 </Button>
 <Button variant="outline" size="sm" class="border-border/50 hover:border-emerald-500/50 hover:text-emerald-500" @click="emit('execute')">
 <Play class="w-4 mr-2" />
 运行
 </Button>
 <Button
 v-if="hasUnsavedChanges"
 variant="outline"
 size="sm"
 class="border-border/50 hover:border-amber-500/50 hover:text-amber-500"
 @click="emit('saveDraft')"
 >
 <span class="icon-[lucide--file-clock] w-4 mr-2" />
 存草稿
 </Button>
 <Button size="sm" class="group relative overflow-hidden":disabled="saving" @click="emit('save')">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <Save class="w-4 mr-2" />
 {{ saving ? '保存中...': '保存' }}
 </Button>
 </div>
 </div>
</template>
