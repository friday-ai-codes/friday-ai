<script setup lang="ts">
import type { SettingRead } from '~/api/settings'
import { onMounted, ref } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import {
 getAllSettings,
 SettingKey,
 updateSetting,
} from '~/api/settings'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Switch } from '~/components/ui/switch'
const { handleError } = useErrorHandler
const { success, error: showError, info, warning } = useToast
// 设置状态
const settings = ref<SettingRead>
const loading = ref(true)
const saving = ref(false)
const testingReranker = ref(false)
// Hybrid Search 表单值
const hybridEnabled = ref(false)
const hybridAlpha = ref('0.7')
const hybridEnabledDirty = ref(false)
const hybridAlphaDirty = ref(false)
// Reranker 表单值
const rerankerEnabled = ref(false)
const rerankerApiUrl = ref('')
const rerankerApiKey = ref('')
const rerankerModel = ref('')
const rerankerTopN = ref('10')
const rerankerEnabledDirty = ref(false)
const rerankerApiUrlDirty = ref(false)
const rerankerApiKeyDirty = ref(false)
const rerankerModelDirty = ref(false)
const rerankerTopNDirty = ref(false)
const showRerankerApiKey = ref(false)
// 健康状态
const rerankerHealth = ref<{ status: string, message?: string } | null>(null)
// 加载设置
async function loadSettings {
 loading.value = true
 try {
 settings.value = await getAllSettings
 const getValue = (key: SettingKey) => settings.value.find(s => s.key === key)?.value || ''
 const getMasked = (key: SettingKey) => {
 const setting = settings.value.find(s => s.key === key)
 return setting?.has_value ? setting.value || '': ''
 }
 hybridEnabled.value = getValue(SettingKey.HYBRID_SEARCH_ENABLED) === 'true'
 hybridAlpha.value = getValue(SettingKey.HYBRID_SEARCH_ALPHA) || '0.7'
 rerankerEnabled.value = getValue(SettingKey.RERANKER_ENABLED) === 'true'
 rerankerApiUrl.value = getValue(SettingKey.RERANKER_API_URL)
 rerankerApiKey.value = getMasked(SettingKey.RERANKER_API_KEY)
 rerankerModel.value = getValue(SettingKey.RERANKER_MODEL)
 rerankerTopN.value = getValue(SettingKey.RERANKER_TOP_N) || '10'
 resetDirtyFlags
 }
 catch (e: unknown) {
 handleError(e, '加载 RAG 增强设置')
 }
 finally {
 loading.value = false
 }
}
function resetDirtyFlags {
 hybridEnabledDirty.value = false
 hybridAlphaDirty.value = false
 rerankerEnabledDirty.value = false
 rerankerApiUrlDirty.value = false
 rerankerApiKeyDirty.value = false
 rerankerModelDirty.value = false
 rerankerTopNDirty.value = false
}
function hasUnsavedChanges: boolean {
 return hybridEnabledDirty.value || hybridAlphaDirty.value
 || rerankerEnabledDirty.value || rerankerApiUrlDirty.value
 || rerankerApiKeyDirty.value || rerankerModelDirty.value
 || rerankerTopNDirty.value
}
async function saveAllSettings {
 saving.value = true
 try {
 const promises: Promise<unknown> =
 if (hybridEnabledDirty.value)
 promises.push(updateSetting(SettingKey.HYBRID_SEARCH_ENABLED, hybridEnabled.value ? 'true': 'false'))
 if (hybridAlphaDirty.value && hybridAlpha.value)
 promises.push(updateSetting(SettingKey.HYBRID_SEARCH_ALPHA, hybridAlpha.value))
 if (rerankerEnabledDirty.value)
 promises.push(updateSetting(SettingKey.RERANKER_ENABLED, rerankerEnabled.value ? 'true': 'false'))
 if (rerankerApiUrlDirty.value && rerankerApiUrl.value.trim)
 promises.push(updateSetting(SettingKey.RERANKER_API_URL, rerankerApiUrl.value.trim))
 if (rerankerApiKeyDirty.value && rerankerApiKey.value.trim)
 promises.push(updateSetting(SettingKey.RERANKER_API_KEY, rerankerApiKey.value.trim))
 if (rerankerModelDirty.value && rerankerModel.value.trim)
 promises.push(updateSetting(SettingKey.RERANKER_MODEL, rerankerModel.value.trim))
 if (rerankerTopNDirty.value && rerankerTopN.value)
 promises.push(updateSetting(SettingKey.RERANKER_TOP_N, rerankerTopN.value))
 if (promises.length === 0) {
 info('没有需要保存的更改')
 return
 }
 await Promise.all(promises)
 success('RAG 增强设置已保存')
 await loadSettings
 }
 catch (e: unknown) {
 handleError(e, '保存')
 }
 finally {
 saving.value = false
 }
}
async function testRerankerConnection {
 testingReranker.value = true
 try {
 const apiUrl = rerankerApiUrl.value.trim
 const model = rerankerModel.value.trim || 'BAAI/bge-reranker-v2-m3'
 if (!apiUrl) {
 showError('请先填写 Reranker API 地址')
 rerankerHealth.value = { status: 'error', message: '未填写 API 地址' }
 return
 }
 const result = await repositoriesApi.testRerankerConnection(
 apiUrl,
 model,
 rerankerApiKeyDirty.value ? rerankerApiKey.value.trim || undefined: undefined,
 )
 rerankerHealth.value = result
 if (result.status === 'healthy') {
 success('Reranker API 连接成功')
 }
 else {
 showError(`Reranker API 连接失败: ${result.message}`)
 }
 }
 catch (e: unknown) {
 handleError(e, '测试 Reranker 连接')
 rerankerHealth.value = { status: 'error', message: String(e) }
 }
 finally {
 testingReranker.value = false
 }
}
function getHealthStatusColor(status: string | undefined) {
 return status === 'healthy' ? 'text-emerald-500': 'text-destructive'
}
function getHealthStatusIcon(status: string | undefined) {
 return status === 'healthy' ? 'icon-[lucide--check-circle]': 'icon-[lucide--x-circle]'
}
onMounted( => {
 loadSettings
})
</script>
<template>
 <section class="group relative">
 <div class="card overflow-hidden">
 <!-- 卡片头部 -->
 <div class="flex items-center gap-3 border-b border-border/50 bg-gradient-to-r from-violet-500/5 to-purple-500/5">
 <div class=".5 rounded-xl bg-gradient-to-br from-violet-500/20 to-violet-500/10 flex items-center justify-center">
 <span class="icon-[lucide--sparkles] text-2xl text-violet-500" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">
 RAG 搜索增强
 </h2>
 <p class="text-sm text-muted-foreground">
 配置搜索增强策略，提升代码检索的准确性和相关性
 </p>
 </div>
 </div>
 <!-- 加载状态 -->
 <div v-if="loading" class="flex items-center justify-center gap-3 ">
 <span class="icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
 <span class="text-muted-foreground">加载设置...</span>
 </div>
 <!-- 表单内容 -->
 <div v-else class=" space-y-8">
 <!-- 1. 混合检索 (Hybrid Search) -->
 <div class="space-y-4">
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
 <span class="icon-[lucide--combine]" />
 <span>混合检索 (Hybrid Search)</span>
 </div>
 <Switch:checked="hybridEnabled"
 @update:checked="(val: boolean) => { hybridEnabled = val; hybridEnabledDirty = true }"
 />
 </div>
 <div class="rounded-xl bg-muted/30 border border-border/30 space-y-3">
 <p class="text-sm text-muted-foreground">
 在语义向量搜索基础上加入 BM25 关键词匹配，当搜索精确的函数名、变量名或错误信息时效果更好。
 使用 Qdrant 原生 RRF (Reciprocal Rank Fusion) 融合两种检索结果。
 </p>
 <div v-if="hybridEnabled" class="space-y-3 pt-2">
 <div class="space-y-2 max-w-xs">
 <Label for="hybrid-alpha">Dense 权重 (alpha)</Label>
 <Input
 id="hybrid-alpha"
 v-model="hybridAlpha"
 type="number"
 min="0"
 max="1"
 step="0.1"
 placeholder="0.7"
 class=" bg-muted/30 border-border/50 focus:border-primary/50"
 @input="hybridAlphaDirty = true"
 />
 <p class="text-xs text-muted-foreground">
 1.0 = 纯语义搜索，0.0 = 纯关键词匹配，推荐 0.7
 </p>
 </div>
 <div class="flex items-start gap-2 rounded-lg bg-amber-500/10 border border-amber-500/20 px-3 py-2">
 <span class="icon-[lucide--alert-triangle] text-amber-500 mt-0.5 shrink-0" />
 <p class="text-xs text-amber-600 dark:text-amber-400">
 启用混合检索后，需要对已索引的仓库重新执行全量索引以生成稀疏向量。
 </p>
 </div>
 </div>
 </div>
 </div>
 <!-- 2. 重排序 (Reranker) -->
 <div class="space-y-4">
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
 <span class="icon-[lucide--arrow-up-down]" />
 <span>重排序 (Reranker)</span>
 <span
 v-if="rerankerHealth":class="[getHealthStatusIcon(rerankerHealth.status), getHealthStatusColor(rerankerHealth.status)]"
 />
 </div>
 <Switch:checked="rerankerEnabled"
 @update:checked="(val: boolean) => { rerankerEnabled = val; rerankerEnabledDirty = true }"
 />
 </div>
 <div class="rounded-xl bg-muted/30 border border-border/30 space-y-3">
 <p class="text-sm text-muted-foreground">
 对初筛结果使用交叉编码器 (Cross-Encoder) 进行精排，大幅提升搜索结果相关性。
 初筛返回更多候选结果，再由 Reranker 模型精确判断与查询的相关度。
 </p>
 <div v-if="rerankerEnabled" class="space-y-4 pt-2">
 <div class="grid gap-4 md:grid-cols-2">
 <!-- Reranker API URL -->
 <div class="space-y-2">
 <Label for="reranker-api-url">Reranker API 地址</Label>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--link] text-muted-foreground" />
 <Input
 id="reranker-api-url"
 v-model="rerankerApiUrl"
 type="url"
 placeholder="https://api.example.com/v1/rerank"
 class="pl-10 bg-muted/30 border-border/50 focus:border-primary/50"
 @input="rerankerApiUrlDirty = true"
 />
 </div>
 <p class="text-xs text-muted-foreground">
 兼容 Jina/Cohere 格式的 Reranker API 端点
 </p>
 </div>
 <!-- Reranker API Key -->
 <div class="space-y-2">
 <Label for="reranker-api-key">Reranker API Key</Label>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key] text-muted-foreground" />
 <Input
 id="reranker-api-key"
 v-model="rerankerApiKey":type="showRerankerApiKey ? 'text': 'password'"
 placeholder="留空表示无需认证"
 class="pl-10 pr-10 bg-muted/30 border-border/50 focus:border-primary/50"
 @input="rerankerApiKeyDirty = true"
 />
 <button
 type="button"
 class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
 @click="showRerankerApiKey = !showRerankerApiKey"
 >
 <span:class="showRerankerApiKey ? 'icon-[lucide--eye-off]': 'icon-[lucide--eye]'" />
 </button>
 </div>
 </div>
 <!-- Reranker Model -->
 <div class="space-y-2">
 <Label for="reranker-model">Reranker 模型</Label>
 <Input
 id="reranker-model"
 v-model="rerankerModel"
 placeholder="BAAI/bge-reranker-v2-m3"
 class=" bg-muted/30 border-border/50 focus:border-primary/50"
 @input="rerankerModelDirty = true"
 />
 </div>
 <!-- Top N -->
 <div class="space-y-2">
 <Label for="reranker-top-n">精排 Top N</Label>
 <Input
 id="reranker-top-n"
 v-model="rerankerTopN"
 type="number"
 min="1"
 max="50"
 placeholder="10"
 class=" bg-muted/30 border-border/50 focus:border-primary/50"
 @input="rerankerTopNDirty = true"
 />
 <p class="text-xs text-muted-foreground">
 精排后保留的最终结果数量
 </p>
 </div>
 </div>
 <Button
 variant="outline"
 size="sm":disabled="testingReranker"
 @click="testRerankerConnection"
 >
 <span v-if="testingReranker" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--plug] mr-2" />
 测试 Reranker 连接
 </Button>
 </div>
 </div>
 </div>
 <!-- 3. Chunk 上下文增强 -->
 <div class="space-y-4">
 <div class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
 <span class="icon-[lucide--file-text]" />
 <span>Chunk 上下文增强</span>
 <Badge variant="success" class="text-xs">
 已内置
 </Badge>
 </div>
 <div class="rounded-xl bg-muted/30 border border-border/30 space-y-3">
 <p class="text-sm text-muted-foreground">
 在代码分块时自动提取文件级上下文信息，增强 embedding 向量的语义质量，使搜索结果更加准确。
 </p>
 <div class="grid gap-2 text-sm">
 <div class="flex items-center gap-2 text-muted-foreground">
 <span class="icon-[lucide--check] text-emerald-500" />
 <span>文件级 import / require 语句</span>
 </div>
 <div class="flex items-center gap-2 text-muted-foreground">
 <span class="icon-[lucide--check] text-emerald-500" />
 <span>模块级 docstring / 文件头注释</span>
 </div>
 <div class="flex items-center gap-2 text-muted-foreground">
 <span class="icon-[lucide--check] text-emerald-500" />
 <span>同文件相邻函数 / 类签名</span>
 </div>
 </div>
 <p class="text-xs text-muted-foreground italic">
 此功能已自动启用，重新索引后生效。上下文信息仅用于提升 embedding 质量，不增加存储开销。
 </p>
 </div>
 </div>
 </div>
 <!-- 保存按钮区域 -->
 <div class="flex justify-end px-6 py-4 border-t border-border/50">
 <Button:disabled="saving || !hasUnsavedChanges"
 class="group/btn relative overflow-hidden"
 @click="saveAllSettings"
 >
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover/btn:translate-x-[100%] transition-transform duration-700" />
 <span v-if="saving" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存设置
 </Button>
 </div>
 </div>
 </section>
</template>
