<script setup lang="ts">
/**
 * GraphRAG 二跳扩散自定义节点（ 骨架 + tooltip 内容实装，UI-SPEC / ）
 *
 * 视觉风格沿用 SymbolNode 卡片骨架（240px / bg-card/80 / rounded-2xl）但
 * **不 import SymbolNode**（UI-SPEC §10 硬约束 5）。
 *
 * TooltipContent 三行内容（ 完整落地）：
 *   1. file_path[:line_start-line_end]（line_start/end 全 null 时仅 file_path + HTML 注释 "行号信息缺失"）
 *   2. chunk_id: first8（slice(0, 8) mono muted）
 *   3. content preview 前 200 字符（whitespace-pre-wrap line-clamp-6），undefined 时降级 fallback 文案
 */
import type { DiffusionNodeData } from '~/composables/useDiffusionGraph'
import { Handle, Position } from '@vue-flow/core'
import { computed, inject } from 'vue'
import { Badge } from '~/components/ui/badge'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '~/components/ui/tooltip'

const props = defineProps<{
  data: DiffusionNodeData
  selected?: boolean
}>()

const emit = defineEmits<{
  (e: 'activate', chunkId: string): void
}>()

// HI-01：键盘激活路径（WCAG button widget contract）。
// Vue Flow `@node-click` 仅由鼠标点击触发；role="button" + tabindex="0" 必须
// 配合 keydown.enter / keydown.space 才能让键盘用户开 Drawer。
// Vue Flow 不冒泡自定义节点 emit，需要 inject 父组件提供的回调（GraphRAGDiffusionTab 注入）。
const onActivateInjected = inject<((chunkId: string) => void) | null>(
  'onDiffusionNodeActivate',
  null,
)
function onKeyboardActivate() {
  emit('activate', props.data.chunk_id)
  onActivateInjected?.(props.data.chunk_id)
}

type BadgeVariant = 'default' | 'secondary' | 'outline'

const hopLabel = computed(() => {
  if (props.data.hop === 'source')
    return '起点'
  return `${props.data.hop}-hop`
})

const hopBadgeVariant = computed<BadgeVariant>(() => {
  if (props.data.hop === 'source')
    return 'default'
  if (props.data.hop === 1)
    return 'secondary'
  return 'outline'
})

const hopBadgeClass = computed(() => {
  if (props.data.hop === 2)
    return 'border-dashed'
  return ''
})

const shellClass = computed(() => {
  if (props.data.hop === 'source')
    return 'border-primary/50 bg-primary/5'
  if (props.data.hop === 2)
    return 'border-dashed border-border/40'
  return 'border-border/50'
})

// ME-05：null/undefined 守卫，与 CodePreviewDrawer.chunkIdShort 一致防御
const chunkIdShort = computed(() => (props.data.chunk_id ?? '').slice(0, 8))

// 行号双 null 时回退到仅显示 file_path（per UI-SPEC + spec）
const hasLineRange = computed(
  () => props.data.line_start !== null || props.data.line_end !== null,
)

// content preview：截前 200 字符，避免超长 chunk 撑爆 tooltip（line-clamp-6 兜底）
const contentPreview = computed(() => {
  const c = props.data.content
  if (typeof c !== 'string' || c.length === 0)
    return null
  return c.slice(0, 200)
})
</script>

<template>
  <!-- HI-07：TooltipProvider 上提到 GraphRAGDiffusionTab 单实例，节点仅 Tooltip 三件套 -->
  <Tooltip>
    <TooltipTrigger as-child>
      <!-- HI-05：Handle 移进卡片 div 内（仍为 TooltipTrigger 子元素），保证锚点贴齐卡片视觉边缘 -->
      <div
        class="w-[240px] bg-card/80 backdrop-blur-sm border rounded-2xl p-3 transition-all duration-200 relative motion-reduce:transition-none"
        :class="[
          shellClass,
          props.selected ? 'ring-2 ring-primary/50 shadow-lg border-primary/30' : 'hover:shadow-md',
        ]"
        role="button"
        tabindex="0"
        :aria-label="`代码块 ${data.fileBasename}, ${hopLabel}`"
        @keydown.enter.prevent="onKeyboardActivate"
        @keydown.space.prevent="onKeyboardActivate"
      >
        <Handle type="target" :position="Position.Top" />
        <Badge
          :variant="hopBadgeVariant"
          class="absolute top-2 right-2 text-xs h-4 px-1.5 leading-none"
          :class="hopBadgeClass"
        >
          {{ hopLabel }}
        </Badge>

        <div class="flex items-center gap-2 mb-2 pr-16">
          <div class="p-1.5 rounded-lg bg-muted/40 shrink-0">
            <span class="icon-[lucide--file-code] w-3.5 h-3.5 text-muted-foreground" />
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
        <Handle type="source" :position="Position.Bottom" />
      </div>
    </TooltipTrigger>
    <TooltipContent class="max-w-[360px]">
      <p v-if="hasLineRange" class="font-mono text-xs">
        {{ data.file_path }}:{{ data.line_start ?? '?' }}-{{ data.line_end ?? '?' }}
      </p>
      <p v-else class="font-mono text-xs">
        {{ data.file_path }}
        <!-- 行号信息缺失 -->
      </p>
      <p class="font-mono text-xs text-muted-foreground mt-1">
        chunk_id: {{ chunkIdShort }}
      </p>
      <p
        v-if="contentPreview"
        class="text-xs whitespace-pre-wrap line-clamp-6 mt-1.5"
      >
        {{ contentPreview }}
      </p>
      <p
        v-else
        class="text-xs text-muted-foreground italic mt-1.5"
      >
        点击查看完整代码片段
      </p>
    </TooltipContent>
  </Tooltip>
</template>
