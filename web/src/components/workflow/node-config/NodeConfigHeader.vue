<script setup lang="ts">
import { Check, Copy, Settings, Wand2, X } from 'lucide-vue-next'
import { ref } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
interface Props {
 nodeTypeDisplayName: string | undefined
 hasInputs: boolean
 selectedNodeShortId: string
 selectedNodeId: string
}
const props = defineProps<Props>
const emit = defineEmits<{
 autoFill:
 close:
}>
// 复制节点 ID
const idCopied = ref(false)
async function copyNodeId {
 if (!props.selectedNodeId)
 return
 try {
 await navigator.clipboard.writeText(props.selectedNodeId)
 idCopied.value = true
 setTimeout( => {
 idCopied.value = false
 }, 2000)
 }
 catch {
 // intentionally ignored
 }
}
</script>
<template>
 <div class=" border-b border-border/50">
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-3">
 <div class=" rounded-xl bg-primary/10">
 <Settings class="w-5 text-primary" />
 </div>
 <div>
 <h3 class="text-base font-semibold">
 节点配置
 </h3>
 <Badge v-if="nodeTypeDisplayName" variant="secondary" class="mt-1">
 {{ nodeTypeDisplayName }}
 </Badge>
 </div>
 </div>
 <div class="flex items-center gap-1">
 <Button
 v-if="hasInputs"
 variant="ghost"
 size="sm"
 class=" hover:bg-muted/50 text-muted-foreground hover:text-foreground"
 @click="emit('autoFill')"
 >
 <Wand2 class="w-4 mr-1.5" />
 自动填充
 </Button>
 <Button variant="ghost" size="icon" class=" w-8 hover:bg-muted/50" @click="emit('close')">
 <X class="w-4 " />
 </Button>
 </div>
 </div>
 <!-- 节点 ID 显示 -->
 <div class="mt-3 flex items-center gap-2">
 <span class="text-xs text-muted-foreground">ID:</span>
 <code class="text-xs font-mono bg-muted/50 px-1.5 py-0.5 rounded">
 {{ selectedNodeShortId || selectedNodeId }}
 </code>
 <TooltipProvider>
 <Tooltip>
 <TooltipTrigger as-child>
 <button
 type="button"
 class="inline-flex items-center justify-center w-5 rounded hover:bg-muted/50 transition-colors"
 @click="copyNodeId"
 >
 <Check v-if="idCopied" class="w-3 text-green-500" />
 <Copy v-else class="w-3 text-muted-foreground" />
 </button>
 </TooltipTrigger>
 <TooltipContent side="top">
 <p>{{ idCopied ? '已复制': '复制节点 ID' }}</p>
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </div>
 </div>
</template>
