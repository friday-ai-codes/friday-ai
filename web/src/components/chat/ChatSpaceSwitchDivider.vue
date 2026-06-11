<script setup lang="ts">
/**
 * 会话内切换空间的分隔线。
 *
 * 渲染 role=system + metadata.type=space_switch 的标记消息（后端
 * ConversationService.switch_space 落库）：居中横线 + 「已切换空间到 xxx」。
 * 分隔线以下的回答基于新空间，以上历史仅作参考。
 */
import type { ConversationMessage } from '~/types/chat'

const props = defineProps<{
  message: ConversationMessage
}>()

const label = computed(() => {
  const meta = props.message.metadata ?? {}
  const toName = typeof meta.to_space_name === 'string' ? meta.to_space_name : ''
  const toSpaceId = meta.to_space_id
  if (toSpaceId && toName)
    return `已切换空间到「${toName}」`
  if (!toSpaceId)
    return '已切换为通用对话（不绑定空间）'
  return props.message.content || '已切换空间'
})
</script>

<template>
  <div class="space-switch-divider" role="separator" :aria-label="label">
    <span class="space-switch-divider-line" />
    <span class="space-switch-divider-label">
      <span class="icon-[lucide--folder-sync] text-[12px] shrink-0" />
      {{ label }}
    </span>
    <span class="space-switch-divider-line" />
  </div>
</template>

<style scoped>
.space-switch-divider {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.25rem 0;
}

.space-switch-divider-line {
  flex: 1;
  height: 1px;
  background: hsl(var(--border) / 0.6);
}

.space-switch-divider-label {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.1875rem 0.625rem;
  border-radius: 9999px;
  border: 1px solid hsl(var(--border) / 0.5);
  background: hsl(var(--muted) / 0.4);
  color: hsl(var(--muted-foreground));
  font-size: 0.6875rem;
  font-weight: 500;
  white-space: nowrap;
}
</style>
