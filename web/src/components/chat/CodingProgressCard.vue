<script setup lang="ts">
/**
 * 编码进度卡片 -- 在对话消息流中展示编码步骤的实时进度。
 *
 * 每个步骤有三种状态：pending / running / done，通过不同图标和样式区分。
 * 使用 TransitionGroup 让步骤状态切换有视觉反馈。
 * 增强展示：详细文件列表 Collapsible + 工具调用摘要 + 向后兼容旧版 payload。
 */
import { ref } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
const props = defineProps<{
 steps: Array<{ name: string; status: 'pending' | 'running' | 'done' }>
 modifiedFilesCount: number
 isComplete: boolean
 modifiedFiles?: Array<{ path: string; change_type: string }>
 recentToolCalls?: Array<{ tool: string; summary: string }>
}>
const filesExpanded = ref(false)
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
 <!-- 底部：摘要统计 + 详细文件列表 + 工具调用 -->
 <div class="px-4 pb-3 space-y-2">
 <!-- 摘要统计行 -->
 <p v-if="modifiedFilesCount > 0 || (modifiedFiles && modifiedFiles.length > 0)" class="text-xs text-muted-foreground">
 已修改 {{ modifiedFiles?.length || modifiedFilesCount }} 个文件
 <template v-if="recentToolCalls && recentToolCalls.length > 0">
 · 最近操作: {{ recentToolCalls[recentToolCalls.length - 1].summary }}
 </template>
 </p>
 <!-- 详细文件列表 Collapsible -->
 <Collapsible v-if="modifiedFiles && modifiedFiles.length > 0" v-model:open="filesExpanded">
 <CollapsibleTrigger class="text-xs text-muted-foreground cursor-pointer hover:text-foreground flex items-center gap-1">
 <span:class="filesExpanded ? 'icon-[lucide--chevron-down]': 'icon-[lucide--chevron-right]'" class="text-[12px]" />
 {{ filesExpanded ? '收起文件列表': '查看文件列表' }}
 </CollapsibleTrigger>
 <CollapsibleContent class="mt-1.5 space-y-0.5">
 <div
 v-for="file in modifiedFiles":key="file.path"
 class="text-xs text-muted-foreground flex items-center gap-1.5 py-0.5"
 >
 <code class="truncate">{{ file.path }}</code>
 <Badge
 variant="outline":class="[
 'text-[10px] px-1 py-0',
 file.change_type === 'added' ? 'text-emerald-500 border-emerald-500/30 bg-emerald-500/5':
 file.change_type === 'deleted' ? 'text-destructive border-destructive/30 bg-destructive/5':
 'text-blue-500 border-blue-500/30 bg-blue-500/5'
 ]"
 >
 {{ file.change_type }}
 </Badge>
 </div>
 </CollapsibleContent>
 </Collapsible>
 <!-- 工具调用摘要 (: 最近 3-5 条) -->
 <div v-if="recentToolCalls && recentToolCalls.length > 0" class="space-y-0.5">
 <div
 v-for="(call, idx) in recentToolCalls.slice(-5)":key="idx"
 class="text-xs text-muted-foreground flex items-center gap-1"
 >
 <span class="icon-[lucide--terminal] text-[10px]" />
 {{ call.summary }}
 </div>
 </div>
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
