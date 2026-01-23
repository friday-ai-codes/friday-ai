<script setup lang="ts">
import { GitBranch, Clock, Copy } from 'lucide-vue-next'
import { Handle, Position, type NodeProps } from '@vue-flow/core'
import { Card, CardHeader, CardTitle, CardContent } from '~/components/ui/card'
import { Badge } from '~/components/ui/badge'
import { cn } from '~/lib/utils'
import { computed } from 'vue'
const props = defineProps<NodeProps>
const isSelected = computed( => props.selected)
const getIcon = (type: string) => {
 switch (type) {
 case 'condition': return GitBranch
 case 'delay': return Clock
 case 'parallel': return Copy
 default: return GitBranch
 }
}
// Get output handles based on condition config
const outputHandles = computed( => {
 const nodeType = props.data?.node_type || props.type
 if (nodeType === 'condition') {
 const conditions = props.data?.config?.conditions ||
 const handles = conditions.map((c: any, i: number) => ({
 id: `branch_${i}`,
 label: c.name || `Branch ${i + 1}`,
 }))
 handles.push({ id: 'else', label: 'Else' })
 return handles
 }
 if (nodeType === 'parallel') {
 return [
 { id: 'fork', label: 'Fork' },
 { id: 'join', label: 'Join' },
 ]
 }
 return [{ id: 'default', label: 'Output' }]
})
</script>
<template>
 <div class="relative group">
 <!-- Input Handle -->
 <Handle
 type="target":position="Position.Left"
 class="!w-3 ! !bg-muted-foreground transition-colors hover:!bg-primary"
 />
 <Card:class="cn(
 'w-64 border-2 transition-all duration-200 shadow-sm border- border-l-purple-500',
 isSelected ? 'border-primary ring-2 ring-primary/20': 'border-border hover:border-primary/50'
 )"
 >
 <CardHeader class=" pb-2 space-y-0">
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2">
 <div class=".5 rounded-md bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
 <component:is="getIcon(props.data?.node_type || props.type)" class="w-4 " />
 </div>
 <CardTitle class="text-sm font-medium leading-none">
 {{ label }}
 </CardTitle>
 </div>
 <Badge variant="secondary" class="text-[10px] px-1.5 bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
 Control
 </Badge>
 </div>
 </CardHeader>
 <CardContent class=" pt-2 text-xs text-muted-foreground">
 <div class="space-y-2">
 <!-- Condition branches preview -->
 <div v-if="(props.data?.node_type || props.type) === 'condition'" class="space-y-1">
 <div
 v-for="(handle, index) in outputHandles":key="handle.id"
 class="flex items-center gap-2 text-[10px]"
 >
 <div:class="cn(
 'w-2 rounded-full',
 handle.id === 'else' ? 'bg-gray-400': 'bg-purple-500'
 )"
 />
 <span>{{ handle.label }}</span>
 </div>
 </div>
 <!-- Delay config preview -->
 <div v-else-if="(props.data?.node_type || props.type) === 'delay'" class="font-mono text-[10px] bg-muted px-1 rounded inline-block">
 {{ props.data?.config?.duration || 60 }}s
 </div>
 <p class="line-clamp-2">{{ props.data?.description || 'Control flow node' }}</p>
 </div>
 </CardContent>
 </Card>
 <!-- Multiple Output Handles for condition node -->
 <div class="absolute right-0 top-0 h-full flex flex-col justify-center">
 <Handle
 v-for="(handle, index) in outputHandles":key="handle.id"
 type="source":position="Position.Right":id="handle.id":style="{ top: `${((index + 1) / (outputHandles.length + 1)) * 100}%` }"
 class="!w-3 ! !bg-muted-foreground transition-colors hover:!bg-primary !transform-none !relative !right-[-6px]"
 />
 </div>
 </div>
</template>
