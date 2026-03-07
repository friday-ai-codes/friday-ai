<route lang="yaml">
meta:
 layout: false
</route>
<script setup lang="ts">
const chatStore = useChatStore
const projectsStore = useProjectsStore
onMounted(async => {
 await Promise.all([
 chatStore.fetchConversations,
 projectsStore.fetchProjects,
 ])
})
</script>
<template>
 <div class="h-screen flex bg-background overflow-hidden">
 <!-- 侧边栏 -->
 <ChatSidebar />
 <!-- 主内容区 -->
 <div class="flex-1 flex flex-col min-w-0">
 <ChatHeader />
 <ChatMessageArea />
 <ChatInput />
 </div>
 </div>
</template>
