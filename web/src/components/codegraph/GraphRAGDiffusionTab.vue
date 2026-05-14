<!-- Plan 占位：完整画布由 Plan 重写 (work item §5.2) -->
<script setup lang="ts">
import type { NeighborMetadata } from '~/api/codegraph'
interface SourceChunk {
 chunk_id: string
 file_path: string
 line_start: number | null
 line_end: number | null
 content?: string
}
defineProps<{
 hop1Neighbors: NeighborMetadata
 hop2Neighbors: NeighborMetadata
 sourceChunks: SourceChunk
 loading: boolean
}>
defineEmits<{
 (e: 'node-click', chunkId: string): void
}>
</script>
<template>
 <div class="h-[520px] relative flex items-center justify-center">
 <p class="text-sm text-muted-foreground">
 GraphRAG 二跳扩散画布将在 Plan 落地
 </p>
 </div>
</template>
