<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { checkProviderHealth } from '~/api/providers'
import ProviderIcon from '~/components/provider/ProviderIcon.vue'
import { PROVIDER_REGISTRY } from '~/types/provider'
import type { HealthStatus } from '~/types/provider'
import { Button } from '~/components/ui/button'
// 加载状态
const loading = ref(true)
// 健康检查状态
const healthStates = reactive<Record<string, HealthStatus>>(
 Object.fromEntries(PROVIDER_REGISTRY.map(p => [p.type, { status: 'unchecked' as const }])),
)
const checkingAll = ref(false)
async function checkHealth(providerType: string) {
 healthStates[providerType] = { status: 'checking' }
 try {
 const result = await checkProviderHealth(providerType as 'anthropic')
 healthStates[providerType] = {
 status: result.status,
 latencyMs: result.latency_ms,
 error: result.error ?? undefined,
 }
 }
 catch {
 healthStates[providerType] = { status: 'unavailable', error: '检查请求失败' }
 }
}
async function checkAllHealth {
 checkingAll.value = true
 for (const provider of PROVIDER_REGISTRY) {
 await checkHealth(provider.type)
 }
 checkingAll.value = false
}
onMounted( => {
 loading.value = false
})
</script>
<template>
 <section class="group relative">
 <!-- 悬浮光晕 -->
 <div class="absolute inset-0 bg-gradient-to-r from-amber-500/20 via-orange-500/20 to-amber-500/20 opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-2xl blur-xl -z-10" />
 <div class="relative rounded-2xl bg-card/80 backdrop-blur-sm border border-border/50 overflow-hidden group-hover:border-amber-500/30 group-hover:shadow-lg group-hover:shadow-amber-500/5 transition-all duration-300">
 <!-- 卡片头部 -->
 <div class="flex items-center justify-between border-b border-border/50 bg-gradient-to-r from-amber-500/5 to-orange-500/5">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-gradient-to-br from-amber-500/20 to-amber-500/10 flex items-center justify-center">
 <span class="icon-[lucide--cpu] text-2xl text-amber-600" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">
 模型提供商配置
 </h2>
 <p class="text-sm text-muted-foreground">
 Anthropic API 凭证配置，用于 Chat AI
 </p>
 </div>
 </div>
 <Button size="sm" variant="outline":disabled="checkingAll" @click="checkAllHealth">
 <span v-if="checkingAll" class="icon-[lucide--loader-circle] animate-spin mr-1.5" />
 <span v-else class="icon-[lucide--activity] mr-1.5" />
 检查全部
 </Button>
 </div>
 <!-- 内容 -->
 <div class="">
 <div v-if="loading" class="flex items-center justify-center py-8 text-muted-foreground">
 <span class="icon-[lucide--loader-circle] animate-spin mr-2" />
 加载中...
 </div>
 <div v-else class="space-y-4">
 <!-- Anthropic Provider 信息 -->
 <div class="flex items-center gap-3 mb-4">
 <ProviderIcon provider="anthropic" size="sm" />
 <span class="font-medium">Anthropic Claude</span>
 </div>
 <!-- 健康检查状态区域 -->
 <div class="flex items-center justify-between rounded-lg bg-muted/20 border border-border/30 px-4 py-3">
 <div class="flex items-center gap-3">
 <template v-if="healthStates['anthropic']?.status === 'unchecked'">
 <span class="w-2.5 .5 rounded-full bg-muted-foreground/30" />
 <span class="text-sm text-muted-foreground">未检查</span>
 </template>
 <template v-else-if="healthStates['anthropic']?.status === 'checking'">
 <span class="icon-[lucide--loader-circle] animate-spin text-muted-foreground" />
 <span class="text-sm text-muted-foreground">检查中...</span>
 </template>
 <template v-else-if="healthStates['anthropic']?.status === 'available'">
 <span class="w-2.5 .5 rounded-full bg-emerald-500" />
 <span class="text-sm text-emerald-600">可用</span>
 <span class="text-xs text-muted-foreground">{{ healthStates['anthropic'].latencyMs }}ms</span>
 </template>
 <template v-else>
 <span class="w-2.5 .5 rounded-full bg-red-500" />
 <span class="text-sm text-red-600">不可用</span>
 <span v-if="healthStates['anthropic']?.error" class="text-xs text-muted-foreground truncate max-w-[200px]">{{ healthStates['anthropic'].error }}</span>
 </template>
 </div>
 <Button
 size="sm"
 variant="ghost":disabled="healthStates['anthropic']?.status === 'checking'"
 @click="checkHealth('anthropic')"
 >
 <span class="icon-[lucide--heart-pulse] mr-1.5" />
 检查
 </Button>
 </div>
 <!-- 凭证说明 -->
 <div class="rounded-lg bg-muted/30 border border-border/50 px-4 py-3 text-sm text-muted-foreground flex items-start gap-2">
 <span class="icon-[lucide--info] w-4 mt-0.5 shrink-0" />
 <span>Anthropic API 凭证由上方「Claude Code 配置」统一管理</span>
 </div>
 </div>
 </div>
 </div>
 </section>
</template>
