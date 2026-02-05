<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import type { DesignTimeVariable } from '~/composables/useDesignTimeVariables'
interface Props {
 items: DesignTimeVariable
 command: (item: DesignTimeVariable) => void
}
const props = defineProps<Props>
const selectedIndex = ref(0)
const scrollContainer = ref<HTMLElement | null>(null)
// Group items by nodeId for display
const groupedItems = computed( => {
 const groups = new Map<string, { nodeLabel: string; items: DesignTimeVariable }>
 for (const item of props.items) {
 if (!groups.has(item.nodeId)) {
 groups.set(item.nodeId, {
 nodeLabel: item.nodeLabel,
 items:,
 })
 }
 groups.get(item.nodeId)!.items.push(item)
 }
 return Array.from(groups.entries).map(([nodeId, group]) => ({
 nodeId,
 nodeLabel: group.nodeLabel,
 items: group.items,
 }))
})
// Get flat index for an item
function getFlatIndex(groupIndex: number, itemIndex: number): number {
 let index = 0
 for (let g = 0; g < groupIndex; g++) {
 index += groupedItems.value[g].items.length
 }
 return index + itemIndex
}
// Check if item at flat index is selected
function isSelected(groupIndex: number, itemIndex: number): boolean {
 return getFlatIndex(groupIndex, itemIndex) === selectedIndex.value
}
// Select item by flat index
function selectItem(index: number) {
 if (index >= 0 && index < props.items.length) {
 props.command(props.items[index])
 }
}
// Scroll selected item into view
function scrollIntoView {
 nextTick( => {
 const selected = scrollContainer.value?.querySelector('[data-selected="true"]')
 selected?.scrollIntoView({ block: 'nearest' })
 })
}
// Reset selection when items change
watch( => props.items, => {
 selectedIndex.value = 0
})
// Keyboard navigation handler
function onKeyDown(event: KeyboardEvent): boolean {
 if (event.key === 'ArrowUp') {
 selectedIndex.value = Math.max(0, selectedIndex.value - 1)
 scrollIntoView
 return true
 }
 if (event.key === 'ArrowDown') {
 selectedIndex.value = Math.min(props.items.length - 1, selectedIndex.value + 1)
 scrollIntoView
 return true
 }
 if (event.key === 'Enter' || event.key === 'Tab') {
 selectItem(selectedIndex.value)
 return true
 }
 // Let Esc be handled by TipTap
 return false
}
defineExpose({ onKeyDown })
</script>
<template>
 <div
 ref="scrollContainer"
 class="bg-popover/95 backdrop-blur-md border border-border/50 rounded-xl shadow-lg shadow-black/5 max- overflow-y-auto min-w-64 "
 >
 <!-- Empty state -->
 <div
 v-if="items.length === 0"
 class="flex flex-col items-center justify-center py-8 px-4 text-center"
 >
 <div class=" rounded-xl bg-muted/50 mb-3">
 <span class="icon-[lucide--variable] text-2xl text-muted-foreground" />
 </div>
 <p class="text-sm font-medium text-muted-foreground">
 当前无可用变量
 </p>
 <p class="text-xs text-muted-foreground/70 mt-1">
 请先连接上游节点
 </p>
 </div>
 <!-- Grouped variable list -->
 <template v-else>
 <div
 v-for="(group, groupIndex) in groupedItems":key="group.nodeId"
 class="mb-1 last:mb-0"
 >
 <!-- Group header -->
 <div class="px-2 py-1.5 text-xs font-medium text-muted-foreground flex items-center gap-1.5">
 <span class="icon-[lucide--box] text-xs opacity-70" />
 <span>{{ group.nodeLabel }}</span>
 </div>
 <!-- Group items -->
 <button
 v-for="(item, itemIndex) in group.items":key="item.path"
 type="button":data-selected="isSelected(groupIndex, itemIndex)"
 class="w-full px-3 py-2 text-sm text-left rounded-lg flex items-center justify-between gap-2 transition-colors":class="[
 isSelected(groupIndex, itemIndex)
 ? 'bg-accent': 'hover:bg-accent/50'
 ]"
 @click="selectItem(getFlatIndex(groupIndex, itemIndex))"
 >
 <span class="truncate">{{ item.outputLabel }}</span>
 <span class="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground shrink-0">
 {{ item.type }}
 </span>
 </button>
 </div>
 </template>
 </div>
</template>
