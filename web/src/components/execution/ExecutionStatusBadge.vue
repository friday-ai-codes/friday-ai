<script setup lang="ts">
/**
 * ExecutionStatusBadge — StatusBadge 的薄包装
 *
 * 保持文件名和导入路径不变，内部委托给统一的 StatusBadge 组件。
 */
import StatusBadge from '~/components/common/StatusBadge.vue'

withDefaults(defineProps<{
  status: string
  showLabel?: boolean
  size?: 'sm' | 'md' | 'lg'
}>(), {
  showLabel: true,
  size: 'md',
})
</script>

<template>
  <StatusBadge type="execution" :status="status" :show-label="showLabel" :size="size" />
</template>
