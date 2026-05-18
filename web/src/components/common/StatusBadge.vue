<script setup lang="ts">
import type { StatusConfig } from '~/config/status'
import { computed } from 'vue'
import { Badge } from '~/components/ui/badge'
import { getStatusConfig } from '~/config/status'
const props = withDefaults(defineProps<{
 type: 'execution' | 'runner' | 'codingTask' | 'index' | 'triggerLog' | 'graph'
 status: string
 showLabel?: boolean
 showIcon?: boolean
 size?: 'sm' | 'md' | 'lg'
}>, {
 showLabel: true,
 showIcon: true,
 size: 'md',
})
const config = computed<StatusConfig>( => getStatusConfig(props.type, props.status))
const sizeClass = computed( => ({
 sm: 'text-[10px] px-1.5 py-0.5',
 md: 'text-xs px-2 py-0.5',
 lg: 'text-sm px-2.5 py-1',
}[props.size]))
const iconSizeClass = computed( => ({
 sm: 'text-[10px]',
 md: 'text-xs',
 lg: 'text-sm',
}[props.size]))
</script>
<template>
 <Badge:variant="config.variant":class="sizeClass">
 <span
 v-if="showIcon":class="[`icon-[${config.icon}]`, iconSizeClass, config.animate ? 'animate-spin': '']"
 />
 <span v-if="showLabel">{{ config.label }}</span>
 </Badge>
</template>
