<script setup lang="ts">
/**
 * Phase Plan — ContextExceededCard
 *
 * 上下文超限结构化引导卡片：SSE ERROR event `{code: "context_window_exceeded"}`
 * 触发时，chat store 写入 lastContextExceeded ref；ChatMessageArea 把本组件挂入
 * 系统消息插槽，展示结构化 payload + 3 动作按钮（按风险倒序）。
 *
 * 按钮语义（ / work item §I-6）：按风险倒序排列，后端 recommended_actions
 * 数组顺序驱动渲染（trim_prompt → switch_model → cleanup_history）：
 * - trim_prompt "精简 system prompt"（低风险 primary）→ router.push('/prompts/')
 * - switch_model "换大 context 模型"（中风险 outline）→ emit('switch-model-click')，
 * 上层打开 ChatHeader 的 ModelSelect 下拉
 * - cleanup_history "清理对话历史"（不可逆 destructive）→ emit('cleanup-click')，
 * 打开 CleanupDialog（硬删，不可恢复）
 *
 * Style: Sub2API Clean Card（非玻璃拟态），与 ProviderCredentialMissingCard 同源。
 */
import { useRouter } from 'vue-router'
import { Button } from '~/components/ui/button'
type ActionId = 'trim_prompt' | 'switch_model' | 'cleanup_history'
type ActionType = 'navigate' | 'dialog'
interface RecommendedAction {
 id: string
 label: string
 action_type: ActionType | string
 target: string
}
const props = defineProps<{
 estimatedTokens: number
 maxTokens: number
 exceededBy: number
 model: string
 recommendedActions: RecommendedAction
}>
const emit = defineEmits<{
 'cleanup-click':
 'switch-model-click':
}>
const router = useRouter
function formatNum(n: number): string {
 return Number.isFinite(n) ? n.toLocaleString('en-US'): String(n)
}
function handleActionClick(action: RecommendedAction): void {
 const id = action.id as ActionId
 if (id === 'cleanup_history') {
 emit('cleanup-click')
 return
 }
 if (id === 'switch_model') {
 emit('switch-model-click')
 return
 }
 if (id === 'trim_prompt') {
 if (router && typeof router.push === 'function')
 router.push(action.target || '/prompts/')
 }
}
function variantForAction(id: string): 'default' | 'outline' | 'destructive' {
 if (id === 'trim_prompt')
 return 'default'
 if (id === 'switch_model')
 return 'outline'
 if (id === 'cleanup_history')
 return 'destructive'
 return 'outline'
}
</script>
<template>
 <div class="card my-12" role="alert" aria-live="polite">
 <div class="flex items-start gap-2">
 <span class="icon-[lucide--triangle-alert] text-amber-500 text-xl shrink-0 mt-0.5" aria-hidden="true" />
 <div class="flex-1 space-y-2">
 <h3 class="text-base font-semibold">
 上下文已超出模型上限
 </h3>
 <p class="text-sm text-muted-foreground leading-6">
 当前估算 <span class="font-mono text-foreground">{{ formatNum(props.estimatedTokens) }}</span> tokens，
 模型 <span class="font-mono text-foreground">{{ props.model }}</span>
 上限 <span class="font-mono text-foreground">{{ formatNum(props.maxTokens) }}</span> tokens，
 超出 <span class="font-mono text-destructive">+{{ formatNum(props.exceededBy) }}</span> tokens。请从下方 3 个动作中选择一种缓解策略。
 </p>
 <div class="flex flex-wrap items-center gap-2 pt-2">
 <Button
 v-for="action in props.recommendedActions":key="action.id":variant="variantForAction(action.id)":aria-label="action.label"
 @click="handleActionClick(action)"
 >
 {{ action.label }}
 </Button>
 </div>
 </div>
 </div>
 </div>
</template>
