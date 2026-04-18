<script setup lang="ts">
/**
 * OIDC Provider 管理设置组件
 * 系统管理员用于配置 OIDC Provider 的 UI
 */
import type { OIDCProvider, OIDCProviderCreate } from '~/types'
import { ref } from 'vue'
import {
 createProvider,
 deleteProvider,
 discoverEndpoints,
 getProviders,
 updateProvider,
} from '~/api/oidc'
import { Button } from '~/components/ui/button'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Switch } from '~/components/ui/switch'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
const { confirm } = useConfirmDialog
const { handleError } = useErrorHandler
const { success, error: showError } = useToast
// 状态
const providers = ref<OIDCProvider>
const loading = ref(true)
const dialogOpen = ref(false)
const saving = ref(false)
const discovering = ref(false)
const editingId = ref<string | null>(null)
// 表单
const form = ref<OIDCProviderCreate>({
 name: '',
 issuer_url: '',
 client_id: '',
 client_secret: '',
 authorization_endpoint: '',
 token_endpoint: '',
 userinfo_endpoint: '',
 scopes: 'openid profile email',
 is_active: true,
})
// 加载 Provider 列表
async function loadProviders {
 loading.value = true
 try {
 providers.value = await getProviders
 }
 catch (e: unknown) {
 handleError(e, '加载 OIDC Provider')
 }
 finally {
 loading.value = false
 }
}
// 打开新建对话框
function openCreateDialog {
 editingId.value = null
 form.value = {
 name: '',
 issuer_url: '',
 client_id: '',
 client_secret: '',
 authorization_endpoint: '',
 token_endpoint: '',
 userinfo_endpoint: '',
 scopes: 'openid profile email',
 is_active: true,
 }
 dialogOpen.value = true
}
// 打开编辑对话框
function openEditDialog(provider: OIDCProvider) {
 editingId.value = provider.id
 form.value = {
 name: provider.name,
 issuer_url: provider.issuer_url,
 client_id: provider.client_id,
 client_secret: '',
 authorization_endpoint: provider.authorization_endpoint,
 token_endpoint: provider.token_endpoint,
 userinfo_endpoint: provider.userinfo_endpoint,
 scopes: provider.scopes,
 is_active: provider.is_active,
 }
 dialogOpen.value = true
}
// Discovery 自动填充
async function onDiscover {
 if (!form.value.issuer_url) {
 showError('请先输入 Issuer URL')
 return
 }
 discovering.value = true
 try {
 const result = await discoverEndpoints(form.value.issuer_url)
 form.value.authorization_endpoint = result.authorization_endpoint
 form.value.token_endpoint = result.token_endpoint
 form.value.userinfo_endpoint = result.userinfo_endpoint
 success('端点信息已自动填充')
 }
 catch (e: unknown) {
 handleError(e, 'Discovery')
 }
 finally {
 discovering.value = false
 }
}
// 保存（创建或更新）
async function onSave {
 if (!form.value.name || !form.value.issuer_url || !form.value.client_id) {
 showError('请填写必填项（名称、Issuer URL、Client ID）')
 return
 }
 if (!form.value.authorization_endpoint || !form.value.token_endpoint) {
 showError('请填写授权端点和 Token 端点（可通过自动发现填充）')
 return
 }
 saving.value = true
 try {
 const data = { ...form.value }
 // 更新时如果 secret 为空则不传
 if (editingId.value && !data.client_secret) {
 delete data.client_secret
 }
 if (editingId.value) {
 await updateProvider(editingId.value, data)
 success('Provider 已更新')
 }
 else {
 await createProvider(data)
 success('Provider 已创建')
 }
 dialogOpen.value = false
 await loadProviders
 }
 catch (e: unknown) {
 handleError(e, '保存')
 }
 finally {
 saving.value = false
 }
}
// 删除 Provider
async function onDelete(provider: OIDCProvider) {
 const confirmed = await confirm({
 title: '删除 Provider',
 description: `确定删除 "${provider.name}"？`,
 confirmText: '删除',
 variant: 'destructive',
 })
 if (!confirmed)
 return
 try {
 await deleteProvider(provider.id)
 success('Provider 已删除')
 await loadProviders
 }
 catch (e: unknown) {
 handleError(e, '删除')
 }
}
// 切换启用/禁用
async function onToggleActive(provider: OIDCProvider) {
 try {
 await updateProvider(provider.id, { is_active: !provider.is_active })
 await loadProviders
 }
 catch (e: unknown) {
 handleError(e, '状态切换')
 }
}
onMounted( => {
 loadProviders
})
</script>
<template>
 <section class="group relative">
 <div class="card overflow-hidden">
 <!-- 卡片头部 -->
 <div class="flex items-center justify-between border-b border-border/50">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--shield-check] text-2xl text-emerald-500" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">
 OIDC Provider 配置
 </h2>
 <p class="text-sm text-muted-foreground">
 配置企业 OIDC 单点登录（Okta、Azure AD 等）
 </p>
 </div>
 </div>
 <Button variant="outline" size="sm" @click="openCreateDialog">
 <span class="icon-[lucide--plus] mr-1.5" />
 添加 Provider
 </Button>
 </div>
 <!-- Provider 列表 -->
 <div class="">
 <!-- 加载中 -->
 <div v-if="loading" class="flex items-center justify-center py-8 text-muted-foreground">
 <span class="icon-[lucide--loader-circle] animate-spin mr-2" />
 加载中...
 </div>
 <!-- 空状态 -->
 <div v-else-if="providers.length === 0" class="flex flex-col items-center justify-center py-10 text-muted-foreground">
 <span class="icon-[lucide--shield-off] text-4xl mb-3 opacity-30" />
 <p class="text-sm font-medium">
 尚未配置 OIDC Provider
 </p>
 <p class="text-xs mt-1 opacity-70">
 添加 Provider 后，用户可通过 OIDC 单点登录
 </p>
 </div>
 <!-- Provider 卡片列表 -->
 <div v-else class="space-y-3">
 <div
 v-for="provider in providers":key="provider.id"
 class="flex items-center justify-between rounded-xl bg-muted/30 border border-border/30 hover:border-border/50 transition-colors"
 >
 <div class="flex items-center gap-3 flex-1 min-w-0">
 <div class=" rounded-lg":class="provider.is_active ? 'bg-emerald-500/10': 'bg-muted'">
 <span
 class="text-lg":class="provider.is_active ? 'icon-[lucide--shield-check] text-emerald-500': 'icon-[lucide--shield-off] text-muted-foreground'"
 />
 </div>
 <div class="min-w-0">
 <div class="font-medium truncate">
 {{ provider.name }}
 </div>
 <div class="text-xs text-muted-foreground truncate">
 {{ provider.issuer_url }}
 </div>
 </div>
 </div>
 <div class="flex items-center gap-2 ml-4">
 <Switch:checked="provider.is_active"
 @update:checked="onToggleActive(provider)"
 />
 <Button variant="ghost" size="icon" class=" w-8" @click="openEditDialog(provider)">
 <span class="icon-[lucide--pencil] text-sm" />
 </Button>
 <Button
 variant="ghost"
 size="icon"
 class=" w-8 hover:text-destructive"
 @click="onDelete(provider)"
 >
 <span class="icon-[lucide--trash-2] text-sm" />
 </Button>
 </div>
 </div>
 </div>
 </div>
 </div>
 <!-- 创建/编辑对话框 -->
 <Dialog v-model:open="dialogOpen">
 <DialogContent class="max-w-lg max-h-[85vh] overflow-y-auto">
 <DialogHeader>
 <DialogTitle>{{ editingId ? '编辑': '添加' }} OIDC Provider</DialogTitle>
 <DialogDescription>
 配置 OIDC Provider 的连接信息。输入 Issuer URL 后可点击"自动发现"按钮填充端点。
 </DialogDescription>
 </DialogHeader>
 <div class="space-y-4 py-4">
 <!-- 名称 -->
 <div class="space-y-2">
 <Label>名称 *</Label>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--tag] text-muted-foreground" />
 <Input v-model="form.name" placeholder="如：Okta、Azure AD" class="pl-10 bg-muted/30 border-border/50 focus:border-primary/50" />
 </div>
 </div>
 <!-- Issuer URL + Discovery -->
 <div class="space-y-2">
 <Label>Issuer URL *</Label>
 <div class="flex gap-2">
 <div class="relative flex-1">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--globe] text-muted-foreground" />
 <Input v-model="form.issuer_url" placeholder="https://your-domain.okta.com" class="pl-10 bg-muted/30 border-border/50 focus:border-primary/50" />
 </div>
 <Button
 variant="outline"
 size="sm":disabled="discovering || !form.issuer_url"
 @click="onDiscover"
 >
 <span v-if="discovering" class="icon-[lucide--loader-circle] animate-spin mr-1.5" />
 <span v-else class="icon-[lucide--search] mr-1.5" />
 自动发现
 </Button>
 </div>
 </div>
 <!-- Client ID -->
 <div class="space-y-2">
 <Label>Client ID *</Label>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--fingerprint] text-muted-foreground" />
 <Input v-model="form.client_id" placeholder="OIDC Client ID" class="pl-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50" />
 </div>
 </div>
 <!-- Client Secret -->
 <div class="space-y-2">
 <div class="flex items-center justify-between">
 <Label>Client Secret</Label>
 <span v-if="editingId" class="text-xs text-muted-foreground">
 留空则保持不变
 </span>
 </div>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--lock] text-muted-foreground" />
 <Input
 v-model="form.client_secret"
 type="password"
 placeholder="OIDC Client Secret"
 class="pl-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50"
 />
 </div>
 </div>
 <!-- 端点配置 -->
 <div class="rounded-lg bg-muted/30 border border-border/30 space-y-3">
 <div class="text-sm font-medium flex items-center gap-2">
 <span class="icon-[lucide--link] text-muted-foreground" />
 端点配置
 </div>
 <div class="space-y-2">
 <Label class="text-xs">Authorization Endpoint *</Label>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--link] text-muted-foreground" />
 <Input v-model="form.authorization_endpoint" placeholder="https://..." class="pl-10 font-mono text-xs bg-muted/30 border-border/50 focus:border-primary/50" />
 </div>
 </div>
 <div class="space-y-2">
 <Label class="text-xs">Token Endpoint *</Label>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key-round] text-muted-foreground" />
 <Input v-model="form.token_endpoint" placeholder="https://..." class="pl-10 font-mono text-xs bg-muted/30 border-border/50 focus:border-primary/50" />
 </div>
 </div>
 <div class="space-y-2">
 <Label class="text-xs">UserInfo Endpoint</Label>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--user-check] text-muted-foreground" />
 <Input v-model="form.userinfo_endpoint" placeholder="https://..." class="pl-10 font-mono text-xs bg-muted/30 border-border/50 focus:border-primary/50" />
 </div>
 </div>
 </div>
 <!-- Scopes -->
 <div class="space-y-2">
 <Label>Scopes</Label>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--shield] text-muted-foreground" />
 <Input v-model="form.scopes" placeholder="openid profile email" class="pl-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50" />
 </div>
 </div>
 <!-- 启用状态 -->
 <div class="flex items-center justify-between">
 <Label>启用此 Provider</Label>
 <Switch v-model:checked="form.is_active" />
 </div>
 </div>
 <DialogFooter>
 <Button variant="outline" @click="dialogOpen = false">
 取消
 </Button>
 <Button:disabled="saving" @click="onSave">
 <span v-if="saving" class="icon-[lucide--loader-circle] animate-spin" />
 <span v-else class="icon-[lucide--save]" />
 {{ editingId ? '更新': '创建' }}
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 </section>
</template>
