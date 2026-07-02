<script setup lang="ts">
/**
 * UX 重设计：chat 路径 Provider 与模型选择已折叠到 ChatInput
 * 底部 model-selector。本组件仅保留空间下拉、角色下拉、ResolvedSourceBadge。
 *
 * 历史背景：删除原顶部凭证下拉与凭证切换确认弹窗、所有相关状态与事件，
 * 全部迁移到 ChatInput。
 *
 * 入口重构后：左侧展示当前对话标题（草稿态显示「新对话」），
 * 右侧聚合空间 / 角色选择，高度与会话列表栏头部（h-16）对齐。
 */
import type { ResolvedProvider } from '~/types/providerCredential'
import FeedbackHeaderButton from '~/components/feedback/FeedbackHeaderButton.vue'
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

/** 实例里一个空间都没有：下拉无可选项，改为「去创建空间」CTA */
const noSpacesExist = computed(() => spacesStore.spaces.length === 0)

const conversationTitle = computed(
  () => chatStore.currentConversation?.title || '新对话',
)
const isRunning = computed(
  () => chatStore.currentConversation?.status === 'running' || chatStore.isStreaming,
)

/** Select 不接受 null value，用 sentinel 表示「通用对话（不绑定空间）」 */
const SPACE_NONE = '__none__'

/**
 * 会话内切换空间：有活跃会话时下拉反映会话**实际绑定**的空间，
 * 切换走 PATCH（后端落库 space_switch 分隔线消息）；
 * 草稿态维持原行为 —— 只写 selectedSpaceId 偏好，影响下一个新建会话。
 */
const headerSpace = computed<string>({
  get: () => {
    const sid = chatStore.hasConversation
      ? chatStore.currentConversation?.space_id ?? null
      : chatStore.selectedSpaceId
    return sid ?? SPACE_NONE
  },
  set: (val) => {
    const sid = val === SPACE_NONE ? null : val
    if (!chatStore.hasConversation) {
      chatStore.selectedSpaceId = sid
      return
    }
    // 失败时 store 已写 error.value（全局错误展示兜底）；
    // computed get 仍读会话真实 space_id，UI 自动回弹到切换前的值。
    chatStore.switchConversationSpace(sid).catch(() => {})
  },
})
</script>

<template>
  <div class="chat-header">
    <!-- 左侧：对话标题 -->
    <div class="flex items-center gap-2 min-w-0 flex-1">
      <h1 class="chat-header-title">
        {{ conversationTitle }}
      </h1>
      <span v-if="isRunning" class="chat-header-running">
        <span class="chat-header-running-dot" />
        运行中
      </span>
    </div>

    <!-- 右侧：空间 / 角色 -->
    <div class="flex items-center gap-2 shrink-0">
      <ResolvedSourceBadge
        v-if="resolvedProvider"
        :source="resolvedProvider.source"
        :chain="resolvedProvider.chain"
      />

      <!-- 无任何空间：不渲染空白下拉，引导去创建（也可不选空间直接对话） -->
      <RouterLink
        v-if="noSpacesExist"
        to="/spaces"
        class="chat-header-create-space"
        title="空间绑定代码仓库后，AI 才能回答代码相关问题；也可以不选空间直接对话"
      >
        <span class="icon-[lucide--folder-plus] text-[13px]" />
        <span>暂无空间，去创建</span>
      </RouterLink>

      <Select v-else v-model="headerSpace" :disabled="isRunning">
        <SelectTrigger
          class="w-44 h-8 text-xs border-border/40 bg-transparent shadow-none"
          :title="isRunning ? '对话进行中，无法切换空间' : '切换空间后，后续回答将基于新空间'"
        >
          <span class="icon-[lucide--folder-git-2] text-[13px] text-muted-foreground/70 shrink-0" />
          <SelectValue placeholder="选择空间" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem :value="SPACE_NONE">
            通用对话（不绑定空间）
          </SelectItem>
          <SelectItem
            v-for="space in spacesStore.spaces"
            :key="space.id"
            :value="space.id"
          >
            {{ space.name }}
          </SelectItem>
        </SelectContent>
      </Select>

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

      <!-- 反馈入口：/chat 不渲染全局顶栏，这里补一个右上角入口 -->
      <FeedbackHeaderButton />
    </div>
  </div>
</template>

<style scoped>
.chat-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  height: 4rem;
  padding: 0 1.25rem;
  border-bottom: 1px solid hsl(var(--border) / 0.3);
  background: hsl(0 0% 100% / 0.6);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  flex-shrink: 0;
}

.chat-header-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.9375rem;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: hsl(215 28% 17%);
}

.chat-header-running {
  display: inline-flex;
  align-items: center;
  gap: 0.3125rem;
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
  background: hsl(38 92% 50% / 0.1);
  color: hsl(38 80% 36%);
  font-size: 0.6875rem;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.chat-header-create-space {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  height: 2rem;
  padding: 0 0.75rem;
  border-radius: 0.5rem;
  border: 1px dashed hsl(168 76% 42% / 0.4);
  color: hsl(168 76% 34%);
  font-size: 0.75rem;
  font-weight: 500;
  white-space: nowrap;
  transition:
    background-color 0.15s ease,
    border-color 0.15s ease;
}

.chat-header-create-space:hover {
  background: hsl(168 76% 42% / 0.07);
  border-color: hsl(168 76% 42% / 0.6);
}

.chat-header-running-dot {
  width: 0.375rem;
  height: 0.375rem;
  border-radius: 9999px;
  background: hsl(38 92% 50%);
  animation: header-pulse 1.6s ease infinite;
}

@keyframes header-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}
</style>
