<script setup lang="ts">
import { computed } from 'vue'
import { Badge } from '~/components/ui/badge'
import type { ConfigSource } from '~/types/provider'
const props = defineProps<{
 source: ConfigSource
}>
const config = computed( => {
 switch (props.source) {
 case 'system':
 return { label: '系统级', variant: 'secondary' as const, className: '' }
 case 'project':
 return { label: '项目级', variant: 'outline' as const, className: '' }
 case 'conversation':
 return { label: '对话级', variant: 'outline' as const, className: 'bg-blue-500/10 text-blue-600 border-blue-500/20' }
 case 'node':
 return { label: '节点级', variant: 'outline' as const, className: 'bg-purple-500/10 text-purple-600 border-purple-500/20' }
 }
})
</script>
<template>
 <Badge:variant="config.variant":class="['text-xs', config.className]"
 >
 {{ config.label }}
 </Badge>
</template>
