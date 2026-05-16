<script setup lang="ts">
import type { GalaxyEdgeType, GalaxyNode } from '~/api/galaxy'
import { ScrollArea } from '~/components/ui/scroll-area'
// ============================================================================
// Props / Emits
// ============================================================================
defineProps<{
 calledBy?: Array<{ caller_node_id: string, edge_type: GalaxyEdgeType }>
 calls?: Array<{ source_node_id: string, edge_type: GalaxyEdgeType }>
 neighbors?: Array<{ node: GalaxyNode, edge_type: GalaxyEdgeType, direction: 'in' | 'out' }>
 loading?: boolean
}>
const emit = defineEmits<{
 (e: 'node-select', nodeId: string): void
}>
// ============================================================================
// 边类型颜色（复用 GalaxyLegend 配色）
// ============================================================================
const EDGE_COLORS: Record<GalaxyEdgeType, string> = {
 CALL: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
 IMPORT: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
 SAME_FILE: 'bg-gray-500/20 text-gray-300 border-gray-500/30',
 TEST_OF: 'bg-orange-500/20 text-orange-300 border-orange-500/30',
 CO_CHANGED: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
 SEMANTIC: 'bg-pink-500/20 text-pink-300 border-pink-500/30',
 API_CALLS: 'bg-red-500/20 text-red-300 border-red-500/30',
 IMPLEMENTS: 'bg-violet-500/20 text-violet-300 border-violet-500/30',
}
function edgeColor(type: GalaxyEdgeType): string {
 return EDGE_COLORS[type] ?? 'bg-white/10 text-white/50 border-white/20'
}
</script>
<template>
 <ScrollArea class="h-full">
 <div class=" space-y-6">
 <!-- 加载骨架 -->
 <div
 v-if="loading"
 class="space-y-3"
 >
 <div
 v-for="i in 4":key="i"
 class=" rounded-lg bg-white/5 animate-pulse"
 />
 </div>
 <template v-else>
 <!-- 被调用（called_by） -->
 <section v-if="calledBy && calledBy.length > 0">
 <h4 class="text-white/50 text-xs uppercase tracking-wider mb-3 flex items-center gap-2">
 <span class="icon-[lucide--arrow-down-to-line] text-sm" />
 被调用（{{ calledBy.length }}）
 </h4>
 <ul class="space-y-1">
 <li
 v-for="ref in calledBy":key="ref.caller_node_id"
 class="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-white/5 cursor-pointer group transition-colors"
 @click="emit('node-select', ref.caller_node_id)"
 >
 <span
 class="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border":class="edgeColor(ref.edge_type)"
 >
 {{ ref.edge_type }}
 </span>
 <span class="flex-1 text-white/70 text-sm font-mono truncate text-xs">
 {{ ref.caller_node_id }}
 </span>
 <span class="icon-[lucide--arrow-right] text-white/20 text-sm opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
 </li>
 </ul>
 </section>
 <!-- 调用（calls / references） -->
 <section v-if="calls && calls.length > 0">
 <h4 class="text-white/50 text-xs uppercase tracking-wider mb-3 flex items-center gap-2">
 <span class="icon-[lucide--arrow-up-from-line] text-sm" />
 调用（{{ calls.length }}）
 </h4>
 <ul class="space-y-1">
 <li
 v-for="ref in calls":key="ref.source_node_id"
 class="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-white/5 cursor-pointer group transition-colors"
 @click="emit('node-select', ref.source_node_id)"
 >
 <span
 class="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border":class="edgeColor(ref.edge_type)"
 >
 {{ ref.edge_type }}
 </span>
 <span class="flex-1 text-white/70 text-sm font-mono truncate text-xs">
 {{ ref.source_node_id }}
 </span>
 <span class="icon-[lucide--arrow-right] text-white/20 text-sm opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
 </li>
 </ul>
 </section>
 <!-- 邻居关系（neighbors） -->
 <section v-if="neighbors && neighbors.length > 0">
 <h4 class="text-white/50 text-xs uppercase tracking-wider mb-3 flex items-center gap-2">
 <span class="icon-[lucide--git-merge] text-sm" />
 关联节点（{{ neighbors.length }}）
 </h4>
 <ul class="space-y-1">
 <li
 v-for="nb in neighbors":key="`${nb.node.id}-${nb.direction}`"
 class="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-white/5 cursor-pointer group transition-colors"
 @click="emit('node-select', nb.node.id)"
 >
 <span
 class="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border":class="edgeColor(nb.edge_type)"
 >
 {{ nb.edge_type }}
 </span>
 <span
 class="shrink-0 text-white/30 text-xs":title="nb.direction === 'in' ? '入边': '出边'"
 >
 {{ nb.direction === 'in' ? '←': '→' }}
 </span>
 <div class="flex-1 min-w-0">
 <p class="text-white/80 text-sm truncate">
 {{ nb.node.label }}
 </p>
 <p class="text-white/30 text-xs truncate">
 {{ nb.node.file_path }}
 </p>
 </div>
 <span class="icon-[lucide--arrow-right] text-white/20 text-sm opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
 </li>
 </ul>
 </section>
 <!-- 空状态 -->
 <div
 v-if="(!calledBy || calledBy.length === 0) && (!calls || calls.length === 0) && (!neighbors || neighbors.length === 0)"
 class="flex flex-col items-center gap-2 py-10 text-white/30"
 >
 <span class="icon-[lucide--unlink] text-3xl" />
 <p class="text-sm">
 暂无引用关系
 </p>
 </div>
 </template>
 </div>
 </ScrollArea>
</template>
