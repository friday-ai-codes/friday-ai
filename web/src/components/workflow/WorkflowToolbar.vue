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
 <div class=" border-b flex items-center justify-between px-4 bg-background">
 <div class="flex items-center space-x-2">
 <Button variant="ghost" size="icon":disabled="!canUndo" @click="emit('undo')">
 <Undo class="w-4 " />
 </Button>
 <Button variant="ghost" size="icon":disabled="!canRedo" @click="emit('redo')">
 <Redo class="w-4 " />
 </Button>
 </div>
 <div class="flex items-center space-x-2">
 <Button variant="outline" size="sm" @click="emit('settings')">
 <Settings class="w-4 mr-2" />
 Settings
 </Button>
 <Button variant="default" size="sm" @click="emit('execute')">
 <Play class="w-4 mr-2" />
 Run
 </Button>
 <Button variant="default" size="sm":disabled="saving" @click="emit('save')">
 <Save class="w-4 mr-2" />
 {{ saving ? 'Saving...': 'Save' }}
 </Button>
 </div>
 </div>
</template>
