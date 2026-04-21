<script setup lang="ts">
import { watch } from 'vue'
import ClaudeTestDialog from '~/components/ClaudeTestDialog.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import RAGEnhancementSettings from '~/components/settings/RAGEnhancementSettings.vue'
import VectorIndexSettings from '~/components/settings/VectorIndexSettings.vue'
import FeishuIMConfigSection from './components/FeishuIMConfigSection.vue'
import FeishuTestPanel from './components/FeishuTestPanel.vue'
import SettingsInfoCard from './components/SettingsInfoCard.vue'
import { useClaudeSettings } from './composables/useClaudeSettings'
import { useFeishuIMSettings } from './composables/useFeishuIMSettings'
definePage({
 meta: { requiresAdmin: true },
})
const claude = useClaudeSettings
const feishu = useFeishuIMSettings(claude.settings, claude.loadSettings)
// 设置加载完成后初始化飞书配置值
watch( => claude.loading.value, (isLoading) => {
 if (!isLoading) {
 feishu.initFromSettings
 }
}, { immediate: true })
</script>
<template>
 <div class="min-h-[calc(100vh-8rem)] relative">
 <!-- 背景装饰 -->
 <div class="absolute inset-0 -z-10 overflow-hidden">
 <div class="absolute inset-x-0 top-0 bg-linear-to-b from-primary/6 to-transparent" />
 </div>
 <div class="max-w-2xl mx-auto space-y-8 relative">
 <!-- 页面标题 -->
 <section class="text-center pt-8 pb-4">
 <div class="inline-flex items-center justify-center mb-6 rounded-2xl bg-gradient-to-br from-primary/10 via-secondary/50 to-primary/10 backdrop-blur-sm border border-primary/10">
 <span class="icon-[lucide--settings] text-4xl text-primary" />
 </div>
 <h1 class="text-3xl font-bold tracking-tight mb-3">
 系统设置
 </h1>
 <p class="text-muted-foreground max-w-md mx-auto">
 配置全局的 Claude Code 设置，作为所有项目的默认值
 </p>
 </section>
 <LoadingState v-if="claude.loading.value" variant="spinner" text="加载设置..." />
 <template v-else>
 <div class="space-y-6">
 <RouterLink
 to="/admin/providers"
 class="block rounded-xl border bg-card hover:bg-muted/50 transition-colors"
 >
 <div class="flex items-center gap-3">
 <span
 class="icon-[lucide--key-round] w-6 text-primary"
 aria-hidden="true"
 />
 <div class="flex-1">
 <h3 class="text-base font-semibold">
 Provider 凭证管理
 </h3>
 <p class="text-xs text-muted-foreground mt-1">
 管理 5 种 LLM Provider 凭证（Anthropic / OpenAI / Gemini / Ollama）
 </p>
 </div>
 <span
 class="icon-[lucide--chevron-right] w-5 text-muted-foreground"
 aria-hidden="true"
 />
 </div>
 </RouterLink>
 <SettingsInfoCard />
 <VectorIndexSettings />
 <RAGEnhancementSettings />
 <FeishuIMConfigSection:feishu-app-id-value="feishu.feishuAppIdValue.value":feishu-app-secret-value="feishu.feishuAppSecretValue.value":feishu-app-id-dirty="feishu.feishuAppIdDirty.value":feishu-app-secret-dirty="feishu.feishuAppSecretDirty.value":show-feishu-app-secret="feishu.showFeishuAppSecret.value":saving-feishu-i-m="feishu.savingFeishuIM.value":has-feishu-i-m-config="feishu.hasFeishuIMConfig":get-setting-by-key="feishu.getSettingByKey"
 @update:feishu-app-id-value="feishu.feishuAppIdValue.value = $event"
 @update:feishu-app-secret-value="feishu.feishuAppSecretValue.value = $event"
 @update:show-feishu-app-secret="feishu.showFeishuAppSecret.value = $event"
 @feishu-app-id-input="feishu.onFeishuAppIdInput"
 @feishu-app-secret-input="feishu.onFeishuAppSecretInput"
 @save="feishu.saveFeishuIMConfig"
 @remove="feishu.removeFeishuIMConfig"
 />
 <!-- 飞书测试面板嵌入在飞书配置卡片内 -->
 <FeishuTestPanel:visible="feishu.hasFeishuIMConfig || feishu.feishuAppIdValue.value.trim !== ''":feishu-test-receive-id="feishu.feishuTestReceiveId.value":feishu-test-receive-id-type="feishu.feishuTestReceiveIdType.value":feishu-test-message="feishu.feishuTestMessage.value":testing-feishu-i-m="feishu.testingFeishuIM.value":feishu-test-result="feishu.feishuTestResult.value"
 @update:feishu-test-receive-id="feishu.feishuTestReceiveId.value = $event"
 @update:feishu-test-receive-id-type="feishu.feishuTestReceiveIdType.value = $event"
 @update:feishu-test-message="feishu.feishuTestMessage.value = $event"
 @test="feishu.testFeishuIMConfig"
 />
 </div>
 </template>
 <ClaudeTestDialog
 v-model:open="claude.testDialogOpen.value"
 source="system"
 />
 </div>
 </div>
</template>
