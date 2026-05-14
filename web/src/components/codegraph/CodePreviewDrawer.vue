<!-- Phase Plan：完整实现（替换 Plan 占位） -->
<script setup lang="ts">
/**
 * 代码片段预览 Drawer（Phase Plan，work item §5.5 / §6 / §10 硬约束 9 + 10）
 *
 * 数据来源：父组件 playground.vue 已持有 PlaygroundSearchResponse；Drawer 不发
 * 任何网络请求，仅从 props.searchResult.layers 中 layer === 'L3' 的 items 按
 * chunk_id 同步反查。hop1 / hop2 chunk 未命中 L3 items 时显示占位文案
 * "代码片段未在当前查询命中范围内，无法预览"（work item §6 + §10 硬约束 10）。
 *
 * a11y：Sheet 由 reka-ui 提供 role=dialog / focus trap / Esc 关闭；SheetTitle +
 * SheetDescription 自动连 aria-labelledby + aria-describedby（无需手写）。
 *
 * 安全：chunk.content 经 Vue 默认文本插值（HTML escape），禁 v-html / innerHTML
 * （per ESLint vue/no-v-html + 威胁模型 T-）。
 */
import type { LayerResult, PlaygroundSearchResponse } from '~/api/codegraph'
import { computed } from 'vue'
import { ScrollArea } from '~/components/ui/scroll-area'
import {
 Sheet,
 SheetContent,
 SheetDescription,
 SheetHeader,
 SheetTitle,
} from '~/components/ui/sheet'
const props = defineProps<{
 open: boolean
 chunkId: string | null
 searchResult?: PlaygroundSearchResponse | null
}>
const emit = defineEmits<{
 (e: 'update:open', value: boolean): void
}>
interface ChunkPreview {
 chunk_id: string
 file_path: string
 line_start: number | null
 line_end: number | null
 content: string
}
/**
 * 从 L3 layer items 中按 chunk_id 反查命中 chunk。
 * 命中且 content 为非空字符串才返回；其它情况（无 layers / 无 L3 / 不命中 /
 * content 类型不符 / content 空字符串）一律返回 null，由模板走 fallback 文案。
 */
function findChunkInLayers(
 layers: LayerResult | undefined,
 chunkId: string | null,
): ChunkPreview | null {
 if (!layers || !chunkId)
 return null
 const l3 = layers.find(l => l.layer === 'L3')
 if (!l3)
 return null
 for (const raw of l3.items) {
 if (typeof raw !== 'object' || raw === null)
 continue
 const item = raw as Record<string, unknown>
 if (item.chunk_id !== chunkId)
 continue
 if (typeof item.content !== 'string' || item.content.length === 0)
 return null
 if (typeof item.file_path !== 'string')
 return null
 return {
 chunk_id: chunkId,
 file_path: item.file_path,
 line_start: typeof item.line_start === 'number' ? item.line_start: null,
 line_end: typeof item.line_end === 'number' ? item.line_end: null,
 content: item.content,
 }
 }
 return null
}
const chunk = computed<ChunkPreview | null>( =>
 findChunkInLayers(props.searchResult?.layers, props.chunkId),
)
const chunkIdShort = computed( => props.chunkId?.slice(0, 8) ?? '')
const headerSubtitle = computed( => {
 if (chunk.value) {
 const ls = chunk.value.line_start
 const le = chunk.value.line_end
 if (ls !== null || le !== null)
 return `${chunk.value.file_path}:${ls ?? '?'}-${le ?? '?'}`
 return chunk.value.file_path
 }
 if (props.chunkId)
 return `chunk_id: ${chunkIdShort.value}`
 return '等待选择代码块...'
})
function onOpenUpdate(value: boolean): void {
 emit('update:open', value)
}
</script>
<template>
 <Sheet:open="open" @update:open="onOpenUpdate">
 <SheetContent
 side="right"
 class="w-[560px] max-w-[80vw] flex flex-col"
 >
 <SheetHeader class="px-5 py-4 border-b border-border/50">
 <SheetTitle class="text-sm font-semibold flex items-center gap-2">
 <span class="icon-[lucide--file-code] text-primary" />
 代码片段预览
 </SheetTitle>
 <SheetDescription
 class="text-xs text-muted-foreground font-mono truncate"
 >
 {{ headerSubtitle }}
 </SheetDescription>
 </SheetHeader>
 <div class="flex-1 overflow-hidden ">
 <div
 v-if="!chunk"
 class="text-sm text-muted-foreground py-8 text-center"
 role="status"
 >
 代码片段未在当前查询命中范围内，无法预览
 </div>
 <ScrollArea v-else class="h-full">
 <pre
 class="font-mono text-xs rounded-lg bg-muted/30 whitespace-pre-wrap break-words"
 >{{ chunk.content }}</pre>
 </ScrollArea>
 </div>
 </SheetContent>
 </Sheet>
</template>
