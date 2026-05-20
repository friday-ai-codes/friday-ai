<!--
 @deprecated Phase 起改用 TechPlanCard.vue。本组件保留为薄包装，
 兼容外部引用（旧 props 签名）；v26.1 删除。新代码请直接 import TechPlanCard。
-->
<script setup lang="ts">
import TechPlanCard from './TechPlanCard.vue'
const props = defineProps<{
 sessionId: string
 techPlan: string
 affectedFiles: Array<{ path?: string, file_path?: string, change_type: string }>
 status: 'draft' | 'confirmed' | 'running' | 'awaiting_confirmation' | 'completed' | 'failed'
 isConfirming: boolean
 branchName?: string
}>
const emit = defineEmits<{
 confirm: [sessionId: string, branchName?: string]
}>
function handleConfirm(_planId: string, sessionId: string | undefined, branchName?: string) {
 if (sessionId)
 emit('confirm', sessionId, branchName)
}
</script>
<template>
 <TechPlanCard
 plan-id="":session-id="props.sessionId":tech-plan="props.techPlan":affected-files="props.affectedFiles":status="props.status":is-confirming="props.isConfirming":branch-name="props.branchName"
 @confirm="handleConfirm"
 />
</template>
