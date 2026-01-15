<script setup lang="ts">
import type { TaskStatus } from '~/types'
import { Badge } from '~/components/ui/badge'
import { STATUS_COLORS, STATUS_LABELS } from '~/types'
const props = defineProps<{
 status: TaskStatus
 showIcon?: boolean
}>
// 状态图标映射
const statusIcons: Record<TaskStatus, string> = {
 pending: 'lucide--clock',
 planning: 'lucide--loader-circle',
 plan_review: 'lucide--eye',
 executing: 'lucide--loader-circle',
 code_review: 'lucide--eye',
 merged: 'lucide--check-circle',
 failed: 'lucide--x-circle',
}
// 是否是运行中状态
const isRunning = computed( =>
 props.status === 'planning' || props.status === 'executing',
)
</script>
<template>
 <Badge:class="[
 STATUS_COLORS[status],
 ]"
 variant="secondary"
 >
 <span
 v-if="showIcon"
 class="mr-1":class="[
 `icon-[${statusIcons[status]}]`,
 isRunning && 'animate-spin',
 ]"
 />
 {{ STATUS_LABELS[status] }}
 </Badge>
</template>
