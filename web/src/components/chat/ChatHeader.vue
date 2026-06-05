<script setup lang="ts">
/**
 * UX 重设计：chat 路径 Provider 与模型选择已折叠到 ChatInput
 * 底部 model-selector。本组件仅保留空间下拉、角色下拉、ResolvedSourceBadge。
 *
 * 历史背景：删除原顶部凭证下拉与凭证切换确认弹窗、所有相关状态与事件，
 * 全部迁移到 ChatInput。
 */
import type { ResolvedProvider } from '~/types/providerCredential'
import ResolvedSourceBadge from '~/components/providers/ResolvedSourceBadge.vue'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { ROLE_OPTIONS } from '~/types/chat'

interface Props {
  /** ：当前对话的四层 Provider 解析链（null=全链路 miss 或未加载） */
  resolvedProvider?: ResolvedProvider | null
}

withDefaults(defineProps<Props>(), {
  resolvedProvider: null,
})

const chatStore = useChatStore()
const spacesStore = useSpacesStore()
</script>

<template>
  <div class="chat-header">
    <!-- 空间选择 -->
    <Select v-model="chatStore.selectedSpaceId">
      <SelectTrigger class="w-44 h-8 text-xs border-border/40 bg-transparent shadow-none">
        <SelectValue placeholder="选择空间" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem
          v-for="space in spacesStore.spaces"
          :key="space.id"
          :value="space.id"
        >
          {{ space.name }}
        </SelectItem>
      </SelectContent>
    </Select>

    <!-- 角色选择 -->
    <Select v-model="chatStore.selectedRole">
      <SelectTrigger class="w-28 h-8 text-xs border-border/40 bg-transparent shadow-none">
        <SelectValue placeholder="角色" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem
          v-for="role in ROLE_OPTIONS"
          :key="role.value"
          :value="role.value"
        >
          {{ role.label }}
        </SelectItem>
      </SelectContent>
    </Select>

    <!-- ：四层 Provider 解析 Inspector -->
    <ResolvedSourceBadge
      v-if="resolvedProvider"
      :source="resolvedProvider.source"
      :chain="resolvedProvider.chain"
    />
  </div>
</template>

<style scoped>
.chat-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  border-bottom: 1px solid hsl(var(--border) / 0.3);
}
</style>
