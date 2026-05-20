<!--
 @deprecated Phase 起改用 TechPlanCard.vue。本组件保留为薄包装，
 兼容外部引用（旧 props 签名）；v26.1 删除。新代码请直接 import TechPlanCard。
 Phase：在仓库行头部追加 RelevanceBadge 让 score 立即可见；
 本卡片本身不直接渲染仓库列表（由 TechPlanCard 内的 CodingSessionStatusRow
 渲染），badge 集成实际发生在 CodingSessionStatusRow / RepoMultiSelector。
-->
<script setup lang="ts">
import { computed } from 'vue'
import RelevanceBadge from './RelevanceBadge.vue'
import TechPlanCard from './TechPlanCard.vue'
const props = defineProps<{
 sessionId: string
 techPlan: string
 affectedFiles: Array<{ path?: string, file_path?: string, change_type: string }>
 status: 'draft' | 'confirmed' | 'running' | 'awaiting_confirmation' | 'completed' | 'failed'
 isConfirming: boolean
 branchName?: string
 /**
 * Phase 可选 prop —— 当上层（ChatMessageBubble）能提供单一
 * 目标 repository_id + conversationId 时，本卡片头部渲染 RelevanceBadge
 * 立即可见。不传则不渲染（向后兼容旧调用方）。
 */
 repositoryId?: string
 conversationId?: string
}>
const emit = defineEmits<{
 confirm: [sessionId: string, branchName?: string]
}>
const effectiveConversationId = computed( => props.conversationId || '')
function handleConfirm(_planId: string, sessionId: string | undefined, branchName?: string) {
 if (sessionId)
 emit('confirm', sessionId, branchName)
}
</script>
<template>
 <div class="space-y-1">
 <!-- Phase：仓库相关性徽章（store 无 trace 时优雅降级不渲染） -->
 <div
 v-if="props.repositoryId && effectiveConversationId"
 class="flex items-center gap-2 px-3 pt-1"
 >
 <RelevanceBadge:repository-id="props.repositoryId":conversation-id="effectiveConversationId"
 />
 </div>
 <TechPlanCard
 plan-id="":session-id="props.sessionId":tech-plan="props.techPlan":affected-files="props.affectedFiles":status="props.status":is-confirming="props.isConfirming":branch-name="props.branchName"
 @confirm="handleConfirm"
 />
 </div>
</template>
