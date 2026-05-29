<script setup lang="ts">
import { useLocalStorage } from '@vueuse/core'
import { IndexStatus } from '~/api/repositories'
import KnowledgeBaseSection from '~/components/codegraph/KnowledgeBaseSection.vue'
import StatusBadge from '~/components/common/StatusBadge.vue'
import IndexedFilesPanel from '~/components/repository/IndexedFilesPanel.vue'
import IndexHistoryList from '~/components/repository/IndexHistoryList.vue'
import IndexProgressTimeline from '~/components/repository/IndexProgressTimeline.vue'
import IndexStatsPanel from '~/components/repository/IndexStatsPanel.vue'
import RepositoryGraphCard from '~/components/repository/RepositoryGraphCard.vue'
import RepositoryIndexCard from '~/components/repository/RepositoryIndexCard.vue'
import { Button } from '~/components/ui/button'
import {
 Tabs,
 TabsContent,
 TabsList,
 TabsTrigger,
} from '~/components/ui/tabs'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
import { useKnowledgeOverview } from '~/composables/useKnowledgeOverview'
import { formatRelativeTime } from '~/lib/relativeTime'
const props = defineProps<{
 repositoryId: string
 gitUrl: string
}>
const activeTab = useLocalStorage<'index' | 'graph' | 'explore' | 'details'>(`kb-tab-${props.repositoryId}`, 'index')
const {
 loading,
 checking,
 errorMessage,
 repo,
 indexStatus,
 health,
 graphRagStatus,
 structuredGraphCounts,
 structuredGraphTotal,
 freshnessState,
 latestRemoteHeadSha,
 refreshFreshness,
 loadAll,
} = useKnowledgeOverview(toRef( => props.repositoryId))
onMounted(loadAll)
const localSha = computed( => repo.value?.last_indexed_commit_sha?.slice(0, 7) || '—')
const remoteSha = computed( => (latestRemoteHeadSha.value || repo.value?.remote_head_sha || '').slice(0, 7) || '—')
const freshnessLabel = computed( => {
 switch (freshnessState.value) {
 case 'fresh': return '索引最新'
 case 'stale': return '索引过期'
 case 'not_indexed': return '尚未索引'
 default: return '远端未知'
 }
})
const freshnessIcon = computed( => {
 switch (freshnessState.value) {
 case 'fresh': return 'icon-[lucide--check-circle-2] text-emerald-500'
 case 'stale': return 'icon-[lucide--alert-triangle] text-amber-500'
 case 'not_indexed': return 'icon-[lucide--circle-dashed] text-muted-foreground'
 default: return 'icon-[lucide--help-circle] text-muted-foreground'
 }
})
const graphRagStatusLabel = computed( => {
 const s = graphRagStatus.value?.status
 switch (s) {
 case 'completed': return '已同步'
 case 'running': return '同步中'
 case 'failed': return '同步失败'
 case 'skipped': return '已跳过'
 case 'pending': return '等待中'
 default: return '—'
 }
})
const pipelineSteps = computed( => [
 {
 id: 'vector',
 step: 1,
 title: '向量索引',
 subtitle: '语义检索 · Qdrant',
 icon: 'icon-[lucide--database]',
 status: indexStatus.value?.index_status ?? 'not_indexed',
 statusType: 'index' as const,
 metric: health.value?.points_count != null
 ? `${health.value.points_count.toLocaleString} 向量`: indexStatus.value?.index_status === IndexStatus.INDEXED ? '已就绪': '—',
 time: repo.value?.last_indexed_at ? formatRelativeTime(repo.value.last_indexed_at): null,
 timeLabel: '最后索引',
 freshness: freshnessLabel.value,
 freshnessIcon: freshnessIcon.value,
 },
 {
 id: 'structured',
 step: 2,
 title: '结构化图谱',
 subtitle: '符号 · 导入 · 调用 · 端点',
 icon: 'icon-[lucide--git-graph]',
 status: repo.value?.graph_build_status ?? 'idle',
 statusType: 'graph' as const,
 metric: structuredGraphCounts.value
 ? `${structuredGraphTotal.value.toLocaleString} 关系`: '—',
 metricDetail: structuredGraphCounts.value
 ? `${structuredGraphCounts.value.symbols} 符号 · ${structuredGraphCounts.value.calls} 调用`: null,
 time: repo.value?.graph_last_built_at ? formatRelativeTime(repo.value.graph_last_built_at): null,
 timeLabel: '最近构建',
 },
 {
 id: 'graphrag',
 step: 3,
 title: 'GraphRAG',
 subtitle: '代码块语义关联',
 icon: 'icon-[lucide--share-2]',
 status: graphRagStatus.value?.status ?? 'pending',
 statusType: 'graph' as const,
 metric: typeof graphRagStatus.value?.edge_count === 'number'
 ? `${graphRagStatus.value.edge_count.toLocaleString} 语义边`: '—',
 time: graphRagStatus.value?.last_synced_at
 ? formatRelativeTime(graphRagStatus.value.last_synced_at): null,
 timeLabel: '最近同步',
 statusLabel: graphRagStatusLabel.value,
 },
])
</script>
<template>
 <div class="card overflow-hidden">
 <!-- Header -->
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between gap-3">
 <div class="flex items-center gap-2 min-w-0">
 <div class=".5 rounded-lg bg-primary/10 shrink-0">
 <span class="icon-[lucide--layers] text-primary" />
 </div>
 <div class="min-w-0">
 <h3 class="text-sm font-semibold text-foreground">
 知识库
 </h3>
 <p class="text-xs text-muted-foreground truncate">
 向量索引 → 结构化图谱 → GraphRAG 语义关联
 </p>
 </div>
 </div>
 <Button
 variant="outline"
 size="sm"
 class=" text-xs shrink-0":disabled="checking"
 @click="refreshFreshness"
 >
 <span:class="checking ? 'icon-[lucide--loader-circle] animate-spin mr-1.5': 'icon-[lucide--refresh-cw] mr-1.5'" />
 {{ checking ? '检查中...': '立即检查' }}
 </Button>
 </div>
 <!-- Pipeline Overview -->
 <div
 class=" border-b border-border/50":class="freshnessState === 'stale' ? 'bg-amber-500/3': 'bg-muted/20'"
 >
 <div v-if="loading" class="flex items-center justify-center gap-2 py-6">
 <span class="icon-[lucide--loader-circle] text-xl text-primary animate-spin" />
 <span class="text-sm text-muted-foreground">加载知识库状态...</span>
 </div>
 <template v-else>
 <!-- Freshness banner (compact) -->
 <div
 v-if="freshnessState !== 'fresh' && freshnessState !== 'not_indexed'"
 class="mb-4 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs":class="freshnessState === 'stale'
 ? 'border-amber-500/30 bg-amber-500/5 text-amber-700 dark:text-amber-300': 'border-border/50 bg-muted/30 text-muted-foreground'"
 >
 <span:class="freshnessIcon" />
 <span>{{ freshnessLabel }}</span>
 <template v-if="freshnessState === 'stale' && localSha !== '—'">
 <span class="text-muted-foreground">·</span>
 <span class="font-mono">{{ localSha }}</span>
 <span class="icon-[lucide--arrow-right] text-[10px]" />
 <span class="font-mono text-amber-600">{{ remoteSha }}</span>
 </template>
 </div>
 <!-- 3-step pipeline -->
 <div class="grid gap-3 lg:grid-cols-3">
 <div
 v-for="(step, idx) in pipelineSteps":key="step.id"
 class="relative rounded-xl border border-border/50 bg-card transition-colors hover:border-primary/20"
 >
 <!-- connector arrow (desktop) -->
 <span
 v-if="idx < pipelineSteps.length - 1"
 class="hidden lg:block absolute -right-3 top-1/2 -translate-y-1/2 z-10 icon-[lucide--chevron-right] text-muted-foreground/40 text-sm"
 />
 <div class="flex items-start justify-between gap-2 mb-3">
 <div class="flex items-center gap-2 min-w-0">
 <span
 class="flex w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary"
 >
 {{ step.step }}
 </span>
 <div class="min-w-0">
 <p class="text-sm font-medium text-foreground leading-tight">
 {{ step.title }}
 </p>
 <p class="text-[11px] text-muted-foreground truncate">
 {{ step.subtitle }}
 </p>
 </div>
 </div>
 <StatusBadge:type="step.statusType":status="step.status"
 size="sm":show-icon="true"
 />
 </div>
 <div class="space-y-1">
 <p class="text-lg font-semibold tabular-nums text-foreground">
 {{ step.metric }}
 </p>
 <p v-if="step.metricDetail" class="text-[11px] text-muted-foreground">
 {{ step.metricDetail }}
 </p>
 <div class="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
 <span v-if="step.freshness" class="inline-flex items-center gap-1">
 <span:class="step.freshnessIcon" class="text-xs" />
 {{ step.freshness }}
 </span>
 <span v-if="step.time">
 {{ step.timeLabel }} {{ step.time }}
 </span>
 <TooltipProvider v-if="step.id === 'graphrag'":delay-duration="300">
 <Tooltip>
 <TooltipTrigger as-child>
 <button type="button" class="inline-flex items-center gap-0.5 text-primary/70 hover:text-primary transition-colors cursor-pointer">
 <span class="icon-[lucide--info] text-[10px]" />
 与结构化图谱区别
 </button>
 </TooltipTrigger>
 <TooltipContent class="max-w-xs text-xs leading-relaxed">
 <p>
 <strong>结构化图谱</strong>记录 AST 解析的符号/导入/调用关系；
 <strong>GraphRAG</strong> 基于代码块生成语义关联边，用于检索扩展。
 两者独立构建，数量与时间可能不同。
 </p>
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </div>
 </div>
 </div>
 </div>
 <p v-if="errorMessage" class="mt-3 text-xs text-destructive">
 {{ errorMessage }}
 </p>
 </template>
 </div>
 <!-- Tabs -->
 <Tabs v-model="activeTab" class=" pt-4">
 <TabsList class="mb-4 w-full justify-start overflow-x-auto">
 <TabsTrigger value="index" class="gap-1.5">
 <span class="icon-[lucide--database] text-xs" />
 索引管理
 </TabsTrigger>
 <TabsTrigger value="graph" class="gap-1.5">
 <span class="icon-[lucide--hammer] text-xs" />
 图谱构建
 </TabsTrigger>
 <TabsTrigger value="explore" class="gap-1.5">
 <span class="icon-[lucide--search] text-xs" />
 图谱浏览
 </TabsTrigger>
 <TabsTrigger value="details" class="gap-1.5">
 <span class="icon-[lucide--bar-chart-3] text-xs" />
 统计与历史
 </TabsTrigger>
 </TabsList>
 <TabsContent value="index" class="mt-0 space-y-4">
 <RepositoryIndexCard:repository-id="repositoryId" embedded />
 <IndexProgressTimeline
 v-if="indexStatus?.index_status === IndexStatus.INDEXING":repository-id="repositoryId":index-history-id="null":changed-files="{}":is-indexing="true"
 />
 </TabsContent>
 <TabsContent value="graph" class="mt-0">
 <RepositoryGraphCard:repository-id="repositoryId" embedded />
 </TabsContent>
 <TabsContent value="explore" class="mt-0">
 <KnowledgeBaseSection:repository-id="repositoryId" embedded />
 </TabsContent>
 <TabsContent value="details" class="mt-0 space-y-4">
 <IndexStatsPanel:repository-id="repositoryId" />
 <IndexedFilesPanel:repository-id="repositoryId":git-url="gitUrl" />
 <IndexHistoryList:repository-id="repositoryId":git-url="gitUrl" />
 </TabsContent>
 </Tabs>
 </div>
</template>
