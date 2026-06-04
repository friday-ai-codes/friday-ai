<script setup lang="ts">
/**
 * Access Tokens 区容器（Phase）
 *
 * 仿 ProviderSettings 编排：onMounted 拉取列表、新建表单 Dialog、一次性明文
 * reveal Dialog、吊销 AlertDialog 二次确认；错误走 useErrorHandler，成功走 useToast。
 *
 * 安全核心（T-）：明文唯一驻留点是本组件的 `plaintext` 内存 ref；
 * 它仅由 store.createToken 返回值赋入，绝不经任何持久层；reveal Dialog 关闭即清空。
 */
import type { AccessTokenCreatePayload, AccessTokenDto } from '~/types/accessToken'
import { onMounted, ref, watch } from 'vue'
import {
 AlertDialog,
 AlertDialogAction,
 AlertDialogCancel,
 AlertDialogContent,
 AlertDialogDescription,
 AlertDialogFooter,
 AlertDialogHeader,
 AlertDialogTitle,
} from '~/components/ui/alert-dialog'
import { Button } from '~/components/ui/button'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import { useAccessTokenStore } from '~/stores/accessTokens'
import AccessTokenForm from './AccessTokenForm.vue'
import AccessTokenListTable from './AccessTokenListTable.vue'
import AccessTokenRevealDialog from './AccessTokenRevealDialog.vue'
const store = useAccessTokenStore
const { handleError } = useErrorHandler
const toast = useToast
// ==== 本地状态 ====
const formOpen = ref(false)
const revealOpen = ref(false)
/** 明文唯一驻留点：瞬态内存 ref，绝不进任何持久层。 */
const plaintext = ref<string | null>(null)
const revokeTarget = ref<AccessTokenDto | null>(null)
const revokeConfirmOpen = ref(false)
// reveal 弹窗关闭即清空明文内存，杜绝残留
watch(revealOpen, (v) => {
 if (!v)
 plaintext.value = null
})
onMounted( => {
 store.fetchTokens.catch(e => handleError(e, '加载 Access Token'))
})
// ==== Handlers ====
async function onCreate(payload: AccessTokenCreatePayload) {
 try {
 plaintext.value = await store.createToken(payload)
 formOpen.value = false
 revealOpen.value = true
 }
 catch (e) {
 handleError(e, '创建 Token')
 }
}
function onRevokeRequest(t: AccessTokenDto) {
 revokeTarget.value = t
 revokeConfirmOpen.value = true
}
async function onConfirmRevoke {
 if (!revokeTarget.value)
 return
 try {
 await store.revokeToken(revokeTarget.value.id)
 toast.success('Token 已吊销')
 }
 catch (e) {
 handleError(e, '吊销 Token')
 }
 finally {
 revokeConfirmOpen.value = false
 revokeTarget.value = null
 }
}
</script>
<template>
 <section class="space-y-6">
 <!-- 区头部 -->
 <header class="flex items-start justify-between gap-4">
 <div class="space-y-1">
 <h2 class="text-base font-semibold">
 Access Tokens
 </h2>
 <p class="text-xs text-muted-foreground">
 用于外部 MCP / Skill 调用的访问令牌；创建后明文仅显示一次。
 </p>
 </div>
 <Button variant="default" @click="formOpen = true">
 <span class="icon-[lucide--plus] mr-1 w-4" aria-hidden="true" />
 新建 Token
 </Button>
 </header>
 <!-- 列表 -->
 <AccessTokenListTable:tokens="store.tokens" @revoke="onRevokeRequest" />
 <!-- 新建表单 Dialog -->
 <Dialog v-model:open="formOpen">
 <DialogContent class="flex max-w-lg flex-col gap-0 overflow-hidden ">
 <DialogHeader class="border-b border-border/50 px-6 py-4 text-left">
 <DialogTitle class="text-base font-semibold">
 新建 Access Token
 </DialogTitle>
 <DialogDescription class="text-xs text-muted-foreground">
 填写名称与过期策略，创建后明文仅显示一次。
 </DialogDescription>
 </DialogHeader>
 <AccessTokenForm @submit="onCreate" @cancel="formOpen = false" />
 </DialogContent>
 </Dialog>
 <!-- 一次性明文 reveal Dialog -->
 <AccessTokenRevealDialog v-model:open="revealOpen":token="plaintext" />
 <!-- 吊销二次确认 -->
 <AlertDialog v-model:open="revokeConfirmOpen">
 <AlertDialogContent>
 <AlertDialogHeader>
 <AlertDialogTitle>吊销此 Token？</AlertDialogTitle>
 <AlertDialogDescription>
 吊销后该 Token 立即失效且不可恢复，确认吊销？
 </AlertDialogDescription>
 </AlertDialogHeader>
 <AlertDialogFooter>
 <AlertDialogCancel>取消</AlertDialogCancel>
 <AlertDialogAction
 class="bg-destructive text-destructive-foreground hover:bg-destructive/90"
 @click="onConfirmRevoke"
 >
 吊销
 </AlertDialogAction>
 </AlertDialogFooter>
 </AlertDialogContent>
 </AlertDialog>
 </section>
</template>
