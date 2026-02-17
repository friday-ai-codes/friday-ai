<script setup lang="ts">
import { computed, ref } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import {
 Collapsible,
 CollapsibleContent,
 CollapsibleTrigger,
} from '~/components/ui/collapsible'
/**
 * AICodeReviewPanel - AI 代码审查执行结果展示面板
 *
 * 功能：
 * - 展示审查通过/未通过状态标记
 * - 概览统计（critical / warning / info 数量）
 * - 总体摘要文本
 * - 按 MR 分组的审查报告，每个 MR 内按维度分节展示 issue 列表
 * - 每个 issue 展示 severity 标签 + 问题描述 + 建议修改
 * - 结论区域
 */
interface Props {
 nodeExecution: {
 id: string
 status: string
 node_type: string
 output_data?: Record<string, any>
 }
}
const props = defineProps<Props>
// 从 output_data 提取数据
const reviewReport = computed(: Record<string, any> =>
 props.nodeExecution.output_data?.review_report || {},
)
const issuesCount = computed(: number =>
 props.nodeExecution.output_data?.issues_count || 0,
)
const severityBreakdown = computed(: { critical: number, warning: number, info: number } =>
 props.nodeExecution.output_data?.severity_breakdown || { critical: 0, warning: 0, info: 0 },
)
const approved = computed(: boolean | undefined =>
 props.nodeExecution.output_data?.approved,
)
const mrReviews = computed(: Record<string, any> =>
 reviewReport.value.mr_reviews ||,
)
// 状态判断
const isRunning = computed( => props.nodeExecution.status === 'running')
const isCompleted = computed( => props.nodeExecution.status === 'completed')
const isFailed = computed( => props.nodeExecution.status === 'failed')
// 折叠面板状态
const expandedMRs = ref<Record<number, boolean>>({})
const expandedIssues = ref<Record<string, boolean>>({})
function toggleMR(index: number) {
 expandedMRs.value[index] = !expandedMRs.value[index]
}
function toggleIssue(key: string) {
 expandedIssues.value[key] = !expandedIssues.value[key]
}
// severity 样式映射
const severityStyles: Record<string, { bg: string, text: string, border: string }> = {
 critical: { bg: 'bg-red-500/10', text: 'text-red-600', border: 'border-red-500/20' },
 warning: { bg: 'bg-amber-500/10', text: 'text-amber-600', border: 'border-amber-500/20' },
 info: { bg: 'bg-blue-500/10', text: 'text-blue-600', border: 'border-blue-500/20' },
}
function getSeverityStyle(severity: string) {
 return severityStyles[severity] || severityStyles.info
}
// 维度图标映射
const dimensionIcons: Record<string, { icon: string, label: string }> = {
 code_quality: { icon: 'icon-[lucide--code-2]', label: '代码质量' },
 security: { icon: 'icon-[lucide--shield-alert]', label: '安全性' },
 plan_compliance: { icon: 'icon-[lucide--clipboard-check]', label: '方案符合度' },
}
function getDimensionMeta(dimension: string) {
 return dimensionIcons[dimension] || { icon: 'icon-[lucide--circle-dot]', label: dimension }
}
// 按维度分组 issues
function groupIssuesByDimension(issues: Record<string, any>): Record<string, Record<string, any>> {
 const groups: Record<string, Record<string, any>> = {}
 for (const issue of issues) {
 const dim = issue.dimension || 'other'
 if (!groups[dim])
 groups[dim] =
 groups[dim].push(issue)
 }
 return groups
}
</script>
<template>
 <Card class="rounded-2xl bg-card/80 backdrop-blur-sm border border-border/50 overflow-hidden">
 <!-- Header -->
 <CardHeader class="pb-3">
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-3">
 <div class="bg-gradient-to-br from-amber-500/20 to-orange-400/10 rounded-lg ">
 <span class="icon-[lucide--search-code] w-5 text-amber-500" />
 </div>
 <CardTitle class="text-base">
 AI 代码审查
 </CardTitle>
 </div>
 <!-- Status Badge -->
 <Badge
 v-if="isRunning"
 class="bg-amber-500/10 text-amber-600 border-amber-500/20 animate-pulse"
 >
 <span class="icon-[lucide--loader-2] w-3 mr-1 animate-spin" />
 审查中
 </Badge>
 <Badge
 v-else-if="isCompleted && approved === true"
 class="bg-emerald-500/10 text-emerald-600 border-emerald-500/20"
 >
 <span class="icon-[lucide--check-circle] w-3 mr-1" />
 审查通过
 </Badge>
 <Badge
 v-else-if="isCompleted && approved === false"
 class="bg-red-500/10 text-red-600 border-red-500/20"
 >
 <span class="icon-[lucide--x-circle] w-3 mr-1" />
 审查未通过
 </Badge>
 <Badge
 v-else-if="isFailed"
 class="bg-red-500/10 text-red-600 border-red-500/20"
 >
 <span class="icon-[lucide--x-circle] w-3 mr-1" />
 审查失败
 </Badge>
 </div>
 </CardHeader>
 <CardContent class="space-y-4">
 <!-- Severity Overview Stats -->
 <div
 v-if="issuesCount > 0 || isCompleted"
 class="grid grid-cols-3 gap-3"
 >
 <div class="text-center rounded-xl bg-red-500/5 border border-red-500/10">
 <div class="text-lg font-bold text-red-600">
 {{ severityBreakdown.critical || 0 }}
 </div>
 <div class="text-xs text-muted-foreground">
 Critical
 </div>
 </div>
 <div class="text-center rounded-xl bg-amber-500/5 border border-amber-500/10">
 <div class="text-lg font-bold text-amber-600">
 {{ severityBreakdown.warning || 0 }}
 </div>
 <div class="text-xs text-muted-foreground">
 Warning
 </div>
 </div>
 <div class="text-center rounded-xl bg-blue-500/5 border border-blue-500/10">
 <div class="text-lg font-bold text-blue-600">
 {{ severityBreakdown.info || 0 }}
 </div>
 <div class="text-xs text-muted-foreground">
 Info
 </div>
 </div>
 </div>
 <!-- Summary -->
 <div v-if="reviewReport.summary" class=" rounded-xl bg-muted/30 border border-border/30">
 <div class="text-xs font-medium text-muted-foreground mb-1.5">
 总体摘要
 </div>
 <p class="text-sm leading-relaxed whitespace-pre-wrap">
 {{ reviewReport.summary }}
 </p>
 </div>
 <!-- MR Reviews (collapsible per MR) -->
 <div v-if="mrReviews.length > 0" class="space-y-2">
 <Collapsible
 v-for="(mr, mrIdx) in mrReviews":key="mrIdx":open="expandedMRs[mrIdx] !== false"
 @update:open=" => toggleMR(mrIdx)"
 >
 <CollapsibleTrigger class="flex items-center justify-between w-full py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors group">
 <span class="flex items-center gap-2">
 <span class="icon-[lucide--git-pull-request] w-4 text-amber-500" />
 {{ mr.repository || mr.repo_name || `MR ${mrIdx + 1}` }}
 <Badge variant="secondary" class="text-[10px] px-1.5 py-0">
 {{ (mr.issues || ).length }} issues
 </Badge>
 </span>
 <span
 class="icon-[lucide--chevron-down] w-4 transition-transform duration-200":class="{ 'rotate-180': expandedMRs[mrIdx] !== false }"
 />
 </CollapsibleTrigger>
 <CollapsibleContent class="space-y-3 pt-2">
 <!-- Group by dimension -->
 <div
 v-for="(issues, dimension) in groupIssuesByDimension(mr.issues || )":key="dimension"
 class="space-y-1.5"
 >
 <!-- Dimension header -->
 <div class="flex items-center gap-1.5 text-xs font-medium text-muted-foreground py-1">
 <span class="w-3.5 .5 text-amber-500":class="[getDimensionMeta(dimension as string).icon]" />
 {{ getDimensionMeta(dimension as string).label }}
 <Badge variant="outline" class="text-[10px] px-1 py-0 ml-1">
 {{ issues.length }}
 </Badge>
 </div>
 <!-- Issue cards -->
 <div
 v-for="(issue, issueIdx) in issues":key="issueIdx"
 class="rounded-xl border border-border/40 hover:border-primary/30 hover:shadow-sm transition-all cursor-pointer"
 @click="toggleIssue(`${mrIdx}-${dimension}-${issueIdx}`)"
 >
 <!-- Collapsed: severity + truncated description -->
 <div class="flex items-center gap-2 .5">
 <Badge
 class="text-[10px] px-1.5 py-0 shrink-0":class="[
 getSeverityStyle(issue.severity).bg,
 getSeverityStyle(issue.severity).text,
 getSeverityStyle(issue.severity).border,
 ]"
 >
 {{ issue.severity }}
 </Badge>
 <span class="text-sm truncate">
 {{ issue.description || issue.message || '未知问题' }}
 </span>
 </div>
 <!-- Expanded: full details -->
 <div
 v-if="expandedIssues[`${mrIdx}-${dimension}-${issueIdx}`]"
 class="px-2.5 pb-2.5 space-y-2 border-t border-border/30 pt-2"
 >
 <!-- Full description -->
 <p class="text-sm leading-relaxed whitespace-pre-wrap">
 {{ issue.description || issue.message }}
 </p>
 <!-- File path -->
 <div v-if="issue.file_path || issue.file" class="flex items-center gap-1.5 text-xs text-muted-foreground">
 <span class="icon-[lucide--file] w-3 " />
 <code class="font-mono px-1 py-0.5 rounded bg-muted">{{ issue.file_path || issue.file }}</code>
 <span v-if="issue.line" class="text-muted-foreground">:{{ issue.line }}</span>
 </div>
 <!-- Suggestion -->
 <div v-if="issue.suggestion || issue.fix" class=" rounded-lg bg-emerald-500/5 border border-emerald-500/10">
 <div class="flex items-center gap-1 text-xs font-medium text-emerald-600 mb-1">
 <span class="icon-[lucide--lightbulb] w-3 " />
 建议修改
 </div>
 <p class="text-xs leading-relaxed whitespace-pre-wrap text-muted-foreground">
 {{ issue.suggestion || issue.fix }}
 </p>
 </div>
 </div>
 </div>
 </div>
 </CollapsibleContent>
 </Collapsible>
 </div>
 <!-- Conclusion -->
 <div v-if="reviewReport.conclusion" class=" rounded-xl bg-muted/30 border border-border/30">
 <div class="text-xs font-medium text-muted-foreground mb-1.5">
 结论
 </div>
 <p class="text-sm leading-relaxed whitespace-pre-wrap">
 {{ reviewReport.conclusion }}
 </p>
 </div>
 </CardContent>
 </Card>
</template>
