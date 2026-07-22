<script setup lang="ts">
// OBS-05 合并：原有的"集合健康"+"索引新鲜度"两个区块已迁移到 RepoHashFreshnessCard
// （详情页顶部的"索引状态"卡片），本组件聚焦"自动化与 Webhook 配置"主题，
// 避免同一份索引状态信息在两处重复展示。
import type { Repository } from '~/types'
import { ref } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import { Separator } from '~/components/ui/separator'
import { Switch } from '~/components/ui/switch'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const props = defineProps<{
  repository: Repository
}>()

const emit = defineEmits<{
  updated: []
}>()

const { confirm } = useConfirmDialog()
const { handleError } = useErrorHandler()
const { success } = useToast()

const togglingAutoIndex = ref(false)
const generatingSecret = ref(false)
const settingUpWebhook = ref(false)

const webhookUrl = computed(() => {
  const base = window.location.origin
  return `${base}/api/repositories/${props.repository.id}/webhooks/push/`
})

const isGitlab = computed(() => props.repository.git_platform === 'gitlab')

/** 一键配置：调用后端在 GitLab 侧幂等创建/更新 push webhook（默认只订阅默认分支） */
async function setupWebhook() {
  settingUpWebhook.value = true
  try {
    const result = await repositoriesApi.setupWebhook(props.repository.id)
    success(
      result.action === 'created' ? 'Webhook 已创建' : 'Webhook 已更新',
      `已在 GitLab 项目中配置 push webhook（分支：${result.branch_filter || '全部'}）`,
    )
    emit('updated')
  }
  catch (e: unknown) {
    handleError(e, '一键配置 Webhook')
  }
  finally {
    settingUpWebhook.value = false
  }
}

async function toggleAutoIndex(enabled: boolean) {
  togglingAutoIndex.value = true
  try {
    await repositoriesApi.update(props.repository.id, { auto_index_enabled: enabled })
    success(enabled ? '自动索引已启用' : '自动索引已禁用')
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

async function generateSecret() {
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
</script>

<template>
  <div class="card">
    <div class="px-5 py-3.5 border-b border-border/50">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--shield-check] text-primary" />
        <h3 class="text-sm font-semibold">
          自动化与 Webhook
        </h3>
      </div>
      <p class="text-xs text-muted-foreground mt-0.5">
        通过 Webhook 推送或定时轮询自动更新索引
      </p>
    </div>
    <div class="p-5 space-y-5">
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
        <Switch
          :checked="repository.auto_index_enabled"
          :disabled="togglingAutoIndex"
          @update:checked="toggleAutoIndex"
        />
      </div>

      <Separator class="bg-border/50" />

      <!-- Webhook 配置 -->
      <div class="space-y-3">
        <p class="text-sm font-medium text-muted-foreground">
          Webhook 配置
        </p>

        <!-- 一键配置（仅 GitLab：用已配置的 Git 凭证调 API 自动创建 hook） -->
        <div
          v-if="isGitlab"
          class="flex items-center justify-between gap-3 p-3 rounded-lg border border-primary/20 bg-primary/5"
        >
          <div class="min-w-0">
            <p class="text-sm font-medium">
              一键配置 Webhook
            </p>
            <p class="text-xs text-muted-foreground">
              用已配置的 Git 凭证自动在 GitLab 项目中创建 push webhook（默认只订阅默认分支），并启用自动索引
            </p>
          </div>
          <button
            class="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 shrink-0"
            :disabled="settingUpWebhook"
            @click="setupWebhook"
          >
            <span v-if="settingUpWebhook" class="icon-[lucide--loader-circle] animate-spin" />
            <span v-else class="icon-[lucide--zap]" />
            {{ settingUpWebhook ? '配置中...' : '一键配置' }}
          </button>
        </div>

        <div class="space-y-2">
          <div>
            <label class="text-xs text-muted-foreground">Payload URL</label>
            <div class="flex items-center gap-2 mt-1">
              <code class="flex-1 text-xs bg-muted/50 px-3 py-2 rounded-lg font-mono break-all border border-border/50">
                {{ webhookUrl }}
              </code>
              <button
                class="p-2 rounded-lg hover:bg-muted/50 transition-colors shrink-0"
                title="复制 URL"
                @click="copyToClipboard(webhookUrl)"
              >
                <span class="icon-[lucide--copy] text-muted-foreground" />
              </button>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <button
              class="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-border/50 hover:bg-muted/50 transition-colors disabled:opacity-50"
              :disabled="generatingSecret"
              @click="generateSecret"
            >
              <span v-if="generatingSecret" class="icon-[lucide--loader-circle] animate-spin" />
              <span v-else class="icon-[lucide--key-round]" />
              {{ repository.webhook_secret ? '重新生成 Secret' : '生成 Secret' }}
            </button>
          </div>
          <div v-if="repository.webhook_secret">
            <label class="text-xs text-muted-foreground">Secret</label>
            <div class="flex items-center gap-2 mt-1">
              <code class="flex-1 text-xs bg-muted/50 px-3 py-2 rounded-lg font-mono border border-border/50">
                {{ repository.webhook_secret }}
              </code>
              <button
                class="p-2 rounded-lg hover:bg-muted/50 transition-colors shrink-0"
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
