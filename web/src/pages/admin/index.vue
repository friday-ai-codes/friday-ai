<script setup lang="ts">
import { ref, watch } from 'vue'

import ClaudeTestDialog from '~/components/ClaudeTestDialog.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import ClaudeCodeConfigPanel from '~/components/providers/ClaudeCodeConfigPanel.vue'
import ProviderSettings from '~/components/providers/ProviderSettings.vue'
import GeneralSettings from '~/components/settings/GeneralSettings.vue'
import OIDCProviderSettings from '~/components/settings/OIDCProviderSettings.vue'
import RerankSettings from '~/components/settings/RerankSettings.vue'
import VectorIndexSettings from '~/components/settings/VectorIndexSettings.vue'
import { Button } from '~/components/ui/button'

import FeishuIMConfigSection from './components/FeishuIMConfigSection.vue'
import FeishuTestPanel from './components/FeishuTestPanel.vue'
import { useClaudeSettings } from './composables/useClaudeSettings'
import { useFeishuIMSettings } from './composables/useFeishuIMSettings'

definePage({
  meta: { requiresAdmin: true },
})

const claude = useClaudeSettings()
const feishu = useFeishuIMSettings(claude.settings, claude.loadSettings)

// 引用嵌入的 ProviderSettings，让卡片头部「新建凭证」按钮触发其新建对话框
const providerSettingsRef = ref<InstanceType<typeof ProviderSettings> | null>(null)

// 设置加载完成后初始化飞书配置值
watch(() => claude.loading.value, (isLoading) => {
  if (!isLoading) {
    feishu.initFromSettings()
  }
}, { immediate: true })

// ============================================================================
// Tab 导航（仿 sub2api SettingsView 风格）
// ============================================================================

type SettingsTab = 'general' | 'rag' | 'integration' | 'provider' | 'oidc'

const activeTab = ref<SettingsTab>('general')

const settingsTabs = [
  { key: 'general' as SettingsTab, icon: 'icon-[lucide--settings-2]', label: '通用设置' },
  { key: 'rag' as SettingsTab, icon: 'icon-[lucide--brain]', label: 'RAG 设置' },
  { key: 'integration' as SettingsTab, icon: 'icon-[lucide--plug]', label: '集成设置' },
  { key: 'provider' as SettingsTab, icon: 'icon-[lucide--cpu]', label: 'Provider' },
  { key: 'oidc' as SettingsTab, icon: 'icon-[lucide--shield-check]', label: 'OIDC 认证' },
]

// 旧 /admin/oidc URL 重定向过来时（#oidc hash）自动切到对应 Tab
const route = useRoute()
onMounted(() => {
  const hashTab = route.hash.slice(1) as SettingsTab
  if (settingsTabs.some(t => t.key === hashTab))
    activeTab.value = hashTab
})
</script>

<template>
  <div class="min-h-[calc(100vh-8rem)] relative">
    <!-- 背景装饰 -->
    <div class="absolute inset-0 -z-10 overflow-hidden">
      <div class="absolute inset-x-0 top-0 h-48 bg-linear-to-b from-primary/6 to-transparent" />
    </div>

    <div class="max-w-4xl mx-auto space-y-6 relative">
      <!-- 页面标题 -->
      <section class="text-center pt-8 pb-2">
        <div class="inline-flex items-center justify-center p-4 mb-4 rounded-2xl bg-gradient-to-br from-primary/10 via-secondary/50 to-primary/10 backdrop-blur-sm border border-primary/10">
          <span class="icon-[lucide--settings] text-4xl text-primary" />
        </div>
        <h1 class="text-3xl font-bold tracking-tight mb-2">
          系统设置
        </h1>
        <p class="text-muted-foreground max-w-md mx-auto text-sm">
          配置全局默认设置，管理 Provider 凭证与第三方集成
        </p>
      </section>

      <LoadingState v-if="claude.loading.value" variant="spinner" text="加载设置..." />

      <template v-else>
        <!-- Tab 导航（sticky + pill 风格） -->
        <div class="sticky top-0 z-30 overflow-x-auto scrollbar-none py-2">
          <nav class="inline-flex min-w-full gap-0.5 rounded-2xl border border-border/60 bg-card/80 p-1 backdrop-blur-sm shadow-sm sm:flex">
            <button
              v-for="tab in settingsTabs"
              :key="tab.key"
              type="button"
              class="relative flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-xl px-3 py-2 text-sm font-medium transition-all duration-200 ease-out"
              :class="[
                activeTab === tab.key
                  ? 'text-primary bg-primary/8 shadow-sm'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted/60',
              ]"
              @click="activeTab = tab.key"
            >
              <span
                class="flex h-5 w-5 items-center justify-center rounded-md transition-all duration-200"
                :class="activeTab === tab.key ? 'text-primary' : 'text-muted-foreground'"
              >
                <span :class="tab.icon" />
              </span>
              <span>{{ tab.label }}</span>
            </button>
          </nav>
        </div>

        <!-- Tab: 通用设置 -->
        <div v-show="activeTab === 'general'" class="space-y-6">
          <GeneralSettings />
        </div>

        <!-- Tab: RAG 设置 -->
        <div v-show="activeTab === 'rag'" class="space-y-6">
          <VectorIndexSettings />
          <RerankSettings />
        </div>

        <!-- Tab: 集成设置 -->
        <div v-show="activeTab === 'integration'" class="space-y-6">
          <FeishuIMConfigSection
            :feishu-app-id-value="feishu.feishuAppIdValue.value"
            :feishu-app-secret-value="feishu.feishuAppSecretValue.value"
            :feishu-app-id-dirty="feishu.feishuAppIdDirty.value"
            :feishu-app-secret-dirty="feishu.feishuAppSecretDirty.value"
            :show-feishu-app-secret="feishu.showFeishuAppSecret.value"
            :saving-feishu-i-m="feishu.savingFeishuIM.value"
            :has-feishu-i-m-config="feishu.hasFeishuIMConfig()"
            :get-setting-by-key="feishu.getSettingByKey"
            @update:feishu-app-id-value="feishu.feishuAppIdValue.value = $event"
            @update:feishu-app-secret-value="feishu.feishuAppSecretValue.value = $event"
            @update:show-feishu-app-secret="feishu.showFeishuAppSecret.value = $event"
            @feishu-app-id-input="feishu.onFeishuAppIdInput()"
            @feishu-app-secret-input="feishu.onFeishuAppSecretInput()"
            @save="feishu.saveFeishuIMConfig()"
            @remove="feishu.removeFeishuIMConfig()"
          />

          <FeishuTestPanel
            :visible="feishu.hasFeishuIMConfig() || feishu.feishuAppIdValue.value.trim() !== ''"
            :feishu-test-receive-id="feishu.feishuTestReceiveId.value"
            :feishu-test-receive-id-type="feishu.feishuTestReceiveIdType.value"
            :feishu-test-message="feishu.feishuTestMessage.value"
            :testing-feishu-i-m="feishu.testingFeishuIM.value"
            :feishu-test-result="feishu.feishuTestResult.value"
            @update:feishu-test-receive-id="feishu.feishuTestReceiveId.value = $event"
            @update:feishu-test-receive-id-type="feishu.feishuTestReceiveIdType.value = $event"
            @update:feishu-test-message="feishu.feishuTestMessage.value = $event"
            @test="feishu.testFeishuIMConfig()"
          />
        </div>

        <!-- Tab: Provider -->
        <div v-show="activeTab === 'provider'" class="space-y-6">
          <div class="card overflow-hidden">
            <!-- 卡片头部：标题 + 新建按钮同行（避免按钮独占一行、左侧空白） -->
            <div class="flex items-center gap-3 p-6 border-b border-border/50">
              <div class="p-2.5 rounded-xl bg-primary/10 flex items-center justify-center">
                <span class="icon-[lucide--cpu] text-2xl text-primary" />
              </div>
              <div class="flex-1 min-w-0">
                <h2 class="text-lg font-semibold">
                  Provider 凭证管理
                </h2>
                <p class="text-sm text-muted-foreground">
                  管理系统级 LLM Provider 凭证，供全部空间共享
                </p>
              </div>
              <Button
                class="shrink-0"
                @click="providerSettingsRef?.openCreate()"
              >
                <span class="icon-[lucide--plus] w-4 h-4 mr-1" aria-hidden="true" />
                新建凭证
              </Button>
            </div>

            <!-- ProviderSettings 嵌入内容 -->
            <div class="p-6">
              <ProviderSettings ref="providerSettingsRef" scope="system" embedded />
            </div>
          </div>

          <!-- Claude Code 编码配置（选凭证 + opus/sonnet/haiku 三档模型映射） -->
          <div class="card overflow-hidden">
            <div class="flex items-center gap-3 p-6 border-b border-border/50">
              <div class="p-2.5 rounded-xl bg-primary/10 flex items-center justify-center">
                <span class="icon-[lucide--terminal] text-2xl text-primary" />
              </div>
              <div class="flex-1">
                <h2 class="text-lg font-semibold">
                  Claude Code 编码配置
                </h2>
                <p class="text-sm text-muted-foreground">
                  选定编码容器使用的 Provider 凭证，并映射 opus / sonnet / haiku 三档模型
                </p>
              </div>
            </div>
            <div class="p-6">
              <ClaudeCodeConfigPanel />
            </div>
          </div>
        </div>

        <!-- Tab: OIDC 认证 -->
        <div v-show="activeTab === 'oidc'" class="space-y-6">
          <OIDCProviderSettings />
        </div>
      </template>

      <ClaudeTestDialog
        v-model:open="claude.testDialogOpen.value"
        source="system"
      />
    </div>
  </div>
</template>

<style scoped>
/* 隐藏 scrollbar 但保留滚动功能 */
.scrollbar-none {
  -ms-overflow-style: none;
  scrollbar-width: none;
}
.scrollbar-none::-webkit-scrollbar {
  display: none;
}
</style>
