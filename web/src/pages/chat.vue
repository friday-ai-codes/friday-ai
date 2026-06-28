<route lang="yaml">
meta:
  title: AI 对话
</route>

<script setup lang="ts">
import ChatConversationList from '~/components/chat/ChatConversationList.vue'
import ChatHeader from '~/components/chat/ChatHeader.vue'
import ChatInput from '~/components/chat/ChatInput.vue'
import ChatMessageArea from '~/components/chat/ChatMessageArea.vue'

const chatStore = useChatStore()
const spacesStore = useSpacesStore()
const repositoriesStore = useRepositoriesStore()

// Chat 数据懒加载：首次进入 /chat 时初始化
onMounted(async () => {
  // 与项目作战室共用同一 store：进入全局 /chat 时解除项目作用域过滤，恢复全量列表。
  chatStore.exitProjectScope()
  await Promise.all([
    chatStore.fetchConversations(),
    spacesStore.fetchSpaces(),
  ])
  // 自愈：localStorage 持久化的 chat-space-id 可能指向已删除的空间
  // （空间被删 / 切换后端数据库）。残留会让首条消息创建对话时后端报
  // 「空间不存在」。fetchSpaces 成功后校验一次，失效则清空回通用对话。
  if (
    chatStore.selectedSpaceId
    && !spacesStore.spaces.some(s => s.id === chatStore.selectedSpaceId)
  ) {
    chatStore.selectedSpaceId = null
  }
  // 有可用空间时默认选中第一个，避免顶部下拉长期显示空占位
  if (!chatStore.selectedSpaceId && spacesStore.spaces.length > 0) {
    chatStore.selectedSpaceId = spacesStore.spaces[0]!.id
  }
  await chatStore.restoreFromURL()
  // 实时同步：全局对话页也建立 ws/chat/ 连接，本人的会话（含项目共享）实时一致。
  chatStore.connectRealtime()
  if (chatStore.notificationsEnabled)
    chatStore.requestNotificationPermission()
  // 惰性拉取仓库列表：供 ChatMessageBubble 把工具调用里的 repository_id
  // 渲染成仓库名称（诉求 2/3 的兜底来源，relevance 候选缺失时使用）。
  if (repositoriesStore.repositories.length === 0)
    repositoriesStore.fetchRepositories().catch(() => {})
})

// 飞书导出可用性：跟随当前会话的空间（草稿态跟随顶部所选空间）。
// 未配置时 ChatMessageBubble 隐藏「导出到飞书」入口。
watch(
  () => chatStore.currentConversation?.space_id ?? chatStore.selectedSpaceId,
  spaceId => chatStore.refreshFeishuExportAvailability(spaceId),
  { immediate: true },
)
</script>

<template>
  <!-- h-full + min-h-0：高度由布局层（default.vue chat 分支 h-screen）锁定。
       此前用 flex-1 + h-screen，在父级 flex column 里 h-screen 被内容撑破，
       会话列表一多整页（含顶部条）跟着滚动。 -->
  <div class="flex min-w-0 h-full min-h-0 overflow-hidden">
    <!-- 二级栏：会话列表（入口重构：从全局侧边栏迁入 chat 页内部，
         全局侧边栏保持工作台导航不变） -->
    <ChatConversationList />

    <!--
      UX 重设计（260423-lum）：chat 路径 Provider/模型选择已折叠到 ChatInput
      底部 model-selector。ChatHeader 不再消费 conversation-id / current-credential-id
      / current-model / message-count / waiting-for-input；@pin-confirmed listener
      迁移到 ChatInput，且参数升级为 (credentialId, model) 双字段，路由到
      chatStore.patchConversationProviderAndModel（单次 PATCH 双字段，避免中间态）。
      :resolved-provider 暂不接（继承自 260423-kxt；ChatHeader 默认 null + v-if 兜底）。
    -->
    <div class="flex-1 flex flex-col min-w-0 h-full">
      <ChatHeader />
      <div class="flex-1 min-h-0 relative">
        <ChatMessageArea />
        <ChatInput
          class="chat-input-float"
          @pin-confirmed="chatStore.patchConversationProviderAndModel"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-input-float {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 10;
  pointer-events: none;
}
</style>
