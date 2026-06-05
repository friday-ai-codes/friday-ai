<script setup lang="ts">
/**
 * 编码失败卡片 -- 展示编码错误信息，红色边框标识。
 *
 * 长错误消息（>100 字）折叠显示，点击展开。
 * 不提供重试按钮（per D-13），用户在对话中重新描述需求。
 */
import { ref } from 'vue'

defineProps<{
  errorMessage: string
}>()

const expanded = ref(false)
</script>

<template>
  <div class="card mt-2 animate-fade-in border-destructive/30">
    <div class="px-4 py-3 flex items-center gap-2">
      <span class="icon-[lucide--x-circle] text-destructive" />
      <span class="text-sm font-semibold">编码失败</span>
    </div>
    <div class="px-4 pb-3">
      <template v-if="errorMessage.length <= 100">
        <p class="text-xs text-muted-foreground">
          {{ errorMessage }}
        </p>
      </template>
      <template v-else>
        <p class="text-xs text-muted-foreground">
          {{ errorMessage.slice(0, 100) }}...
        </p>
        <button
          class="text-xs text-primary mt-1 cursor-pointer"
          @click="expanded = !expanded"
        >
          {{ expanded ? '收起' : '查看详情' }}
        </button>
        <p v-if="expanded" class="text-xs text-muted-foreground mt-1 whitespace-pre-wrap">
          {{ errorMessage }}
        </p>
      </template>
    </div>
  </div>
</template>
