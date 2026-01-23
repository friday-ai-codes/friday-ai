<script setup lang="ts">
import { Clock, GitBranch, MessageSquare, Play, Terminal, Webhook } from 'lucide-vue-next'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
const nodeTypes = [
 {
 category: 'Triggers',
 items: [
 { type: 'manual_trigger', label: 'Manual Trigger', icon: Play },
 { type: 'webhook_trigger', label: 'Webhook', icon: Webhook },
 { type: 'schedule_trigger', label: 'Schedule', icon: Clock },
 ],
 },
 {
 category: 'Actions',
 items: [
 { type: 'http_request', label: 'HTTP Request', icon: Webhook }, // Reusing Webhook icon for HTTP
 { type: 'create_branch', label: 'Create Branch', icon: GitBranch },
 { type: 'code_implement', label: 'AI Coding', icon: Terminal },
 ],
 },
 {
 category: 'Logic',
 items: [
 { type: 'condition', label: 'Condition (If/Else)', icon: GitBranch },
 { type: 'approval', label: 'Human Approval', icon: MessageSquare },
 ],
 },
]
function onDragStart(event: DragEvent, nodeType: string) {
 if (event.dataTransfer) {
 event.dataTransfer.setData('application/vueflow', nodeType)
 event.dataTransfer.effectAllowed = 'move'
 }
}
</script>
<template>
 <Card class="h-full w-64 border-r rounded-none flex flex-col">
 <CardHeader class="pb-4">
 <CardTitle class="text-lg">
 Nodes
 </CardTitle>
 </CardHeader>
 <CardContent class="flex-1 overflow-y-auto space-y-6">
 <div v-for="category in nodeTypes":key="category.category">
 <h3 class="text-sm font-medium text-muted-foreground mb-3 px-1">
 {{ category.category }}
 </h3>
 <div class="grid grid-cols-1 gap-2">
 <div
 v-for="item in category.items":key="item.type"
 class="flex items-center gap-3 text-sm border rounded-md cursor-grab hover:bg-accent hover:text-accent-foreground transition-colors":draggable="true"
 @dragstart="onDragStart($event, item.type)"
 >
 <component:is="item.icon" class="w-4 " />
 <span>{{ item.label }}</span>
 </div>
 </div>
 </div>
 </CardContent>
 </Card>
</template>
