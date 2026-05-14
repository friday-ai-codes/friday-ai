<script setup lang="ts">
/**
 * GraphRAG 二跳扩散自定义节点（Phase Plan，work item §5.3）
 *
 * 视觉风格沿用 SymbolNode 卡片骨架（240px / bg-card/80 / rounded-2xl）但
 * **不 import SymbolNode**（work item §10 硬约束 5）。本 plan 仅落基础壳；
 * TooltipContent 第 3 行 content preview / 选中环交互留 Plan 接力。
 */
import type { DiffusionNodeData } from '~/composables/useDiffusionGraph'
import { Handle, Position } from '@vue-flow/core'
import { computed } from 'vue'
import { Badge } from '~/components/ui/badge'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
const props = defineProps<{
 data: DiffusionNodeData
 selected?: boolean
}>
type BadgeVariant = 'default' | 'secondary' | 'outline'
const hopLabel = computed( => {
 if (props.data.hop === 'source')
 return '起点'
 return `${props.data.hop}-hop`
})
const hopBadgeVariant = computed<BadgeVariant>( => {
 if (props.data.hop === 'source')
 return 'default'
 if (props.data.hop === 1)
 return 'secondary'
 return 'outline'
})
const hopBadgeClass = computed( => {
 if (props.data.hop === 2)
 return 'border-dashed'
 return ''
})
const shellClass = computed( => {
 if (props.data.hop === 'source')
 return 'border-primary/50 bg-primary/5'
 if (props.data.hop === 2)
 return 'border-dashed border-border/40'
 return 'border-border/50'
})
const chunkIdShort = computed( => props.data.chunk_id.slice(0, 8))
</script>
<template>
 <TooltipProvider>
 <Tooltip>
 <TooltipTrigger as-child>
 <div
 class="w-[240px] bg-card/80 backdrop-blur-sm border rounded-2xl transition-all duration-200 relative":class="[
 shellClass,
 props.selected ? 'ring-2 ring-primary/50 shadow-lg border-primary/30': 'hover:shadow-md',
 ]"
 role="button"
 tabindex="0":aria-label="`代码块 ${data.fileBasename}, ${hopLabel}`"
 >
 <Badge:variant="hopBadgeVariant"
 class="absolute top-2 right-2 text-xs px-1.5 leading-none":class="hopBadgeClass"
 >
 {{ hopLabel }}
 </Badge>
 <div class="flex items-center gap-2 mb-2 pr-16">
 <div class=".5 rounded-lg bg-muted/40 shrink-0">
 <span class="icon-[lucide--file-code] w-3.5 .5 text-muted-foreground" />
 </div>
 <span class="font-mono text-sm font-medium text-foreground truncate">
 {{ data.fileBasename }}
 </span>
 </div>
 <p class="font-mono text-xs text-muted-foreground mb-1">
 L{{ data.line_start ?? '?' }}-{{ data.line_end ?? '?' }}
 </p>
 <p class="font-mono text-xs text-muted-foreground truncate">
 {{ data.file_path }}
 </p>
 </div>
 </TooltipTrigger>
 <TooltipContent class="max-w-[360px]">
 <p class="font-mono text-xs">
 {{ data.file_path }}:{{ data.line_start ?? '?' }}-{{ data.line_end ?? '?' }}
 </p>
 <p class="font-mono text-xs text-muted-foreground mt-1">
 chunk_id: {{ chunkIdShort }}
 </p>
 <!-- Plan 落 content preview 第 3 行（前 200 字 whitespace-pre-wrap line-clamp-6） -->
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 <Handle type="target":position="Position.Top" />
 <Handle type="source":position="Position.Bottom" />
</template>
