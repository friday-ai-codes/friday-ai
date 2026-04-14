<script setup lang="ts">
import type { CollectionHealthResponse, IndexFreshnessResponse } from '~/api/repositories'
import type { Repository } from '~/types'
import { onMounted, ref } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import { Badge } from '~/components/ui/badge'
import { Separator } from '~/components/ui/separator'
import { Switch } from '~/components/ui/switch'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
const props = defineProps<{
 repository: Repository
}>
const emit = defineEmits<{
 updated:
}>
const { confirm } = useConfirmDialog
const { handleError } = useErrorHandler
const { success } = useToast
const health = ref<CollectionHealthResponse | null>(null)
const freshness = ref<IndexFreshnessResponse | null>(null)
const loadingHealth = ref(true)
const loadingFreshness = ref(true)
const togglingAutoIndex = ref(false)
const generatingSecret = ref(false)
const webhookUrl = computed( => {
 const base = window.location.origin
 return `${base}/api/repositories/${props.repository.id}/webhooks/push/`
})
async function loadHealth {
 loadingHealth.value = true
 try {
 health.value = await repositoriesApi.getCollectionHealth(props.repository.id)
 }
 catch {
 // intentionally ignored
 }
 finally {
 loadingHealth.value = false
 }
}
async function loadFreshness {
 loadingFreshness.value = true
 try {
 freshness.value = await repositoriesApi.getIndexFreshness(props.repository.id)
 }
 catch {
 // intentionally ignored
 }
 finally {
 loadingFreshness.value = false
 }
}
async function toggleAutoIndex(enabled: boolean) {
 togglingAutoIndex.value = true
 try {
 await repositoriesApi.update(props.repository.id, { auto_index_enabled: enabled })
 success(enabled ? '自动索引已启用': '自动索引已禁用')
 emit('updated')
 }
 catch (e: unknown) {
 handleError(e, '设置自动索引')
 }
 finally {
 togglingAutoIndex.value = false
 }
}
function copyToClipboard(text: string) {
 navigator.clipboard.writeText(text)
 success('已复制到剪贴板')
}
async function generateSecret {
 if (props.repository.webhook_secret) {
 const confirmed = await confirm({
 title: '重新生成 Secret',
 description: '重新生成将使当前配置的 Webhook 签名验证失效，确认继续？',
 confirmText: '重新生成',
 variant: 'destructive',
 })
 if (!confirmed)
 return
 }
 generatingSecret.value = true
 try {
 await repositoriesApi.generateWebhookSecret(props.repository.id)
 success('Webhook Secret 已生成')
 emit('updated')
 }
 catch (e: unknown) {
 handleError(e, '生成 Secret')
 }
 finally {
 generatingSecret.value = false
 }
}
onMounted( => {
 loadHealth
 loadFreshness
})
</script>
<template>
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--shield-check] text-primary" />
 <h3 class="text-sm font-semibold">
 索引健康与配置
 </h3>
 </div>
 <p class="text-xs text-muted-foreground mt-0.5">
 健康状态、新鲜度与自动索引配置
 </p>
 </div>
 <div class=" space-y-5">
 <!-- 健康状态 -->
 <div class="space-y-2">
 <p class="text-sm font-medium text-muted-foreground">
 集合健康
 </p>
 <div v-if="loadingHealth" class="flex items-center gap-2 text-sm text-muted-foreground">
 <span class="icon-[lucide--loader-circle] animate-spin" />
 检测中...
 </div>
 <div v-else-if="health" class="flex items-center gap-3">
 <div class=".5 rounded-full":class="health.status === 'healthy' ? 'bg-emerald-500/10': 'bg-destructive/10'">
 <span
 class="text-lg":class="health.status === 'healthy' ? 'icon-[lucide--check-circle] text-emerald-500': 'icon-[lucide--alert-circle] text-destructive'"
 />
 </div>
 <div class="flex-1 min-w-0">
 <p class="text-sm font-medium">
 {{ health.status === 'healthy' ? '健康': '异常' }}
 </p>
 <p class="text-xs text-muted-foreground">
 {{ health.points_count.toLocaleString }} 个向量点
 <template v-if="health.points_match === false">
 · <span class="text-amber-600">数量不匹配（预期 {{ health.expected_points }}）</span>
 </template>
 </p>
 </div>
 </div>
 <p v-else class="text-xs text-muted-foreground">
 无法获取健康状态
 </p>
 </div>
 <Separator class="bg-border/50" />
 <!-- 新鲜度 -->
 <div class="space-y-2">
 <p class="text-sm font-medium text-muted-foreground">
 索引新鲜度
 </p>
 <div v-if="loadingFreshness" class="flex items-center gap-2 text-sm text-muted-foreground">
 <span class="icon-[lucide--loader-circle] animate-spin" />
 检测中...
 </div>
 <div v-else-if="freshness" class="space-y-2">
 <div class="flex items-center gap-2">
 <Badge
 v-if="freshness.is_fresh === true"
 variant="outline"
 class="bg-emerald-500/10 text-emerald-600 border-emerald-500/20"
 >
 <span class="icon-[lucide--check] mr-1" />
 最新
 </Badge>
 <Badge
 v-else-if="freshness.is_fresh === false"
 variant="outline"
 class="bg-amber-500/10 text-amber-600 border-amber-500/20"
 >
 <span class="icon-[lucide--alert-triangle] mr-1" />
 有更新可用
 </Badge>
 <Badge
 v-else
 variant="outline"
 class="bg-muted text-muted-foreground border-border"
 >
 未知
 </Badge>
 </div>
 <div v-if="freshness.local_sha || freshness.remote_sha" class="text-xs text-muted-foreground font-mono space-y-0.5">
 <p v-if="freshness.local_sha">
 本地: {{ freshness.local_sha.slice(0, 10) }}
 </p>
 <p v-if="freshness.remote_sha">
 远端: {{ freshness.remote_sha.slice(0, 10) }}
 </p>
 </div>
 <p v-if="freshness.last_indexed_at" class="text-xs text-muted-foreground">
 最后索引: {{ new Date(freshness.last_indexed_at).toLocaleString('zh-CN') }}
 </p>
 </div>
 <p v-else class="text-xs text-muted-foreground">
 无法获取新鲜度信息
 </p>
 </div>
 <Separator class="bg-border/50" />
 <!-- 自动索引开关 -->
 <div class="flex items-center justify-between">
 <div>
 <p class="text-sm font-medium">
 自动索引
 </p>
 <p class="text-xs text-muted-foreground">
 Webhook 推送或定时轮询时自动更新索引
 </p>
 </div>
 <Switch:checked="repository.auto_index_enabled":disabled="togglingAutoIndex"
 @update:checked="toggleAutoIndex"
 />
 </div>
 <Separator class="bg-border/50" />
 <!-- Webhook 配置 -->
 <div class="space-y-3">
 <p class="text-sm font-medium text-muted-foreground">
 Webhook 配置
 </p>
 <div class="space-y-2">
 <div>
 <label class="text-xs text-muted-foreground">Payload URL</label>
 <div class="flex items-center gap-2 mt-1">
 <code class="flex-1 text-xs bg-muted/50 px-3 py-2 rounded-lg font-mono break-all border border-border/50">
 {{ webhookUrl }}
 </code>
 <button
 class=" rounded-lg hover:bg-muted/50 transition-colors shrink-0"
 title="复制 URL"
 @click="copyToClipboard(webhookUrl)"
 >
 <span class="icon-[lucide--copy] text-muted-foreground" />
 </button>
 </div>
 </div>
 <div class="flex items-center gap-2">
 <button
 class="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-border/50 hover:bg-muted/50 transition-colors disabled:opacity-50":disabled="generatingSecret"
 @click="generateSecret"
 >
 <span v-if="generatingSecret" class="icon-[lucide--loader-circle] animate-spin" />
 <span v-else class="icon-[lucide--key-round]" />
 {{ repository.webhook_secret ? '重新生成 Secret': '生成 Secret' }}
 </button>
 </div>
 <div v-if="repository.webhook_secret">
 <label class="text-xs text-muted-foreground">Secret</label>
 <div class="flex items-center gap-2 mt-1">
 <code class="flex-1 text-xs bg-muted/50 px-3 py-2 rounded-lg font-mono border border-border/50">
 {{ repository.webhook_secret }}
 </code>
 <button
 class=" rounded-lg hover:bg-muted/50 transition-colors shrink-0"
 title="复制 Secret"
 @click="copyToClipboard(repository.webhook_secret!)"
 >
 <span class="icon-[lucide--copy] text-muted-foreground" />
 </button>
 </div>
 </div>
 </div>
 <div class="text-xs text-muted-foreground bg-muted/30 rounded-lg px-3 py-2 space-y-1">
 <p class="font-medium">
 配置说明
 </p>
 <p>1. 在 Git 平台（GitHub / GitLab / Gitea）的仓库设置中添加 Webhook</p>
 <p>2. 将 Payload URL 填入 Webhook 配置，事件选择 <code class="bg-muted px-1 rounded">push</code></p>
 <p>3. 如有 Secret，填入上方的 Secret 值用于签名验证</p>
 </div>
 </div>
 </div>
 </div>
</template>
