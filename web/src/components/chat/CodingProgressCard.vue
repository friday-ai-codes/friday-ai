<script setup lang="ts">
/**
 * 编码进度卡片 -- 在对话消息流中展示编码步骤的实时进度。
 *
 * 每个步骤有三种状态：pending / running / done，通过不同图标和样式区分。
 * 使用 TransitionGroup 让步骤状态切换有视觉反馈。
 */
defineProps<{
 steps: Array<{ name: string; status: 'pending' | 'running' | 'done' }>
 modifiedFilesCount: number
 isComplete: boolean
}>
</script>
<template>
 <div class="card mt-2 animate-fade-in">
 <!-- 头部 -->
 <div class="px-4 py-3 border-b border-border/50 flex items-center gap-2">
 <span v-if="!isComplete" class="icon-[lucide--loader-2] text-primary animate-spin" />
 <span v-else class="icon-[lucide--check-circle] text-emerald-500" />
 <span class="text-sm font-semibold">{{ isComplete ? '编码完成': '正在编码...' }}</span>
 </div>
 <!-- 步骤列表 -->
 <div class=" space-y-2">
 <TransitionGroup name="step">
 <div
 v-for="(step, i) in steps":key="step.name + i"
 class="flex items-center gap-2 text-sm"
 >
 <!-- 步骤图标 -->
 <span
 v-if="step.status === 'pending'"
 class="icon-[lucide--circle] text-muted-foreground/50 text-[14px]"
 />
 <span
 v-else-if="step.status === 'running'"
 class="icon-[lucide--loader-2] text-primary animate-spin text-[14px]"
 />
 <span v-else class="icon-[lucide--check-circle] text-emerald-500 text-[14px]" />
 <!-- 步骤文字 -->
 <span:class="{
 'text-muted-foreground': step.status === 'pending',
 'text-foreground font-semibold': step.status === 'running',
 'text-muted-foreground line-through': step.status === 'done',
 }"
 >
 {{ step.name }}
 </span>
 </div>
 </TransitionGroup>
 </div>
 <!-- 底部：文件变更数 -->
 <div v-if="modifiedFilesCount > 0" class="px-4 pb-3 text-xs text-muted-foreground">
 {{ modifiedFilesCount }} 个文件变更
 </div>
 </div>
</template>
<style scoped>
.step-enter-active {
 transition: all 0.3s ease-out;
}
.step-enter-from {
 opacity: 0;
 transform: translateY(4px);
}
</style>
