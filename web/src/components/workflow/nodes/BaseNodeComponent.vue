<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position, type NodeProps } from '@vue-flow/core'
import { Card, CardHeader, CardTitle, CardContent } from '~/components/ui/card'
import { Badge } from '~/components/ui/badge'
import { cn } from '~/lib/utils'
interface Props extends NodeProps {
 icon?: any
 color?: string
 badge?: string
}
const props = defineProps<Props>
const isSelected = computed( => props.selected)
</script>
<template>
 <div class="relative group">
 <!-- Input Handle (Target) -->
 <Handle
 v-if="type !== 'trigger'"
 type="target":position="Position.Left"
 class="!w-3 ! !bg-muted-foreground transition-colors hover:!bg-primary"
 />
 <Card:class="cn(
 'w-64 border-2 transition-all duration-200 shadow-sm',
 isSelected ? 'border-primary ring-2 ring-primary/20': 'border-border hover:border-primary/50',
 props.class
 )"
 >
 <CardHeader class=" pb-2 space-y-0">
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2">
 <div
 v-if="icon"
 class=".5 rounded-md bg-muted text-foreground"
 >
 <component:is="icon" class="w-4 " />
 </div>
 <CardTitle class="text-sm font-medium leading-none">
 {{ label }}
 </CardTitle>
 </div>
 <Badge v-if="badge" variant="secondary" class="text-[10px] px-1.5 ">
 {{ badge }}
 </Badge>
 </div>
 </CardHeader>
 <CardContent class=" pt-2 text-xs text-muted-foreground">
 <slot>
 <div v-if="data.description" class="line-clamp-2">
 {{ data.description }}
 </div>
 </slot>
 </CardContent>
 </Card>
 <!-- Output Handle (Source) -->
 <Handle
 type="source":position="Position.Right"
 class="!w-3 ! !bg-muted-foreground transition-colors hover:!bg-primary"
 />
 </div>
</template>
