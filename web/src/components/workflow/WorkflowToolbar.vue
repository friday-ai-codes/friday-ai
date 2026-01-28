<script setup lang="ts">
import { Play, Redo, Save, Settings, Undo } from 'lucide-vue-next'
import { Button } from '~/components/ui/button'
defineProps<{
 canUndo?: boolean
 canRedo?: boolean
 saving?: boolean
}>
const emit = defineEmits(['save', 'execute', 'undo', 'redo', 'settings'])
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
 <Button size="sm" class="group relative overflow-hidden":disabled="saving" @click="emit('save')">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <Save class="w-4 mr-2" />
 {{ saving ? '保存中...': '保存' }}
 </Button>
 </div>
 </div>
</template>
