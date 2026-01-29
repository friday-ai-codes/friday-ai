<script setup lang="ts">
import { computed } from 'vue'
const props = withDefaults(defineProps<{
 status: string
 showLabel?: boolean
 size?: 'sm' | 'md' | 'lg'
}>, {
 showLabel: true,
 size: 'md',
})
const statusConfig = computed( => {
 const configs: Record<string, { icon: string, color: string, bg: string, label: string, animate?: boolean }> = {
 pending: { icon: 'lucide--clock', color: 'text-gray-500', bg: 'bg-gray-500/10', label: '等待中' },
 queued: { icon: 'lucide--list', color: 'text-gray-500', bg: 'bg-gray-500/10', label: '排队中' },
 running: { icon: 'lucide--loader-2', color: 'text-blue-500', bg: 'bg-blue-500/10', label: '运行中', animate: true },
 paused: { icon: 'lucide--pause', color: 'text-yellow-500', bg: 'bg-yellow-500/10', label: '已暂停' },
 completed: { icon: 'lucide--check-circle', color: 'text-emerald-500', bg: 'bg-emerald-500/10', label: '已完成' },
 failed: { icon: 'lucide--x-circle', color: 'text-red-500', bg: 'bg-red-500/10', label: '失败' },
 cancelled: { icon: 'lucide--square', color: 'text-gray-500', bg: 'bg-gray-500/10', label: '已取消' },
 timeout: { icon: 'lucide--alarm-clock-off', color: 'text-orange-500', bg: 'bg-orange-500/10', label: '超时' },
 waiting_approval: { icon: 'lucide--user-check', color: 'text-orange-500', bg: 'bg-orange-500/10', label: '待审批' },
 waiting_input: { icon: 'lucide--edit', color: 'text-purple-500', bg: 'bg-purple-500/10', label: '待输入' },
 skipped: { icon: 'lucide--skip-forward', color: 'text-gray-400', bg: 'bg-gray-400/10', label: '已跳过' },
 }
 return configs[props.status] || { icon: 'lucide--help-circle', color: 'text-gray-500', bg: 'bg-gray-500/10', label: props.status }
})
const sizeClasses = computed( => {
 const sizes = {
 sm: { badge: 'px-1.5 py-0.5 text-xs gap-1', icon: 'text-xs' },
 md: { badge: 'px-2 py-1 text-xs gap-1.5', icon: 'text-sm' },
 lg: { badge: 'px-2.5 py-1.5 text-sm gap-2', icon: 'text-base' },
 }
 return sizes[props.size]
})
</script>
<template>
 <span
 class="inline-flex items-center rounded-full font-medium":class="[statusConfig.bg, statusConfig.color, sizeClasses.badge]"
 >
 <span:class="[
 `icon-[${statusConfig.icon}]`,
 sizeClasses.icon,
 statusConfig.animate ? 'animate-spin': '',
 ]"
 />
 <span v-if="showLabel">{{ statusConfig.label }}</span>
 </span>
</template>
