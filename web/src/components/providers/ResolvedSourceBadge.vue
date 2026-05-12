<script setup lang="ts">
/**
 * ResolvedSourceBadge — Phase / 四层 Provider 解析 Inspector。
 *
 * Props:
 * - source: winning layer（node/conversation/project/system）
 * - chain: 4 层解析条目（顺序固定 node → conversation → project → system）
 * - size?: 'sm' | 'md'（默认 md）
 *
 * 视觉契约（work item §Source-hue token + §Dimension 3）:
 * - Badge 本身 variant="outline"（不叠加背景色）
 * - hue 色仅作用于内部 icon：
 * node → lucide--layers + text-violet-600
 * conversation → lucide--message-circle + text-blue-600
 * project → lucide--folder-lock + text-teal-600
 * system → lucide--globe + text-slate-500
 * - hover/focus 打开 tooltip：展开完整优先级链表（4 行）
 * winning 层：text-primary font-semibold + 末尾 ✓（lucide--check）
 * 被覆盖层（value 存在但 active=false）：line-through text-muted-foreground
 * value 不存在：灰色 —
 * - 禁用 backdrop-blur（Clean Card 纠偏 work item L33）
 *
 * Analog: ProviderHealthBadge.vue（同目录，Phase 四态模板）+ PATTERNS §Pattern 2
 */
import type { ChainEntry, SourceLayer } from '~/types/providerCredential'
import { Badge } from '~/components/ui/badge'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
interface Props {
 source: SourceLayer
 chain: ChainEntry
 size?: 'sm' | 'md'
}
const props = withDefaults(defineProps<Props>, {
 size: 'md',
})
/**
 * hue icon class（图标 class + 颜色 class 合并）。
 *
 * work item §Source-hue token：Badge outline + 内部 icon 着色，
 * 保证 A11y 对比度 + 不违反 DESIGN.md "禁止 Badge 叠色"约束。
 */
const hueIconMap: Record<SourceLayer, string> = {
 node: 'icon-[lucide--layers] text-violet-600',
 conversation: 'icon-[lucide--message-circle] text-blue-600',
 project: 'icon-[lucide--folder-lock] text-teal-600',
 system: 'icon-[lucide--globe] text-slate-500',
}
/** 四层中文标签（work item §Copywriting L287 node → 节点配置 映射）。 */
const labelMap: Record<SourceLayer, string> = {
 node: '节点配置',
 conversation: '对话固定',
 project: '空间覆盖',
 system: '系统默认',
}
/** 链表每行的 value 文本：provider_type [+ / model]（work item §Copywriting + Typography mono）。 */
function formatEntryValue(entry: ChainEntry): string {
 if (!entry.provider_type) {
 return '—'
 }
 if (entry.model) {
 return `${entry.provider_type} / ${entry.model}`
 }
 return entry.provider_type
}
</script>
<template>
 <span class="inline-flex items-center relative">
 <TooltipProvider:delay-duration="150">
 <Tooltip>
 <TooltipTrigger as-child>
 <Badge
 variant="outline"
 role="button":aria-label="`当前生效：${labelMap[props.source]} · 点击展开优先级链`"
 class="inline-flex items-center gap-1 px-2 py-0.5 cursor-pointer select-none":class="{ 'text-xs': props.size === 'sm' }"
 >
 <span:class="hueIconMap[props.source]"
 class="w-3 shrink-0"
 aria-hidden="true"
 />
 <span class="text-xs font-normal">{{ labelMap[props.source] }}</span>
 </Badge>
 </TooltipTrigger>
 <TooltipContent class="max-w-sm text-xs font-normal">
 <div
 v-for="entry in props.chain":key="entry.layer"
 class="flex items-center gap-2 py-0.5"
 >
 <span:class="hueIconMap[entry.layer]"
 class="w-3 shrink-0"
 aria-hidden="true"
 />
 <span
 class="flex-1":class="{
 'text-primary font-semibold': entry.active,
 'line-through text-muted-foreground': entry.provider_type && !entry.active,
 'text-muted-foreground': !entry.provider_type,
 }"
 >
 {{ labelMap[entry.layer] }}: {{ formatEntryValue(entry) }}
 </span>
 <span
 v-if="entry.active"
 class="icon-[lucide--check] w-3 text-primary shrink-0"
 aria-hidden="true"
 title="当前生效层"
 />
 </div>
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 <!--
 A11y sr-only 链表 — 屏幕阅读器 + 测试双用（work item §I-5 契约）。
 Tooltip Portal 在 happy-dom 下不挂 DOM；sr-only 镜像保证 chain 契约可被
 wrapper.html 断言（沿用 Plan 三重承载模式：title / aria / DOM）。
 -->
 <span class="sr-only" aria-hidden="true" data-testid="resolved-source-chain-sr">
 <span
 v-for="entry in props.chain":key="`sr-${entry.layer}`":class="{
 'text-primary font-semibold': entry.active,
 'line-through text-muted-foreground': entry.provider_type && !entry.active,
 }"
 >
 <span:class="hueIconMap[entry.layer]" />
 {{ labelMap[entry.layer] }}: {{ formatEntryValue(entry) }}
 <span v-if="entry.active" class="icon-[lucide--check]">✓</span>
 </span>
 </span>
 </span>
</template>
