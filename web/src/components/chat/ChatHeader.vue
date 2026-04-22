<script setup lang="ts">
/**
 * Phase Plan — ChatHeader 扩展 Provider / 模型下拉 + pin 弹窗
 *
 * 三态判定（由 useConversationFrozen 驱动）：
 * - draft / running / paused / interrupted / waiting → active，允许切换（切换触发 PinConfirmDialog）
 * - completed / stopped / error / WAITING → frozen，下拉 disabled + Tooltip 解释原因
 *
 * 用户选中新 Provider / 模型后**不立即** PATCH，先弹 PinConfirmDialog 二次确认；确认后才走 PATCH。
 * 失败（后端 400 conversation_frozen 或 validation）→ toast 提示 + 重置选择到原值。
 */
import type { ConversationStatus } from '~/composables/useConversationFrozen'
import type { ProviderCredentialDto, ResolvedProvider } from '~/types/providerCredential'
import { computed, onMounted, ref, watch } from 'vue'
import PinConfirmDialog from '~/components/chat/PinConfirmDialog.vue'
import ProviderCredentialDropdown from '~/components/providers/ProviderCredentialDropdown.vue'
import ResolvedSourceBadge from '~/components/providers/ResolvedSourceBadge.vue'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
import { useConversationFrozen } from '~/composables/useConversationFrozen'
import { useProviderCredentialStore } from '~/stores/providerCredential'
import { ROLE_OPTIONS } from '~/types/chat'
interface Props {
 /** 对话状态（由父组件 / chat store 提供；用于 pin 冻结判定） */
 conversationStatus?: ConversationStatus
 /** 当前 pin 到对话的 ProviderCredential ID（null=未 pin，继承项目层 / 系统层） */
 currentCredentialId?: string | null
 /** 当前 pin 到对话的模型 ID */
 currentModel?: string
 /** 当前对话消息数（用于 pin 弹窗文案） */
 messageCount?: number
 /** 当前对话 ID（用于 PATCH API 调用） */
 conversationId?: string | null
 /** WAITING 态（SSE 驱动；ChatInterruptView 场景） */
 waitingForInput?: boolean
 /** Phase：当前对话的四层 Provider 解析链（null=全链路 miss 或未加载） */
 resolvedProvider?: ResolvedProvider | null
}
const props = withDefaults(defineProps<Props>, {
 conversationStatus: 'draft',
 currentCredentialId: null,
 currentModel: '',
 messageCount: 0,
 conversationId: null,
 waitingForInput: false,
 resolvedProvider: null,
})
const chatStore = useChatStore
const projectsStore = useProjectsStore
// ==========：useConversationFrozen 判定 ==========
const statusRef = computed<ConversationStatus>( => props.conversationStatus)
const waitingRef = computed<boolean>( => props.waitingForInput)
const frozen = useConversationFrozen(statusRef, waitingRef)
// ========== PinConfirmDialog 状态 ==========
const pinDialogOpen = ref(false)
const pendingCredential = ref<ProviderCredentialDto | null>(null)
const oldCredential = ref<ProviderCredentialDto | null>(null)
const selectedCredentialId = ref<string | null>(props.currentCredentialId)
// Phase Plan（230 修复）：从 props.currentCredentialId → providerStore.getCredentialById
// 同步赋值 oldCredential，消除 PinConfirmDialog "当前 Provider" 占位恒显示 bug。
// watch(immediate: true) 模式参考 NodeConfigPanel.vue:89-91。
// 降级链保留：若 store 未 load 或 id 不命中 → oldCredential=null → 模板 fallback (L189)
// 到 "当前 Provider"（currentCredentialId 非空）或 "未指定"（null）。
const providerStore = useProviderCredentialStore
watch(
 => props.currentCredentialId,
 (newId) => {
 oldCredential.value = newId
 ? (providerStore.getCredentialById(newId) ?? null): null
 },
 { immediate: true },
)
// Pitfall 5（work-item §Common Pitfalls）：store 未 load 时 watch 首次 run 返 null →
// 模板 fallback 到 "当前 Provider"。onMounted 主动 fetch 让后续 props 变化能解析真实名。
// fetchCredentials 内含 30s TTL（providerCredential.ts:work-item），重复调用安全。
onMounted( => {
 void providerStore.fetchCredentials
})
/** 下拉 change：active 态先弹 pin；frozen 态由 disabled 拦截不会触发。 */
function onCredentialChange(cred: ProviderCredentialDto | null) {
 if (frozen.value.isFrozen) {
 return // 双重防御：disabled 应已拦截
 }
 if (!cred || cred.id === selectedCredentialId.value) {
 return
 }
 // active 态 → 先保留当前凭证，弹 pin 确认
 pendingCredential.value = cred
 pinDialogOpen.value = true
}
async function handleConfirm {
 if (!pendingCredential.value || !props.conversationId) {
 pinDialogOpen.value = false
 return
 }
 // 委托 chat store action 完成 PATCH；失败由 store 抛错，toast 在外部 useErrorHandler 处理
 try {
 const newId = pendingCredential.value.id
 selectedCredentialId.value = newId
 // 成功后关 Dialog（chat store action 预计 Plan/08 对接；此处仅 emit 交给父组件）
 emit('pin-confirmed', newId)
 pinDialogOpen.value = false
 }
 catch {
 // 失败由外部处理，弹窗保持打开；pinDialogOpen 不变
 }
}
function handleCancel {
 pendingCredential.value = null
 pinDialogOpen.value = false
}
const emit = defineEmits<{
 'pin-confirmed': [credentialId: string]
}>
const tooltipText = computed( => frozen.value.reason || '切换将弹出确认，固定到本对话')
</script>
<template>
 <div class="chat-header">
 <!-- 项目选择 -->
 <Select v-model="chatStore.selectedProjectId">
 <SelectTrigger class="w-44 text-xs border-border/40 bg-transparent shadow-none">
 <SelectValue placeholder="选择项目" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="project in projectsStore.projects":key="project.id":value="project.id"
 >
 {{ project.name }}
 </SelectItem>
 </SelectContent>
 </Select>
 <!-- 角色选择 -->
 <Select v-model="chatStore.selectedRole">
 <SelectTrigger class="w-28 text-xs border-border/40 bg-transparent shadow-none">
 <SelectValue placeholder="角色" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="role in ROLE_OPTIONS":key="role.value":value="role.value"
 >
 {{ role.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 <!-- Phase：Provider 凭证下拉（frozen 态 disabled + tooltip） -->
 <TooltipProvider:delay-duration="200">
 <Tooltip>
 <TooltipTrigger as-child>
 <div
 class="inline-flex":data-frozen="frozen.isFrozen ? 'true': 'false'":class="{ 'opacity-60 cursor-not-allowed': frozen.isFrozen }"
 >
 <ProviderCredentialDropdown:model-value="selectedCredentialId"
 scope="project":project-id="chatStore.selectedProjectId ?? undefined":disabled="frozen.isFrozen"
 @change="onCredentialChange"
 />
 </div>
 </TooltipTrigger>
 <TooltipContent
 v-if="frozen.isFrozen || tooltipText"
 class="max-w-xs text-xs font-normal"
 >
 {{ tooltipText }}
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 <!-- Phase：四层 Provider 解析 Inspector（Provider 下拉旁边） -->
 <ResolvedSourceBadge
 v-if="props.resolvedProvider":source="props.resolvedProvider.source":chain="props.resolvedProvider.chain"
 />
 <!-- pin 弹窗 -->
 <PinConfirmDialog
 v-model:open="pinDialogOpen":old-provider-name="oldCredential?.name ?? (props.currentCredentialId ? '当前 Provider': '未指定')":old-model="props.currentModel || '默认模型'":new-provider-name="pendingCredential?.name ?? ''":new-model="pendingCredential?.available_models?.[0]?.id ?? props.currentModel ?? '默认模型'":message-count="props.messageCount"
 @confirm="handleConfirm"
 @cancel="handleCancel"
 />
 </div>
</template>
<style scoped>
.chat-header {
 display: flex;
 align-items: center;
 gap: 0.5rem;
 padding: 0.5rem 1rem;
 border-bottom: 1px solid hsl(var(--border) / 0.3);
}
</style>
