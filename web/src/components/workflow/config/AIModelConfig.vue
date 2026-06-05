<script setup lang="ts">
import type { LLMModel, LLMSystemConfig } from '~/api/workflow'

import { computed, onMounted, ref, watch } from 'vue'

import { getLLMSystemConfig, queryLLMModels, querySystemLLMModels } from '~/api/workflow'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { Separator } from '~/components/ui/separator'
import { Switch } from '~/components/ui/switch'
import { extractErrorMessage } from '~/composables/useErrorHandler'

// ============================================================================
// Props & Emits
// ============================================================================

export interface AIModelConfigValue {
  use_custom_api: boolean
  api_base_url: string
  api_key: string
  model: string
}

interface Props {
  useCustomApi: boolean
  apiBaseUrl: string
  apiKey: string
  model: string
  /** 模型选择标签，默认"模型" */
  modelLabel?: string
  /** 模型描述文字 */
  modelDescription?: string
}

const props = withDefaults(defineProps<Props>(), {
  modelLabel: '模型',
  modelDescription: '',
})

const emit = defineEmits<{
  (e: 'update:useCustomApi', value: boolean): void
  (e: 'update:apiBaseUrl', value: string): void
  (e: 'update:apiKey', value: string): void
  (e: 'update:model', value: string): void
}>()

// ============================================================================
// 本地状态（用于 v-model 绑定）
// ============================================================================

const localUseCustomApi = computed({
  get: () => props.useCustomApi,
  set: v => emit('update:useCustomApi', v),
})

const localApiBaseUrl = computed({
  get: () => props.apiBaseUrl,
  set: v => emit('update:apiBaseUrl', v),
})

const localApiKey = computed({
  get: () => props.apiKey,
  set: v => emit('update:apiKey', v),
})

const localModel = computed({
  get: () => props.model,
  set: v => emit('update:model', v),
})

// ：启用自定义 API 后 API Base URL 必填（228 前端 UX 防御）
// 文案与 UI-SPEC §Fix 4 锁定；后端 validate_config 做保底（服务端拒绝保存）
const apiBaseUrlError = computed<string>(() => {
  if (localUseCustomApi.value && !localApiBaseUrl.value.trim()) {
    return 'API Base URL 为必填（启用自定义 API 后）'
  }
  return ''
})

// ============================================================================
// 系统配置
// ============================================================================

const systemConfig = ref<LLMSystemConfig | null>(null)
const loadingSystemConfig = ref(false)

async function loadSystemConfig() {
  loadingSystemConfig.value = true
  try {
    systemConfig.value = await getLLMSystemConfig()
    // 如果未使用自定义 API 且系统已配置密钥，自动获取模型列表
    if (!localUseCustomApi.value && systemConfig.value?.has_api_key) {
      await fetchSystemModels()
    }
  }
  catch {
    systemConfig.value = null
  }
  finally {
    loadingSystemConfig.value = false
  }
}

onMounted(() => {
  loadSystemConfig()
})

// ============================================================================
// 模型查询
// ============================================================================

const customModels = ref<LLMModel[]>([])
const systemModels = ref<LLMModel[]>([])
const loadingModels = ref(false)
const modelError = ref('')

// 查询自定义 API 模型
async function fetchCustomModels() {
  if (!localApiBaseUrl.value) {
    modelError.value = '请先填写 API Base URL'
    return
  }

  loadingModels.value = true
  modelError.value = ''

  try {
    const result = await queryLLMModels(localApiBaseUrl.value, localApiKey.value)
    customModels.value = result.models
    // 如果当前选中的模型不在列表中，选择第一个
    if (result.models.length > 0 && !result.models.find(m => m.id === localModel.value)) {
      localModel.value = result.models[0].id
    }
  }
  catch (e: unknown) {
    modelError.value = extractErrorMessage(e) || '查询模型失败'
    customModels.value = []
  }
  finally {
    loadingModels.value = false
  }
}

// 查询系统配置的模型
async function fetchSystemModels() {
  if (!systemConfig.value?.has_api_key) {
    modelError.value = '系统未配置 API Key'
    return
  }

  loadingModels.value = true
  modelError.value = ''

  try {
    const result = await querySystemLLMModels()
    systemModels.value = result.models
    // 如果当前选中的模型不在列表中，选择第一个
    if (result.models.length > 0 && !result.models.find(m => m.id === localModel.value)) {
      localModel.value = result.models[0].id
    }
  }
  catch (e: unknown) {
    modelError.value = extractErrorMessage(e) || '查询模型失败'
    systemModels.value = []
  }
  finally {
    loadingModels.value = false
  }
}

// 当切换到自定义 API 时，清空模型和模型列表
watch(localUseCustomApi, (val, oldVal) => {
  if (val !== oldVal) {
    // 切换模式时清空模型
    localModel.value = ''
    modelError.value = ''

    if (val) {
      // 切换到自定义 API：清空自定义模型列表
      customModels.value = []
    }
    else {
      // 切换到系统 API：重新获取系统模型
      if (systemConfig.value?.has_api_key) {
        fetchSystemModels()
      }
    }
  }
})

// 模型列表：根据模式返回不同的选项
const modelOptions = computed(() => {
  if (localUseCustomApi.value) {
    return customModels.value.map(m => ({
      value: m.id,
      label: m.id,
    }))
  }
  return systemModels.value.map(m => ({
    value: m.id,
    label: m.id,
  }))
})

// 当前模式下已查询到的模型数量
const fetchedModelsCount = computed(() => {
  if (localUseCustomApi.value) {
    return customModels.value.length
  }
  return systemModels.value.length
})
</script>

<template>
  <div class="space-y-4">
    <!-- 自定义 API 配置 -->
    <div class="space-y-4 p-4 rounded-xl bg-muted/30 border border-border/50">
      <div class="flex items-center justify-between">
        <div class="space-y-0.5">
          <Label class="text-sm font-medium">使用自定义 API</Label>
          <p class="text-xs text-muted-foreground">
            启用后可配置自定义的 API 地址（支持 OpenAI 兼容协议）
          </p>
        </div>
        <Switch v-model="localUseCustomApi" />
      </div>

      <!-- 系统配置信息（未使用自定义 API 时显示） -->
      <template v-if="!localUseCustomApi && systemConfig">
        <div class="flex items-center gap-2 text-xs text-muted-foreground">
          <span class="icon-[lucide--info] w-3.5 h-3.5" />
          <span>
            使用系统配置：{{ systemConfig.base_url }}
            <span v-if="systemConfig.has_api_key" class="text-green-600">（已配置密钥）</span>
            <span v-else class="text-amber-600">（未配置密钥）</span>
          </span>
        </div>

        <div v-if="modelError" class="text-sm text-destructive">
          {{ modelError }}
        </div>

        <div v-if="fetchedModelsCount > 0" class="text-sm text-muted-foreground">
          已发现 {{ fetchedModelsCount }} 个模型
        </div>
      </template>

      <template v-if="localUseCustomApi">
        <Separator />

        <div class="space-y-2">
          <Label>API Base URL</Label>
          <div class="flex gap-2">
            <Input
              v-model="localApiBaseUrl"
              :aria-invalid="apiBaseUrlError ? 'true' : 'false'"
              :class="apiBaseUrlError ? 'border-destructive' : ''"
              placeholder="https://api.openai.com/v1"
              class="flex-1"
            />
            <Button
              variant="outline"
              size="sm"
              :disabled="loadingModels || !localApiBaseUrl"
              @click="fetchCustomModels"
            >
              <span
                v-if="loadingModels"
                class="icon-[lucide--loader-2] w-4 h-4 mr-1 animate-spin"
              />
              <span v-else class="icon-[lucide--refresh-cw] w-4 h-4 mr-1" />
              查询模型
            </Button>
          </div>
          <p v-if="apiBaseUrlError" class="text-sm text-destructive">
            {{ apiBaseUrlError }}
          </p>
          <p v-else class="text-xs text-muted-foreground">
            支持 OpenAI、Ollama 等兼容 API
          </p>
        </div>

        <div class="space-y-2">
          <Label>API Key（可选）</Label>
          <Input
            v-model="localApiKey"
            type="password"
            placeholder="sk-..."
          />
          <p class="text-xs text-muted-foreground">
            某些本地部署（如 Ollama）无需密钥
          </p>
        </div>

        <div v-if="modelError" class="text-sm text-destructive">
          {{ modelError }}
        </div>

        <div v-if="customModels.length > 0" class="text-sm text-muted-foreground">
          已发现 {{ customModels.length }} 个模型
        </div>
      </template>
    </div>

    <!-- 模型选择 -->
    <div class="space-y-2">
      <Label>{{ modelLabel }}</Label>
      <div class="flex gap-2">
        <Select v-model="localModel" class="flex-1">
          <SelectTrigger>
            <SelectValue placeholder="选择模型" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem
              v-for="option in modelOptions"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </SelectItem>
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="icon"
          :disabled="loadingModels || (localUseCustomApi && !localApiBaseUrl) || (!localUseCustomApi && !systemConfig?.has_api_key)"
          :title="localUseCustomApi ? '从自定义 API 获取模型' : '从系统 API 获取模型'"
          @click="localUseCustomApi ? fetchCustomModels() : fetchSystemModels()"
        >
          <span
            v-if="loadingModels"
            class="icon-[lucide--loader-2] w-4 h-4 animate-spin"
          />
          <span v-else class="icon-[lucide--refresh-cw] w-4 h-4" />
        </Button>
      </div>
      <p v-if="modelDescription" class="text-xs text-muted-foreground">
        {{ modelDescription }}
      </p>
    </div>
  </div>
</template>
