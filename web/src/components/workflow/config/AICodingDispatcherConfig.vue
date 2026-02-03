<script setup lang="ts">
import type { AICodingDispatcherConfig } from '~/types/workflow'
import { Switch } from '~/components/ui/switch'
import { useConfigModel } from '~/composables/useConfigModel'
import { aiCodingDispatcherConfigSchema } from '~/types/workflow'
// ============================================================================
// Props & Emits
// ============================================================================
interface Props {
 config: AICodingDispatcherConfig
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'update:config', value: AICodingDispatcherConfig): void
}>
// ============================================================================
// Config Model
// ============================================================================
const { field } = useConfigModel({
 config: => props.config,
 emit: v => emit('update:config', v),
 schema: aiCodingDispatcherConfigSchema,
})
// 任务合并配置
const mergeSameBranch = field('merge_same_branch', true)
</script>
<template>
 <div class="space-y-4">
 <!-- 严格模式说明 -->
 <div
 class=" rounded-xl bg-gradient-to-br from-amber-500/10 to-orange-500/5
 border border-amber-200/50 dark:border-amber-800/50"
 >
 <div class="flex items-start gap-3">
 <span class="icon-[lucide--info] text-lg text-amber-500 mt-0.5" />
 <div class="text-sm">
 <p class="font-medium text-amber-700 dark:text-amber-400">
 严格模式
 </p>
 <p class="text-muted-foreground mt-1">
 此节点将严格按照上游技术方案节点的 execution_plan 创建编码任务，
 不进行 AI 自主分析。请确保上游已配置技术方案节点。
 </p>
 </div>
 </div>
 </div>
 <!-- 合并同仓库任务 -->
 <div
 class="flex items-center justify-between rounded-xl
 bg-card/70 backdrop-blur-sm border border-border/50"
 >
 <div class="flex items-center gap-3">
 <div class=" rounded-lg bg-gradient-to-br from-blue-500/20 to-cyan-500/10">
 <span class="icon-[lucide--git-merge] text-xl text-blue-500" />
 </div>
 <div>
 <label class="text-sm font-medium">
 合并同仓库任务
 </label>
 <p class="text-xs text-muted-foreground">
 将目标仓库和分支相同的任务合并为一个编码任务
 </p>
 </div>
 </div>
 <Switch v-model="mergeSameBranch" />
 </div>
 <!-- 节点行为说明 -->
 <div class=" bg-secondary/50 rounded-xl text-sm space-y-1">
 <p class="font-medium">
 此节点将：
 </p>
 <ul class="text-xs text-muted-foreground space-y-1 list-disc list-inside">
 <li>从上游技术方案节点读取 execution_plan</li>
 <li>验证技术方案的有效性</li>
 <li>按配置选项合并相同仓库/分支的任务</li>
 <li>并行创建 CodingTask 记录供后续处理</li>
 </ul>
 </div>
 </div>
</template>
