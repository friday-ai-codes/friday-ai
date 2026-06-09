<script setup lang="ts">
import type { SettingRead } from '~/api/settings'
import { onMounted, ref } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import {
  getAllSettings,
  SettingKey,
  updateSetting,
} from '~/api/settings'
import { getSetupStatus } from '~/api/setup'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const { handleError } = useErrorHandler()
const { success, error: showError, info, warning } = useToast()

// 设置状态
const settings = ref<SettingRead[]>([])
const loading = ref(true)
const saving = ref(false)
const testingQdrant = ref(false)
const testingEmbedding = ref(false)

// 表单值
const qdrantUrlValue = ref('')
const qdrantApiKeyValue = ref('')
const embeddingApiUrlValue = ref('')
const embeddingApiKeyValue = ref('')
const embeddingModelValue = ref('')
const embeddingDimensionValue = ref('')

// 跟踪用户是否修改了值
const qdrantUrlDirty = ref(false)
const qdrantApiKeyDirty = ref(false)
const embeddingApiUrlDirty = ref(false)
const embeddingApiKeyDirty = ref(false)
const embeddingModelDirty = ref(false)
const embeddingDimensionDirty = ref(false)

const showQdrantApiKey = ref(false)
const showEmbeddingApiKey = ref(false)

// Qdrant 是否由部署环境（env QDRANT_URL）托管：托管时锁定地址/密钥，server 以 env 为准，
// 此处 DB 中的值不会生效，故置为只读避免误导用户。
const qdrantManaged = ref(false)

// 健康状态
const qdrantHealth = ref<{ status: string, message?: string } | null>(null)
const embeddingHealth = ref<{ status: string, message?: string } | null>(null)

// 设置项元数据
const settingsMeta: Record<string, { label: string, description: string, placeholder: string }> = {
  [SettingKey.QDRANT_URL]: {
    label: 'Qdrant 服务地址',
    description: 'Qdrant 向量数据库 HTTP 地址',
    placeholder: 'http://localhost:6333',
  },
  [SettingKey.QDRANT_API_KEY]: {
    label: 'Qdrant API Key',
    description: 'Qdrant 服务的 API 密钥（可选，加密存储）',
    placeholder: '留空表示无需认证',
  },
  [SettingKey.EMBEDDING_API_URL]: {
    label: 'Embedding API 地址',
    description: '完整的 API 端点地址，OpenAI 兼容格式需包含 /v1/embeddings，Ollama 需包含 /api/embeddings',
    placeholder: 'https://api.example.com/v1/embeddings',
  },
  [SettingKey.EMBEDDING_API_KEY]: {
    label: 'Embedding API Key',
    description: 'Embedding 服务的 API 密钥（可选，加密存储）',
    placeholder: '留空表示无需认证',
  },
  [SettingKey.EMBEDDING_MODEL]: {
    label: 'Embedding 模型',
    description: '使用的 Embedding 模型名称',
    placeholder: 'BAAI/bge-m3',
  },
  [SettingKey.EMBEDDING_DIMENSION]: {
    label: '向量维度',
    description: 'Embedding 向量的维度大小',
    placeholder: '1024',
  },
}

// 加载设置
async function loadSettings() {
  loading.value = true
  try {
    settings.value = await getAllSettings()

    // 填充表单值
    const getValue = (key: SettingKey) => settings.value.find(s => s.key === key)?.value || ''
    const getMasked = (key: SettingKey) => {
      const setting = settings.value.find(s => s.key === key)
      return setting?.has_value ? setting.value || '' : ''
    }

    qdrantUrlValue.value = getValue(SettingKey.QDRANT_URL)
    qdrantApiKeyValue.value = getMasked(SettingKey.QDRANT_API_KEY)

    // 检测 Qdrant 是否被 env 托管；若是，用真实 env 地址覆盖展示并锁定
    try {
      const setupStatus = await getSetupStatus()
      qdrantManaged.value = Boolean(setupStatus.qdrant_bundled)
      if (qdrantManaged.value && setupStatus.qdrant_url)
        qdrantUrlValue.value = setupStatus.qdrant_url
    }
    catch {
      qdrantManaged.value = false
    }
    embeddingApiUrlValue.value = getValue(SettingKey.EMBEDDING_API_URL)
    embeddingApiKeyValue.value = getMasked(SettingKey.EMBEDDING_API_KEY)
    embeddingModelValue.value = getValue(SettingKey.EMBEDDING_MODEL)
    embeddingDimensionValue.value = getValue(SettingKey.EMBEDDING_DIMENSION)

    // 重置脏标记
    resetDirtyFlags()
  }
  catch (e: unknown) {
    handleError(e, '加载设置')
  }
  finally {
    loading.value = false
  }
}

function resetDirtyFlags() {
  qdrantUrlDirty.value = false
  qdrantApiKeyDirty.value = false
  embeddingApiUrlDirty.value = false
  embeddingApiKeyDirty.value = false
  embeddingModelDirty.value = false
  embeddingDimensionDirty.value = false
}

// 保存所有设置
async function saveAllSettings() {
  saving.value = true
  try {
    const promises: Promise<unknown>[] = []

    if (qdrantUrlDirty.value && qdrantUrlValue.value.trim())
      promises.push(updateSetting(SettingKey.QDRANT_URL, qdrantUrlValue.value.trim()))

    if (qdrantApiKeyDirty.value && qdrantApiKeyValue.value.trim())
      promises.push(updateSetting(SettingKey.QDRANT_API_KEY, qdrantApiKeyValue.value.trim()))

    if (embeddingApiUrlDirty.value && embeddingApiUrlValue.value.trim())
      promises.push(updateSetting(SettingKey.EMBEDDING_API_URL, embeddingApiUrlValue.value.trim()))

    if (embeddingApiKeyDirty.value && embeddingApiKeyValue.value.trim())
      promises.push(updateSetting(SettingKey.EMBEDDING_API_KEY, embeddingApiKeyValue.value.trim()))

    if (embeddingModelDirty.value && embeddingModelValue.value.trim())
      promises.push(updateSetting(SettingKey.EMBEDDING_MODEL, embeddingModelValue.value.trim()))

    if (embeddingDimensionDirty.value && embeddingDimensionValue.value)
      promises.push(updateSetting(SettingKey.EMBEDDING_DIMENSION, String(embeddingDimensionValue.value)))

    if (promises.length === 0) {
      info('没有需要保存的更改')
      return
    }

    await Promise.all(promises)
    success('设置已保存')
    await loadSettings()
  }
  catch (e: unknown) {
    handleError(e, '保存')
  }
  finally {
    saving.value = false
  }
}

// 检查是否有未保存的更改
function hasUnsavedChanges(): boolean {
  return qdrantUrlDirty.value || qdrantApiKeyDirty.value || embeddingApiUrlDirty.value
    || embeddingApiKeyDirty.value || embeddingModelDirty.value || embeddingDimensionDirty.value
}

// 测试 Qdrant 连接
async function testQdrantConnection() {
  testingQdrant.value = true
  try {
    const result = await repositoriesApi.testQdrantConnection(qdrantUrlValue.value, qdrantApiKeyDirty.value ? qdrantApiKeyValue.value || undefined : undefined)
    qdrantHealth.value = result
    if (result.status === 'healthy') {
      success('Qdrant 连接成功')
    }
    else {
      showError(`Qdrant 连接失败: ${result.message || result.error || '未知错误'}`)
    }
  }
  catch (e: unknown) {
    handleError(e, '测试 Qdrant 连接')
    qdrantHealth.value = { status: 'error', message: String(e) }
  }
  finally {
    testingQdrant.value = false
  }
}

// 测试 Embedding API 连接
async function testEmbeddingConnection() {
  testingEmbedding.value = true
  try {
    // 使用表单中的值测试（无需先保存）
    const apiUrl = embeddingApiUrlValue.value.trim()
    const model = embeddingModelValue.value.trim() || 'BAAI/bge-m3'

    if (!apiUrl) {
      showError('请先填写 Embedding API 地址')
      embeddingHealth.value = { status: 'error', message: 'Embedding API URL is required' }
      return
    }

    const result = await repositoriesApi.testEmbeddingConnection(
      apiUrl,
      model,
      embeddingApiKeyDirty.value ? embeddingApiKeyValue.value.trim() || undefined : undefined,
      embeddingDimensionValue.value ? Number(embeddingDimensionValue.value) : undefined,
    )
    embeddingHealth.value = result
    if (result.status === 'healthy') {
      success(`Embedding API 连接成功，维度: ${result.dimension}`)
    }
    else if (result.status === 'warning') {
      warning(result.message ?? '连接警告')
    }
    else {
      showError(`Embedding API 连接失败: ${result.message}`)
    }
  }
  catch (e: unknown) {
    handleError(e, '测试 Embedding 连接')
    embeddingHealth.value = { status: 'error', message: String(e) }
  }
  finally {
    testingEmbedding.value = false
  }
}

function getHealthStatusColor(status: string | undefined) {
  switch (status) {
    case 'healthy':
      return 'text-emerald-500'
    case 'warning':
    case 'not_configured':
      return 'text-amber-500'
    default:
      return 'text-destructive'
  }
}

function getHealthStatusIcon(status: string | undefined) {
  switch (status) {
    case 'healthy':
      return 'icon-[lucide--check-circle]'
    case 'not_configured':
      return 'icon-[lucide--info]'
    default:
      return 'icon-[lucide--x-circle]'
  }
}

onMounted(() => {
  loadSettings()
})
</script>

<template>
  <section class="group relative">
    <div class="card overflow-hidden">
      <!-- 卡片头部 -->
      <div class="flex items-center gap-3 p-6 border-b border-border/50">
        <div class="p-2.5 rounded-xl bg-primary/10 flex items-center justify-center">
          <span class="icon-[lucide--database] text-2xl text-cyan-500" />
        </div>
        <div>
          <h2 class="text-lg font-semibold">
            向量索引配置
          </h2>
          <p class="text-sm text-muted-foreground">
            配置代码 RAG 系统的向量数据库和 Embedding 服务
          </p>
        </div>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="flex items-center justify-center gap-3 p-12">
        <span class="icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
        <span class="text-muted-foreground">加载设置...</span>
      </div>

      <!-- 表单内容 -->
      <div v-else class="p-6 space-y-8">
        <!-- Qdrant 配置 -->
        <div class="space-y-4">
          <div class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <span class="icon-[lucide--server]" />
            <span>Qdrant 向量数据库</span>
            <span
              v-if="qdrantHealth"
              :class="[getHealthStatusIcon(qdrantHealth.status), getHealthStatusColor(qdrantHealth.status)]"
            />
          </div>

          <p
            v-if="qdrantManaged"
            class="flex items-center gap-1.5 text-xs text-muted-foreground"
          >
            <span class="icon-[lucide--lock] text-[0.7rem] shrink-0" />
            Qdrant 地址由部署环境（环境变量）管理，此处不可修改。
          </p>

          <div class="grid gap-4 md:grid-cols-2">
            <!-- Qdrant URL -->
            <div class="space-y-2">
              <Label for="qdrant-url">{{ settingsMeta[SettingKey.QDRANT_URL].label }}</Label>
              <div class="relative">
                <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--link] text-muted-foreground" />
                <Input
                  id="qdrant-url"
                  v-model="qdrantUrlValue"
                  type="url"
                  :placeholder="settingsMeta[SettingKey.QDRANT_URL].placeholder"
                  :readonly="qdrantManaged"
                  class="pl-10 h-10 bg-muted/30 border-border/50 focus:border-primary/50"
                  :class="qdrantManaged ? 'opacity-70 cursor-not-allowed' : ''"
                  @input="qdrantUrlDirty = true"
                />
              </div>
              <p class="text-xs text-muted-foreground">
                {{ settingsMeta[SettingKey.QDRANT_URL].description }}
              </p>
            </div>

            <!-- Qdrant API Key -->
            <div class="space-y-2">
              <Label for="qdrant-api-key">{{ settingsMeta[SettingKey.QDRANT_API_KEY].label }}</Label>
              <div class="relative">
                <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key] text-muted-foreground" />
                <Input
                  id="qdrant-api-key"
                  v-model="qdrantApiKeyValue"
                  :type="showQdrantApiKey ? 'text' : 'password'"
                  :placeholder="settingsMeta[SettingKey.QDRANT_API_KEY].placeholder"
                  :readonly="qdrantManaged"
                  class="pl-10 pr-10 h-10 bg-muted/30 border-border/50 focus:border-primary/50"
                  :class="qdrantManaged ? 'opacity-70 cursor-not-allowed' : ''"
                  @input="qdrantApiKeyDirty = true"
                />
                <button
                  type="button"
                  class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                  @click="showQdrantApiKey = !showQdrantApiKey"
                >
                  <span :class="showQdrantApiKey ? 'icon-[lucide--eye-off]' : 'icon-[lucide--eye]'" />
                </button>
              </div>
              <p class="text-xs text-muted-foreground">
                {{ settingsMeta[SettingKey.QDRANT_API_KEY].description }}
              </p>
            </div>
          </div>

          <Button
            variant="outline"
            size="sm"
            :disabled="testingQdrant"
            @click="testQdrantConnection"
          >
            <span v-if="testingQdrant" class="icon-[lucide--loader-circle] animate-spin mr-2" />
            <span v-else class="icon-[lucide--plug] mr-2" />
            测试 Qdrant 连接
          </Button>
        </div>

        <!-- Embedding 配置 -->
        <div class="space-y-4">
          <div class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <span class="icon-[lucide--brain]" />
            <span>Embedding API</span>
            <span
              v-if="embeddingHealth"
              :class="[getHealthStatusIcon(embeddingHealth.status), getHealthStatusColor(embeddingHealth.status)]"
            />
          </div>

          <div class="grid gap-4 md:grid-cols-2">
            <!-- Embedding API URL -->
            <div class="space-y-2">
              <Label for="embedding-api-url">{{ settingsMeta[SettingKey.EMBEDDING_API_URL].label }}</Label>
              <div class="relative">
                <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--link] text-muted-foreground" />
                <Input
                  id="embedding-api-url"
                  v-model="embeddingApiUrlValue"
                  type="url"
                  :placeholder="settingsMeta[SettingKey.EMBEDDING_API_URL].placeholder"
                  class="pl-10 h-10 bg-muted/30 border-border/50 focus:border-primary/50"
                  @input="embeddingApiUrlDirty = true"
                />
              </div>
            </div>

            <!-- Embedding API Key -->
            <div class="space-y-2">
              <Label for="embedding-api-key">{{ settingsMeta[SettingKey.EMBEDDING_API_KEY].label }}</Label>
              <div class="relative">
                <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key] text-muted-foreground" />
                <Input
                  id="embedding-api-key"
                  v-model="embeddingApiKeyValue"
                  :type="showEmbeddingApiKey ? 'text' : 'password'"
                  :placeholder="settingsMeta[SettingKey.EMBEDDING_API_KEY].placeholder"
                  class="pl-10 pr-10 h-10 bg-muted/30 border-border/50 focus:border-primary/50"
                  @input="embeddingApiKeyDirty = true"
                />
                <button
                  type="button"
                  class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                  @click="showEmbeddingApiKey = !showEmbeddingApiKey"
                >
                  <span :class="showEmbeddingApiKey ? 'icon-[lucide--eye-off]' : 'icon-[lucide--eye]'" />
                </button>
              </div>
              <p class="text-xs text-muted-foreground">
                {{ settingsMeta[SettingKey.EMBEDDING_API_KEY].description }}
              </p>
            </div>

            <!-- Embedding Model -->
            <div class="space-y-2">
              <Label for="embedding-model">{{ settingsMeta[SettingKey.EMBEDDING_MODEL].label }}</Label>
              <Input
                id="embedding-model"
                v-model="embeddingModelValue"
                :placeholder="settingsMeta[SettingKey.EMBEDDING_MODEL].placeholder"
                class="h-10 bg-muted/30 border-border/50 focus:border-primary/50"
                @input="embeddingModelDirty = true"
              />
            </div>

            <!-- Embedding Dimension -->
            <div class="space-y-2">
              <Label for="embedding-dimension">{{ settingsMeta[SettingKey.EMBEDDING_DIMENSION].label }}</Label>
              <Input
                id="embedding-dimension"
                v-model="embeddingDimensionValue"
                type="number"
                :placeholder="settingsMeta[SettingKey.EMBEDDING_DIMENSION].placeholder"
                class="h-10 bg-muted/30 border-border/50 focus:border-primary/50"
                @input="embeddingDimensionDirty = true"
              />
            </div>
          </div>

          <Button
            variant="outline"
            size="sm"
            :disabled="testingEmbedding"
            @click="testEmbeddingConnection"
          >
            <span v-if="testingEmbedding" class="icon-[lucide--loader-circle] animate-spin mr-2" />
            <span v-else class="icon-[lucide--plug] mr-2" />
            测试 Embedding API
          </Button>
        </div>
      </div>

      <!-- 保存按钮区域 -->
      <div class="flex justify-end px-6 py-4 border-t border-border/50">
        <Button
          :disabled="saving || !hasUnsavedChanges()"
          class="group/btn relative overflow-hidden"
          @click="saveAllSettings"
        >
          <span class="absolute inset-0 translate-x-[-100%] group-hover/btn:translate-x-[100%] transition-transform duration-700" />
          <span v-if="saving" class="icon-[lucide--loader-circle] animate-spin mr-2" />
          <span v-else class="icon-[lucide--save] mr-2" />
          保存设置
        </Button>
      </div>
    </div>
  </section>
</template>
