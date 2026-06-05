<script setup lang="ts">
import { Handle, Position } from '@vue-flow/core'
import { Badge } from '~/components/ui/badge'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'

export interface SymbolNodeData {
  name: string
  symbol_type: string
  file_path: string
  line_start: number
  line_end: number
  signature: string
}

const props = defineProps<{
  data: SymbolNodeData
  selected?: boolean
}>()

type BadgeVariant = 'default' | 'secondary' | 'destructive' | 'outline' | 'success' | 'warning' | 'info' | 'muted'

function symbolTypeBadgeVariant(type: string): BadgeVariant {
  switch (type.toUpperCase()) {
    case 'FUNCTION':
    case 'METHOD':
      return 'info'
    case 'CLASS':
      return 'success'
    case 'INTERFACE':
      return 'secondary'
    default:
      return 'muted'
  }
}

function symbolTypeIcon(type: string): string {
  switch (type.toUpperCase()) {
    case 'FUNCTION': return 'function-square'
    case 'CLASS': return 'box'
    case 'METHOD': return 'braces'
    case 'INTERFACE': return 'layout-template'
    default: return 'code'
  }
}
</script>

<template>
  <TooltipProvider>
    <Tooltip>
      <TooltipTrigger as-child>
        <div
          class="w-[240px] bg-card/80 backdrop-blur-sm border rounded-2xl p-3 transition-all duration-200 relative"
          :class="[
            props.selected
              ? 'ring-2 ring-primary/50 shadow-lg border-primary/30'
              : 'border-border/50 hover:shadow-md',
          ]"
          :aria-label="`${data.symbol_type}: ${data.name}`"
        >
          <!-- 类型徽章：右上角 absolute -->
          <Badge
            :variant="symbolTypeBadgeVariant(data.symbol_type)"
            class="absolute top-2 right-2 text-xs h-4 px-1.5 leading-none"
          >
            {{ data.symbol_type }}
          </Badge>

          <!-- 头部：图标 + 名称 -->
          <div class="flex items-center gap-2 mb-2 pr-16">
            <div class="p-1.5 rounded-lg bg-primary/10 shrink-0">
              <span :class="`icon-[lucide--${symbolTypeIcon(data.symbol_type)}] w-3.5 h-3.5 text-primary`" />
            </div>
            <span class="font-mono text-sm font-medium text-foreground truncate">{{ data.name }}</span>
          </div>

          <!-- Signature -->
          <p
            v-if="data.signature"
            class="font-mono text-xs text-muted-foreground line-clamp-2 mb-1.5 leading-relaxed"
          >
            {{ data.signature }}
          </p>

          <!-- 文件路径 -->
          <p class="font-mono text-xs text-muted-foreground truncate">
            {{ data.file_path }}
            <span class="ml-1">L{{ data.line_start }}-{{ data.line_end }}</span>
          </p>
        </div>
      </TooltipTrigger>
      <TooltipContent>
        <span class="font-mono text-xs">{{ data.file_path }}:L{{ data.line_start }}-{{ data.line_end }}</span>
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>

  <!-- Vue Flow Handles -->
  <Handle type="target" :position="Position.Top" />
  <Handle type="source" :position="Position.Bottom" />
</template>
