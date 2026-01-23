<script setup lang="ts">
import {
 CheckCircle,
 Clock,
 Loader2,
 Pause,
 Square,
 XCircle,
} from 'lucide-vue-next'
import { computed } from 'vue'
import { Progress } from '~/components/ui/progress'
import { cn } from '~/lib/utils'
interface Props {
 status: string
 progress: number
 totalNodes: number
 completedNodes: number
 failedNodes: number
 skippedNodes: number
 duration?: number | null
}
const props = defineProps<Props>
const statusConfig = {
 pending: { icon: Clock, color: 'text-gray-500', bg: 'bg-gray-100 dark:bg-gray-800', label: 'Pending' },
 running: { icon: Loader2, color: 'text-blue-500', bg: 'bg-blue-100 dark:bg-blue-900/30', label: 'Running', animate: true },
 completed: { icon: CheckCircle, color: 'text-green-500', bg: 'bg-green-100 dark:bg-green-900/30', label: 'Completed' },
 failed: { icon: XCircle, color: 'text-red-500', bg: 'bg-red-100 dark:bg-red-900/30', label: 'Failed' },
 paused: { icon: Pause, color: 'text-yellow-500', bg: 'bg-yellow-100 dark:bg-yellow-900/30', label: 'Paused' },
 cancelled: { icon: Square, color: 'text-gray-500', bg: 'bg-gray-100 dark:bg-gray-800', label: 'Cancelled' },
 timeout: { icon: Clock, color: 'text-red-500', bg: 'bg-red-100 dark:bg-red-900/30', label: 'Timeout' },
}
const currentStatus = computed( => statusConfig[props.status as keyof typeof statusConfig] || statusConfig.pending)
const formattedDuration = computed( => {
 if (!props.duration)
 return '-'
 const seconds = Math.round(props.duration)
 if (seconds < 60)
 return `${seconds}s`
 const minutes = Math.floor(seconds / 60)
 const remainingSeconds = seconds % 60
 return `${minutes}m ${remainingSeconds}s`
})
</script>
<template>
 <div class="space-y-4">
 <!-- Status Badge -->
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2">
 <div:class="cn('.5 rounded-md', currentStatus.bg)">
 <component:is="currentStatus.icon":class="cn(
 'w-4 ',
 currentStatus.color,
 currentStatus.animate && 'animate-spin',
 )"
 />
 </div>
 <span class="font-medium">{{ currentStatus.label }}</span>
 </div>
 <span class="text-sm text-muted-foreground">{{ formattedDuration }}</span>
 </div>
 <!-- Progress Bar -->
 <div class="space-y-2">
 <div class="flex justify-between text-sm">
 <span class="text-muted-foreground">Progress</span>
 <span class="font-medium">{{ Math.round(progress) }}%</span>
 </div>
 <Progress:model-value="progress" class="" />
 </div>
 <!-- Node Stats -->
 <div class="grid grid-cols-4 gap-2 text-center text-xs">
 <div class=" rounded bg-muted/50">
 <div class="font-medium text-lg">
 {{ totalNodes }}
 </div>
 <div class="text-muted-foreground">
 Total
 </div>
 </div>
 <div class=" rounded bg-green-100 dark:bg-green-900/20">
 <div class="font-medium text-lg text-green-600">
 {{ completedNodes }}
 </div>
 <div class="text-muted-foreground">
 Done
 </div>
 </div>
 <div class=" rounded bg-red-100 dark:bg-red-900/20">
 <div class="font-medium text-lg text-red-600">
 {{ failedNodes }}
 </div>
 <div class="text-muted-foreground">
 Failed
 </div>
 </div>
 <div class=" rounded bg-gray-100 dark:bg-gray-800">
 <div class="font-medium text-lg text-gray-500">
 {{ skippedNodes }}
 </div>
 <div class="text-muted-foreground">
 Skipped
 </div>
 </div>
 </div>
 </div>
</template>
