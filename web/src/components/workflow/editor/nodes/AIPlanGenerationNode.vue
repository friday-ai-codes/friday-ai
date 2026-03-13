<script setup lang="ts">
/**
 * AIPlanGenerationNode - AI 方案生成节点的画布组件
 *
 * 在工作流画布上展示节点内部的工作流水线和 AI 能力标签，
 * 让用户直观了解节点的处理过程。
 */
import { Brain, RefreshCcw, Search, Send, Sparkles } from 'lucide-vue-next'
import BaseWorkflowNode from './BaseWorkflowNode.vue'
defineProps<{
 id: string
 data: {
 name: string
 nodeType: string
 disabled?: boolean
 [key: string]: unknown
 }
 selected?: boolean
}>
const steps = [
 { icon: Brain, label: '需求分析' },
 { icon: Search, label: '跨仓代码检索' },
 { icon: Sparkles, label: '方案生成' },
 { icon: RefreshCcw, label: '验证 & 重试' },
 { icon: Send, label: '飞书推送' },
]
const capabilities = ['ReAct', 'RAG', '多轮迭代']
</script>
<template>
 <BaseWorkflowNode:id="id":data="data":selected="selected">
 <template #content>
 <!-- 分隔线 -->
 <div class="border-t border-violet-500/15 -mx-1 mb-2" />
 <!-- 内部流水线步骤 -->
 <div class="relative pl-3 space-y-1.5 mb-2">
 <!-- 左侧连接线 -->
 <div class="absolute left-[5px] top-1 bottom-1 w-px bg-gradient-to-b from-violet-500/30 via-purple-400/20 to-transparent" />
 <div
 v-for="(step, i) in steps":key="i"
 class="relative flex items-center gap-1.5"
 >
 <!-- 步骤圆点 -->
 <div class="absolute -left-3 w-[7px] h-[7px] rounded-full bg-violet-500/40 ring-1 ring-violet-500/20" />
 <component:is="step.icon" class="w-3 text-violet-400/60 shrink-0" />
 <span class="text-[11px] text-muted-foreground leading-none">{{ step.label }}</span>
 </div>
 </div>
 <!-- 能力标签 -->
 <div class="flex flex-wrap gap-1">
 <span
 v-for="cap in capabilities":key="cap"
 class="text-[10px] leading-none px-1.5 py-0.5 rounded-full
 bg-violet-500/10 text-violet-400/80 border border-violet-500/15"
 >
 {{ cap }}
 </span>
 </div>
 </template>
 </BaseWorkflowNode>
</template>
