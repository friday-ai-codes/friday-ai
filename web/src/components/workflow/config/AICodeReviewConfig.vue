<script setup lang="ts">
import type { WritableComputedRef } from 'vue'
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'

import { computed } from 'vue'
import ModelSelect from '~/components/providers/ModelSelect.vue'
import ProviderCredentialDropdown from '~/components/providers/ProviderCredentialDropdown.vue'
import { Checkbox } from '~/components/ui/checkbox'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { useConfigModel } from '~/composables/useConfigModel'

/**
 * AICodeReviewConfig - AI 代码审查节点配置面板
 *
 * 配置项：
 * - model: AI 模型标识
 * - use_custom_api: 是否使用自定义 API
 * - api_base_url: 自定义 API 地址
 * - api_key: 自定义 API 密钥
 * - chat_id: 飞书群聊 ID，用于发送审查结果通知
 * - max_iterations: Agent 审查迭代上限
 */

interface AICodeReviewConfig {
  model: string
  use_custom_api: boolean
  api_base_url: string
  api_key: string
  chat_id: string
  max_iterations: number
  provider_credential_id?: string | null
}

interface Props {
  config: AICodeReviewConfig
  workflowNodes?: WorkflowNode[]
  workflowEdges?: WorkflowEdge[]
  currentNodeId?: string
}

const props = withDefaults(defineProps<Props>(), {
  workflowNodes: () => [],
  workflowEdges: () => [],
  currentNodeId: '',
})

const emit = defineEmits<{
  (e: 'update:config', value: AICodeReviewConfig): void
}>()

const { field } = useConfigModel({
  config: () => props.config as unknown as Record<string, unknown>,
  emit: v => emit('update:config', v as unknown as AICodeReviewConfig),
})

const model = field('model', '') as WritableComputedRef<string>
const useCustomApi = field('use_custom_api', false) as WritableComputedRef<boolean>
const apiBaseUrl = field('api_base_url', '') as WritableComputedRef<string>
const apiKey = field('api_key', '') as WritableComputedRef<string>
const chatId = field('chat_id', '') as WritableComputedRef<string>
const maxIterations = field('max_iterations', 30) as WritableComputedRef<number>

// Provider 凭证
// AICodeReviewConfig 模板当前无 thinking / reasoning_effort 控件,按 取舍
// 仅保留字段双向绑定;未来 扩展 thinking UI 时再接入 capability computed。
const providerCredentialIdField = field('provider_credential_id', null) as WritableComputedRef<string | null>
const providerCredentialId = computed<string | null>({
  get: () => providerCredentialIdField.value ?? null,
  set: (v: string | null) => { providerCredentialIdField.value = v },
})

// 数值字段需要 string -> number 转换
const maxIterationsStr = computed({
  get: () => String(maxIterations.value),
  set: (v: string) => { maxIterations.value = Number(v) || 30 },
})
</script>

<template>
  <div class="space-y-4">
    <!-- Introduction -->
    <div class="rounded-xl bg-primary/10 border border-amber-500/20 p-3">
      <div class="flex items-start gap-2">
        <span class="icon-[lucide--search-code] text-amber-500 text-lg shrink-0 mt-0.5" />
        <div class="space-y-1.5">
          <h4 class="text-sm font-medium">
            AI 代码审查
          </h4>
          <p class="text-xs text-muted-foreground leading-relaxed">
            从代码质量、安全性、方案符合度三个维度审查代码变更，输出结构化审查报告。
          </p>

          <!-- Workflow Visual -->
          <div class="flex items-center gap-1 text-[10px] py-1.5 px-2 rounded-lg bg-muted/50">
            <span class="px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium">读取 MR</span>
            <span class="icon-[lucide--arrow-right] text-muted-foreground" />
            <span class="px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium">获取 Diff</span>
            <span class="icon-[lucide--arrow-right] text-muted-foreground" />
            <span class="px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium">AI 审查</span>
            <span class="icon-[lucide--arrow-right] text-muted-foreground" />
            <span class="px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium">生成报告</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Provider 凭证(/05/06) -->
    <div class="space-y-2">
      <Label class="flex items-center gap-1.5 font-normal">
        <span class="icon-[lucide--key-round] text-primary" />
        Provider 凭证
      </Label>
      <ProviderCredentialDropdown
        :model-value="providerCredentialId"
        scope="system"
        @update:model-value="v => providerCredentialId = v"
      />
      <p class="text-xs text-muted-foreground">
        选择一条启用中的 Provider 凭证,未选择则走系统默认
      </p>
    </div>

    <!-- Model(代码审查需要 ReadFile/Grep 工具,UI-06 requires-tools=true) -->
    <div class="space-y-2">
      <Label class="flex items-center gap-1.5 font-normal">
        <span class="icon-[lucide--brain] text-primary" />
        模型
      </Label>
      <ModelSelect
        :credential-id="providerCredentialId"
        :requires-tools="true"
        :model-value="model"
        @update:model-value="v => model = v ?? ''"
      />
      <Input
        v-model="model"
        placeholder="或手动输入模型标识(留空使用系统默认)"
        class="bg-background/50"
      />
      <p class="text-xs text-muted-foreground">
        代码审查使用的 AI 模型,优先按 Provider 凭证的 available_models 列表选择
      </p>
    </div>

    <!-- Use Custom API -->
    <div class="flex items-center gap-2">
      <Checkbox
        :model-value="useCustomApi"
        @update:model-value="(v: boolean | 'indeterminate') => useCustomApi = v === true"
      />
      <Label class="flex items-center gap-1.5 cursor-pointer">
        <span class="icon-[lucide--plug] text-primary" />
        使用自定义 API
      </Label>
    </div>

    <!-- API Base URL (conditional) -->
    <div v-if="useCustomApi" class="space-y-2">
      <Label class="flex items-center gap-1.5">
        <span class="icon-[lucide--link] text-primary" />
        API Base URL
      </Label>
      <Input
        v-model="apiBaseUrl"
        placeholder="https://api.example.com/v1"
        class="bg-background/50"
      />
    </div>

    <!-- API Key (conditional) -->
    <div v-if="useCustomApi" class="space-y-2">
      <Label class="flex items-center gap-1.5">
        <span class="icon-[lucide--key] text-primary" />
        API Key
      </Label>
      <Input
        v-model="apiKey"
        type="password"
        placeholder="sk-..."
        class="bg-background/50"
      />
    </div>

    <!-- Max Iterations -->
    <div class="space-y-2">
      <Label class="flex items-center gap-1.5">
        <span class="icon-[lucide--repeat] text-primary" />
        审查迭代上限
      </Label>
      <Input
        v-model="maxIterationsStr"
        type="number"
        placeholder="30"
        class="bg-background/50"
        min="1"
        max="100"
      />
      <p class="text-xs text-muted-foreground">
        Agent 审查的最大迭代次数，默认 30 次
      </p>
    </div>

    <!-- Chat ID -->
    <div class="space-y-2">
      <Label class="flex items-center gap-1.5">
        <span class="icon-[lucide--message-circle] text-primary" />
        飞书群 ID
      </Label>
      <Input
        v-model="chatId"
        placeholder="输入飞书群 ID"
        class="bg-background/50"
      />
      <p class="text-xs text-muted-foreground">
        审查结果通知将发送到此群。留空则使用上游节点传递的 chat_id。
      </p>
    </div>
  </div>
</template>
