<script setup lang="ts">
import {
 Variable, GitBranch, GitPullRequest,
 Sparkles, SquareCode, SearchCode, FileCode, FileText,
 CircleCheck, Terminal, Cog,
} from 'lucide-vue-next'
import { computed, type Component } from 'vue'
import BaseWorkflowNode from './BaseWorkflowNode.vue'
const props = defineProps<{
 id: string
 data: {
 name: string
 nodeType: string
 description?: string
 disabled?: boolean
 [key: string]: unknown
 }
 selected?: boolean
}>
const iconMap: Record<string, Component> = {
 variable_extractor: Variable,
 create_branch: GitBranch,
 create_pr: GitPullRequest,
 ai_prompt: Sparkles,
 ai_coding_dispatcher: SquareCode,
 ai_variable_extractor: Sparkles,
 context_retrieval: SearchCode,
 ai_technical_plan: FileCode,
 ai_plan_generation: FileText,
 ai_plan_approval: CircleCheck,
 ai_coding: Terminal,
 ai_code_review: SearchCode,
}
const icon = computed( => iconMap[props.data.nodeType] ?? Cog)
</script>
<template>
 <BaseWorkflowNode:id="id":data="data":selected="selected">
 <template #icon>
 <component:is="icon" class="w-4 " />
 </template>
 <template v-if="data.description" #content>
 <p class="text-xs text-muted-foreground">{{ data.description }}</p>
 </template>
 </BaseWorkflowNode>
</template>
