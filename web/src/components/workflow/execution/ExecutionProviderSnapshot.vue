<script setup lang="ts">
/**
 * ExecutionProviderSnapshot — Execution 详情页 AI 节点 Provider 快照
 *
 * Props:
 * - nodeId: AI 节点 ID（用于 aria-controls 关联折叠区）
 * - snapshot: 快照对象 | null（null 表示本节点未记录快照）
 * - canReplay: Replay 是否可用（上层页面根据 execution.status 计算）
 *
 * Emits:
 * - replay: 用户点击 "使用此快照重放" 按钮
 *
 * 设计要点：
 * - Clean Card（`.card `）风格，严禁玻璃拟态光晕层（work item L33 Clean Card 纠偏）
 * - 折叠态（默认）：显示 provider_type 中文名 + model；展开态：source + Replay 按钮
 * - snapshot=null：渲染 warning Badge + 说明文案 + Replay disabled + tooltip 三重承载
 * （title / aria-label / TooltipContent；happy-dom 下 Portal 不挂 DOM，沿用 Plan 模式）
 *
 * Analog: ProviderHealthBadge.vue（Badge + Tooltip 模板）+ PATTERNS §Pattern 2 + §S-5 Clean Card
 */
import type { ChainEntry } from '~/types/providerCredential'
import { computed, ref } from 'vue'
import ResolvedSourceBadge from '~/components/providers/ResolvedSourceBadge.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
type ProviderType = 'anthropic' | 'openai_responses' | 'openai_chat' | 'gemini' | 'ollama'
type SourceLayer = 'node' | 'conversation' | 'project' | 'system'
interface NodeSnapshot {
 provider_type: ProviderType
 model: string
 source: SourceLayer
 credential_id: string | null
 /** Phase：可选的四层解析链（Plan 扩展；旧快照无此字段则空数组） */
 chain?: ChainEntry
}
const props = defineProps<{
 nodeId: string
 snapshot: NodeSnapshot | null
 canReplay: boolean
}>
const emit = defineEmits<{
 replay:
}>
const expanded = ref(false)
/** Provider 中文名映射（work item §Copywriting L285） */
const PROVIDER_LABEL: Record<ProviderType, string> = {
 anthropic: 'Anthropic',
 openai_responses: 'OpenAI（Responses）',
 openai_chat: 'OpenAI（Chat）',
 gemini: 'Gemini',
 ollama: 'Ollama',
}
/** source layer 中文映射（work item §Copywriting L287） */
const SOURCE_LABEL: Record<SourceLayer, string> = {
 node: '节点配置',
 conversation: '对话固定',
 project: '项目覆盖',
 system: '系统默认',
}
const providerLabel = computed( => {
 if (!props.snapshot)
 return ''
 return PROVIDER_LABEL[props.snapshot.provider_type] ?? props.snapshot.provider_type
})
const sourceLabel = computed( => {
 if (!props.snapshot)
 return ''
 return SOURCE_LABEL[props.snapshot.source] ?? props.snapshot.source
})
/** Replay 可用性：必须同时有 snapshot + 外部 canReplay=true */
const replayEnabled = computed( => props.snapshot !== null && props.canReplay)
/** Tooltip / disabled 文案（三重承载）*/
const replayTooltipText = computed( => {
 if (props.snapshot === null)
 return '历史 Execution 未记录快照，无法稳定 Replay'
 return '使用快照的 Provider / 模型重放此节点（不受当前项目默认修改影响）'
})
function toggle {
 expanded.value = !expanded.value
}
function onReplay {
 if (!replayEnabled.value)
 return
 emit('replay')
}
</script>
<template>
 <section class="card space-y-4" role="region" aria-label="Provider 快照">
 <!-- 标题 + 折叠按钮 -->
 <header class="flex items-center justify-between">
 <div>
 <h4 class="text-base font-semibold">
 Provider 快照
 </h4>
 <p class="text-xs text-muted-foreground mt-1">
 该节点在本次执行启动时使用的 Provider 与模型，Replay 将保持一致
 </p>
 </div>
 <Button
 variant="ghost"
 size="sm":aria-expanded="expanded":aria-controls="`snap-detail-${nodeId}`":aria-label="expanded ? '折叠': '展开'"
 @click="toggle"
 >
 {{ expanded ? '折叠': '展开' }}
 </Button>
 </header>
 <!-- 折叠态概要 / 未快照态 -->
 <div v-if="snapshot" class="flex items-center gap-2 text-sm">
 <Badge variant="outline">
 {{ providerLabel }}
 </Badge>
 <span class="font-mono text-foreground">{{ snapshot.model }}</span>
 </div>
 <div v-else class="flex items-start gap-2">
 <Badge variant="warning">
 未快照
 </Badge>
 <p class="text-sm text-muted-foreground flex-1">
 本节点未记录 Provider 快照，Replay 将实时解析当前项目默认 Provider，结果可能与历史执行不同
 </p>
 </div>
 <!-- 展开态详情（仅字段 dl 受折叠控制；Replay 按钮永远可见以保持 A11y + 降级提示） -->
 <div
 v-show="expanded && snapshot":id="`snap-detail-${nodeId}`"
 class="pt-2 border-t border-border/40"
 >
 <!-- Phase：四层 Provider 解析 Inspector（snapshot 带 chain 时渲染） -->
 <div
 v-if="snapshot && snapshot.chain && snapshot.chain.length > 0"
 class="mb-3"
 >
 <ResolvedSourceBadge:source="snapshot.source":chain="snapshot.chain"
 />
 </div>
 <dl v-if="snapshot" class="text-sm space-y-2">
 <div class="flex gap-2">
 <dt class="text-muted-foreground w-20 shrink-0">
 Provider
 </dt>
 <dd>{{ providerLabel }}</dd>
 </div>
 <div class="flex gap-2">
 <dt class="text-muted-foreground w-20 shrink-0">
 Model
 </dt>
 <dd class="font-mono">
 {{ snapshot.model }}
 </dd>
 </div>
 <div class="flex gap-2">
 <dt class="text-muted-foreground w-20 shrink-0">
 Source
 </dt>
 <dd>{{ sourceLabel }}</dd>
 </div>
 </dl>
 </div>
 <!-- Replay 按钮（始终可见，snapshot=null 时 disabled + tooltip 解释） -->
 <div class="pt-2">
 <TooltipProvider:delay-duration="150">
 <Tooltip>
 <TooltipTrigger as-child>
 <Button
 variant="default"
 size="sm":disabled="!replayEnabled":title="replayTooltipText":aria-label="`使用此快照重放（${replayTooltipText}）`"
 @click="onReplay"
 >
 使用此快照重放
 </Button>
 </TooltipTrigger>
 <TooltipContent class="max-w-xs text-xs font-normal">
 {{ replayTooltipText }}
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </div>
 </section>
</template>
