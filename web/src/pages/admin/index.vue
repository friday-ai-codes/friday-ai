<script setup lang="ts">
import { watch } from 'vue'
import ClaudeTestDialog from '~/components/ClaudeTestDialog.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import RAGEnhancementSettings from '~/components/settings/RAGEnhancementSettings.vue'
import VectorIndexSettings from '~/components/settings/VectorIndexSettings.vue'
import ClaudeConfigSection from './components/ClaudeConfigSection.vue'
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
 <div class="absolute -top-40 -right-40 w-80 bg-primary/10 rounded-full blur-3xl" />
 <div class="absolute top-1/2 -left-40 w-96 bg-gradient-to-tr from-secondary/30 to-primary/10 rounded-full blur-3xl" />
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
 <ClaudeConfigSection:api-key-value="claude.apiKeyValue.value":base-url-value="claude.baseUrlValue.value":default-model-value="claude.defaultModelValue.value":git-proxy-value="claude.gitProxyValue.value":show-api-key="claude.showApiKey.value":models="claude.models.value":loading-models="claude.loadingModels.value":saving="claude.saving.value":has-unsaved-changes="claude.hasUnsavedChanges.value":can-test="claude.canTest":settings-meta="claude.settingsMeta":get-setting-by-key="claude.getSettingByKey"
 @update:api-key-value="claude.apiKeyValue.value = $event"
 @update:base-url-value="claude.baseUrlValue.value = $event"
 @update:default-model-value="claude.defaultModelValue.value = $event"
 @update:git-proxy-value="claude.gitProxyValue.value = $event"
 @update:show-api-key="claude.showApiKey.value = $event"
 @api-key-input="claude.onApiKeyInput"
 @base-url-input="claude.onBaseUrlInput"
 @default-model-input="claude.onDefaultModelInput"
 @git-proxy-input="claude.onGitProxyInput"
 @save="claude.saveAllSettings"
 @remove="claude.removeSetting($event)"
 @open-test="claude.openTestDialog"
 @fetch-models="claude.fetchModels"
 />
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
