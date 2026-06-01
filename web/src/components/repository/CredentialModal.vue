<script setup lang="ts">
/**
 * CredentialModal — 仓库凭证管理弹窗（Phase）
 *
 * 把原独立路由页 `pages/repositories/[id]/credential.vue` 的凭证表单逻辑迁入详情页弹窗：
 * - 复用现网 shadcn Dialog 壳（参考 GraphSearchModal 的 v-model:open 模式）+ Glassmorphism。
 * - 查看已配置凭证（认证类型 / Git 用户 / 创建时间），Access Token 始终脱敏，绝不回显明文。
 * - 通过现有凭证 API（`repositoriesApi.setAccessToken`，不改后端）配置 / 更新 Access Token。
 *
 * 数据同步：保存成功后 emit('saved')，由详情页 index.vue 重新拉取凭证刷新「凭证已配置」徽标。
 *
 * 注：现有凭证 API 仅支持 Access Token（无 SSH Key 写入端点），故表单仅提供 Access Token；
 * 已存在的 ssh_key 类型凭证以只读方式展示认证类型徽标。
 */
import type { GitCredential } from '~/types'
import { repositoriesApi } from '~/api/repositories'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
import { useErrorHandler } from '~/composables/useErrorHandler'
const props = defineProps<{
 repositoryId: string
 credential?: GitCredential | null
}>
const emit = defineEmits<{
 saved:
}>
const open = defineModel<boolean>('open', { default: false })
const { handleError } = useErrorHandler
const { success } = useToast
// 表单状态
const accessToken = ref('')
const gitUserName = ref('Friday Codes AI Agent')
const gitUserEmail = ref('ai@friday.codes')
const submitting = ref(false)
// 是否处于编辑（输入新 Token）模式；无凭证时直接进入编辑
const editing = ref(false)
const isSshKey = computed( => props.credential?.auth_type === 'ssh_key')
function resetForm {
 accessToken.value = ''
 gitUserName.value = props.credential?.git_user_name || 'Friday Codes AI Agent'
 gitUserEmail.value = props.credential?.git_user_email || 'ai@friday.codes'
 editing.value = !props.credential
}
// 弹窗每次打开时重置表单，避免残留上次输入
watch(open, (isOpen) => {
 if (isOpen)
 resetForm
})
async function handleAccessTokenUpdate {
 if (!accessToken.value.trim) {
 handleError(new Error('请输入新的 Access Token'), '保存凭证')
 return
 }
 submitting.value = true
 try {
 await repositoriesApi.setAccessToken(props.repositoryId, {
 token: accessToken.value,
 git_user_name: gitUserName.value,
 git_user_email: gitUserEmail.value,
 })
 success('保存成功', props.credential ? 'Access Token 已更新': 'Access Token 已配置')
 accessToken.value = ''
 emit('saved')
 open.value = false
 }
 catch (e: unknown) {
 // handleError 仅提取错误消息（脱敏），绝不回显明文 Token
 handleError(e, '保存 Access Token')
 }
 finally {
 submitting.value = false
 }
}
function formatDate(dateStr: string) {
 return new Date(dateStr).toLocaleString('zh-CN')
}
</script>
<template>
 <Dialog v-model:open="open">
 <DialogContent class="sm:max-w-lg bg-card/85 backdrop-blur-xl border-border/50">
 <DialogHeader>
 <DialogTitle class="flex items-center gap-2">
 <span class="icon-[lucide--key] text-primary" />
 凭证配置
 </DialogTitle>
 <DialogDescription>
 配置 Git 访问凭证（Access Token 已脱敏，不会显示原文）
 </DialogDescription>
 </DialogHeader>
 <!-- 已有凭证：脱敏展示 -->
 <div v-if="credential && !editing" class="space-y-4">
 <div class="grid gap-4">
 <div>
 <Label class="text-muted-foreground">认证类型</Label>
 <div class="mt-2">
 <Badge variant="outline" class="px-3 py-1">
 <span:class="isSshKey ? 'icon-[lucide--terminal] mr-2': 'icon-[lucide--key] mr-2'" />
 {{ isSshKey ? 'SSH 密钥': 'Access Token' }}
 </Badge>
 </div>
 </div>
 <Separator class="bg-border/50" />
 <div>
 <Label class="text-muted-foreground">凭证</Label>
 <p class="mt-2 text-sm font-mono text-muted-foreground bg-muted/50 px-4 py-3 rounded-xl border border-border/50">
 ••••••••••••••••
 </p>
 <p class="text-xs text-muted-foreground mt-2">
 出于安全考虑，凭证不会显示原文。如需更新请点击下方按钮。
 </p>
 </div>
 <Separator class="bg-border/50" />
 <div>
 <Label class="text-muted-foreground">Git 用户</Label>
 <p class="mt-2 text-sm">
 {{ credential.git_user_name }} &lt;{{ credential.git_user_email }}&gt;
 </p>
 </div>
 <Separator class="bg-border/50" />
 <div>
 <Label class="text-muted-foreground">创建时间</Label>
 <p class="mt-2 text-sm">
 {{ formatDate(credential.created_at) }}
 </p>
 </div>
 </div>
 <div class="flex justify-end pt-2">
 <Button variant="outline" class="group" @click="editing = true">
 <span class="icon-[lucide--refresh-cw] mr-2 group-hover:rotate-180 transition-transform duration-500" />
 更新凭证
 </Button>
 </div>
 </div>
 <!-- 配置 / 更新表单 -->
 <form v-else class="space-y-4" @submit.prevent="handleAccessTokenUpdate">
 <p class="text-sm text-muted-foreground">
 {{ credential ? '输入新的 Access Token，更新后旧的 Token 将被替换': '输入 Access Token 以配置 Git 访问凭证' }}
 </p>
 <div class="space-y-2">
 <Label for="cred_access_token">Access Token</Label>
 <Input
 id="cred_access_token"
 v-model="accessToken"
 type="password"
 placeholder="GITHUB_TOKEN_PLACEHOLDER 或 glpat-xxxxxxxxxxxx"
 class=" bg-muted/30 border-border/50 focus:border-primary/50"
 />
 </div>
 <div class="grid gap-4 md:grid-cols-2">
 <div class="space-y-2">
 <Label for="cred_git_user_name">Git 用户名</Label>
 <Input
 id="cred_git_user_name"
 v-model="gitUserName"
 placeholder="Friday AI Agent"
 class=" bg-muted/30 border-border/50 focus:border-primary/50"
 />
 </div>
 <div class="space-y-2">
 <Label for="cred_git_user_email">Git 邮箱</Label>
 <Input
 id="cred_git_user_email"
 v-model="gitUserEmail"
 type="email"
 placeholder="ai@friday.codes"
 class=" bg-muted/30 border-border/50 focus:border-primary/50"
 />
 </div>
 </div>
 <div class="flex justify-end gap-3 pt-2">
 <Button
 v-if="credential"
 type="button"
 variant="outline":disabled="submitting"
 @click="editing = false"
 >
 取消
 </Button>
 <Button
 type="submit":disabled="!accessToken.trim || submitting"
 class="group relative overflow-hidden"
 >
 <span v-if="submitting" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 {{ submitting ? '保存中...': '保存' }}
 </Button>
 </div>
 </form>
 </DialogContent>
 </Dialog>
</template>
