<script setup lang="ts">
import { computed, ref } from 'vue'
import { Checkbox } from '~/components/ui/checkbox'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { ScrollArea } from '~/components/ui/scroll-area'
/**
 * ToolSelector - Tool multi-select component for AI Agent node.
 *
 * Features:
 * - Search/filter tools by name and description
 * - Flat list display with ScrollArea (max 200px height)
 * - Select all / deselect individual tools
 * - Empty array = all enabled (inverse selection logic)
 */
interface Tool {
 name: string
 description: string
 category?: string
}
interface Props {
 tools: Tool
 modelValue: string
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'update:modelValue', value: string): void
}>
const searchQuery = ref('')
// Filter tools by search query (name or description)
const filteredTools = computed( => {
 const query = searchQuery.value.toLowerCase.trim
 if (!query) return props.tools
 return props.tools.filter(
 t =>
 t.name.toLowerCase.includes(query)
 || t.description.toLowerCase.includes(query),
 )
})
// Check if all tools are selected (empty array = all selected)
const allSelected = computed(
 => props.modelValue.length === 0,
)
// Check if a specific tool is enabled
// Per CONTEXT.md: empty array = all enabled
function isToolEnabled(toolName: string): boolean {
 if (props.modelValue.length === 0) return true
 return props.modelValue.includes(toolName)
}
// Toggle tool selection (inverse logic per CONTEXT.md)
// When unchecking: add to exclusion list
// When checking: remove from exclusion list (or keep empty if was all-selected)
function toggleTool(toolName: string) {
 const current = [...props.modelValue]
 if (allSelected.value) {
 // Currently all selected, user wants to disable one tool
 // Add all other tools to the list (enabled list)
 const newValue = props.tools
 .map(t => t.name)
 .filter(name => name !== toolName)
 emit('update:modelValue', newValue)
 }
 else {
 const idx = current.indexOf(toolName)
 if (idx >= 0) {
 // Tool is in enabled list, remove it (disable)
 current.splice(idx, 1)
 // If list becomes empty after removal, keep it empty (means none selected)
 // But if only one was removed and others remain, just update
 emit('update:modelValue', current)
 }
 else {
 // Tool is not in enabled list, add it (enable)
 current.push(toolName)
 // Check if all tools are now enabled
 if (current.length === props.tools.length) {
 emit('update:modelValue', ) // All selected = empty array
 }
 else {
 emit('update:modelValue', current)
 }
 }
 }
}
// Select all tools (emit empty array)
function selectAll {
 emit('update:modelValue', )
}
</script>
<template>
 <div class="space-y-3">
 <!-- Header with label and select all button -->
 <div class="flex items-center justify-between">
 <Label>启用的工具</Label>
 <button
 type="button"
 class="text-xs text-primary hover:underline transition-colors":class="{ 'text-muted-foreground': allSelected }"
 @click="selectAll"
 >
 {{ allSelected ? '已全选': '全选' }}
 </button>
 </div>
 <!-- Search input -->
 <Input
 v-model="searchQuery"
 placeholder="搜索工具..."
 class="bg-background/50"
 >
 <template #prefix>
 <span class="icon-[lucide--search] text-muted-foreground" />
 </template>
 </Input>
 <!-- Tools list with ScrollArea -->
 <ScrollArea class=" rounded-lg border border-border/50 bg-muted/30">
 <div class=" space-y-1">
 <div
 v-for="tool in filteredTools":key="tool.name"
 class="flex items-start gap-2 rounded-lg hover:bg-muted/50 cursor-pointer transition-colors"
 @click="toggleTool(tool.name)"
 >
 <Checkbox:checked="isToolEnabled(tool.name)"
 class="mt-0.5"
 @click.stop
 @update:checked="toggleTool(tool.name)"
 />
 <div class="flex-1 min-w-0">
 <div class="font-mono text-sm">{{ tool.name }}</div>
 <div class="text-xs text-muted-foreground truncate">
 {{ tool.description }}
 </div>
 </div>
 <span
 v-if="tool.category"
 class="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground shrink-0"
 >
 {{ tool.category }}
 </span>
 </div>
 <!-- Empty state -->
 <div
 v-if="filteredTools.length === 0"
 class="py-4 text-center text-sm text-muted-foreground"
 >
 未找到匹配的工具
 </div>
 </div>
 </ScrollArea>
 <!-- Help text -->
 <p class="text-xs text-muted-foreground">
 留空表示启用所有工具
 </p>
 </div>
</template>
