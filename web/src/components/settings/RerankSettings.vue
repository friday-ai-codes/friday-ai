<script setup lang="ts">
import type { SettingRead } from '~/api/settings'
import { onMounted, ref } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import {
  getAllSettings,
  SettingKey,
  updateSetting,
} from '~/api/settings'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Switch } from '~/components/ui/switch'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const { handleError } = useErrorHandler()
const { success, error: showError, info } = useToast()

// 模型名预设：点击仅填入「模型」字段，API 地址 / Key 由用户按文档自行填写。
interface ModelPreset {
  model: string
  hint: string
}
const MODEL_PRESETS: ModelPreset[] = [
  { model: 'qwen3-rerank', hint: '阿里云百炼' },
  { model: 'Qwen/Qwen3-Reranker-8B', hint: 'SiliconFlow' },
  { model: 'Qwen/Qwen3-Reranker-4B', hint: 'SiliconFlow，更快' },
  { model: 'BAAI/bge-reranker-v2-m3', hint: '开源多语言' },
]

// 配置引导文档：帮助用户找到各服务商的 Rerank API 地址与可用模型。
const DOC_LINKS: { label: string, url: string }[] = [
  { label: '阿里云百炼 Rerank 文档', url: 'https://help.aliyun.com/zh/model-studio/text-rerank-api' },
  { label: 'SiliconFlow Rerank 文档', url: 'https://docs.siliconflow.cn/cn/api-reference/rerank/create-rerank' },
]

const settings = ref<SettingRead[]>([])
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)

// 表单值
const rerankerEnabled = ref(false)
const apiUrl = ref('')
const apiKey = ref('')
const model = ref('')
const topN = ref('10')
const fetchK = ref('50')
const heuristicEnabled = ref(true)
const showApiKey = ref(false)

// dirty 跟踪
const dirty = ref<Record<string, boolean>>({})
function markDirty(key: string) {
  dirty.value[key] = true
}

const health = ref<{ status: string, message?: string } | null>(null)

function getValue(key: SettingKey): string {
  return settings.value.find(s => s.key === key)?.value || ''
}

async function loadSettings() {
  loading.value = true
  try {
    settings.value = await getAllSettings()

    rerankerEnabled.value = getValue(SettingKey.RERANKER_ENABLED) === 'true'
    apiUrl.value = getValue(SettingKey.RERANKER_API_URL)
    apiKey.value = settings.value.find(s => s.key === SettingKey.RERANKER_API_KEY)?.has_value
      ? getValue(SettingKey.RERANKER_API_KEY)
      : ''
    model.value = getValue(SettingKey.RERANKER_MODEL)
    topN.value = getValue(SettingKey.RERANKER_TOP_N) || '10'
    fetchK.value = getValue(SettingKey.RERANK_FETCH_K) || '50'
    // 启发式降级默认开启：未配置时按后端默认行为对齐
    const heuristicRaw = settings.value.find(s => s.key === SettingKey.HEURISTIC_RERANK_ENABLED)?.value
    heuristicEnabled.value = heuristicRaw == null ? true : heuristicRaw === 'true'

    dirty.value = {}
  }
  catch (e: unknown) {
    handleError(e, '加载 Rerank 设置')
  }
  finally {
    loading.value = false
  }
}

function applyModelPreset(modelName: string) {
  model.value = modelName
  markDirty(SettingKey.RERANKER_MODEL)
}

async function saveAll() {
  saving.value = true
  try {
    const promises: Promise<unknown>[] = []
    const push = (key: SettingKey, value: string) => {
      if (dirty.value[key])
        promises.push(updateSetting(key, value))
    }

    push(SettingKey.RERANKER_ENABLED, rerankerEnabled.value ? 'true' : 'false')
    if (dirty.value[SettingKey.RERANKER_API_URL] && apiUrl.value.trim())
      promises.push(updateSetting(SettingKey.RERANKER_API_URL, apiUrl.value.trim()))
    if (dirty.value[SettingKey.RERANKER_API_KEY] && apiKey.value.trim())
      promises.push(updateSetting(SettingKey.RERANKER_API_KEY, apiKey.value.trim()))
    if (dirty.value[SettingKey.RERANKER_MODEL] && model.value.trim())
      promises.push(updateSetting(SettingKey.RERANKER_MODEL, model.value.trim()))
    push(SettingKey.RERANKER_TOP_N, topN.value)
    push(SettingKey.RERANK_FETCH_K, fetchK.value)
    push(SettingKey.HEURISTIC_RERANK_ENABLED, heuristicEnabled.value ? 'true' : 'false')

    if (promises.length === 0) {
      info('没有需要保存的更改')
      return
    }
    await Promise.all(promises)
    success('Rerank 设置已保存')
    await loadSettings()
  }
  catch (e: unknown) {
    handleError(e, '保存')
  }
  finally {
    saving.value = false
  }
}

async function testConnection() {
  testing.value = true
  try {
    const url = apiUrl.value.trim()
    if (!url) {
      showError('请先填写 Reranker API 地址')
      health.value = { status: 'error', message: '未填写 API 地址' }
      return
    }
    const result = await repositoriesApi.testRerankerConnection(
      url,
      model.value.trim() || 'qwen3-rerank',
      dirty.value[SettingKey.RERANKER_API_KEY] ? apiKey.value.trim() || undefined : undefined,
    )
    health.value = result
    if (result.status === 'healthy')
      success('Reranker API 连接成功')
    else
      showError(`Reranker API 连接失败: ${result.message}`)
  }
  catch (e: unknown) {
    handleError(e, '测试 Reranker 连接')
    health.value = { status: 'error', message: String(e) }
  }
  finally {
    testing.value = false
  }
}

const hasChanges = () => Object.values(dirty.value).some(Boolean)

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
          <span class="icon-[lucide--arrow-up-down] text-2xl text-violet-500" />
        </div>
        <div>
          <h2 class="text-lg font-semibold">
            重排序 (Rerank)
          </h2>
          <p class="text-sm text-muted-foreground">
            对召回结果做精排，提升代码检索相关性。生效于对话 / Agent / 工作流全链路。
          </p>
        </div>
      </div>

      <div v-if="loading" class="flex items-center justify-center gap-3 p-12">
        <span class="icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
        <span class="text-muted-foreground">加载设置...</span>
      </div>

      <div v-else class="p-6 space-y-8">
        <!-- 1. Rerank 模型 -->
        <div class="space-y-4">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <span class="icon-[lucide--sparkles]" />
              <span>Rerank 模型 (API)</span>
              <span
                v-if="health"
                :class="[
                  health.status === 'healthy' ? 'icon-[lucide--check-circle] text-emerald-500' : 'icon-[lucide--x-circle] text-destructive',
                ]"
              />
            </div>
            <Switch
              :model-value="rerankerEnabled"
              @update:model-value="(val: boolean) => { rerankerEnabled = val; markDirty(SettingKey.RERANKER_ENABLED) }"
            />
          </div>

          <div class="rounded-xl bg-muted/30 border border-border/30 p-4 space-y-4">
            <p class="text-sm text-muted-foreground">
              用 Cross-Encoder 对初筛候选精排。先在「服务商」选预设自动填好地址与模型，再填 API Key 即可。
            </p>

            <div v-if="rerankerEnabled" class="space-y-4">
              <!-- 配置引导：如何获取 API 地址与可用模型 -->
              <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span class="icon-[lucide--book-open]" />
                <span>如何配置 API 地址与模型？参考：</span>
                <a
                  v-for="link in DOC_LINKS"
                  :key="link.url"
                  :href="link.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="inline-flex items-center gap-1 text-primary hover:underline"
                >
                  {{ link.label }}
                  <span class="icon-[lucide--external-link] text-[0.9em]" />
                </a>
              </div>

              <div class="grid gap-4 md:grid-cols-2">
                <div class="space-y-2">
                  <Label for="rerank-api-url">Reranker API 地址</Label>
                  <Input
                    id="rerank-api-url"
                    v-model="apiUrl"
                    type="url"
                    placeholder="https://api.example.com/v1/rerank"
                    class="h-10 bg-muted/30 border-border/50 focus:border-primary/50"
                    @input="markDirty(SettingKey.RERANKER_API_URL)"
                  />
                </div>

                <div class="space-y-2">
                  <Label for="rerank-api-key">API Key</Label>
                  <div class="relative">
                    <Input
                      id="rerank-api-key"
                      v-model="apiKey"
                      :type="showApiKey ? 'text' : 'password'"
                      placeholder="留空表示无需认证"
                      class="pr-10 h-10 bg-muted/30 border-border/50 focus:border-primary/50"
                      @input="markDirty(SettingKey.RERANKER_API_KEY)"
                    />
                    <button
                      type="button"
                      class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                      @click="showApiKey = !showApiKey"
                    >
                      <span :class="showApiKey ? 'icon-[lucide--eye-off]' : 'icon-[lucide--eye]'" />
                    </button>
                  </div>
                </div>

                <div class="space-y-2">
                  <Label for="rerank-model">模型</Label>
                  <Input
                    id="rerank-model"
                    v-model="model"
                    placeholder="qwen3-rerank"
                    class="h-10 bg-muted/30 border-border/50 focus:border-primary/50"
                    @input="markDirty(SettingKey.RERANKER_MODEL)"
                  />
                  <div class="flex flex-wrap gap-1.5 pt-1">
                    <button
                      v-for="m in MODEL_PRESETS"
                      :key="m.model"
                      type="button"
                      :title="m.hint"
                      class="px-2 py-1 rounded-md text-xs border transition-colors"
                      :class="model === m.model
                        ? 'border-primary/60 bg-primary/10 text-primary'
                        : 'border-border/50 text-muted-foreground hover:bg-muted/50'"
                      @click="applyModelPreset(m.model)"
                    >
                      {{ m.model }}
                    </button>
                  </div>
                </div>

                <div class="space-y-2">
                  <Label for="rerank-top-n">精排 Top N</Label>
                  <Input
                    id="rerank-top-n"
                    v-model="topN"
                    type="number"
                    min="1"
                    max="50"
                    placeholder="10"
                    class="h-10 bg-muted/30 border-border/50 focus:border-primary/50"
                    @input="markDirty(SettingKey.RERANKER_TOP_N)"
                  />
                </div>

                <div class="space-y-2">
                  <Label for="rerank-fetch-k">召回候选数 (fetch_k)</Label>
                  <Input
                    id="rerank-fetch-k"
                    v-model="fetchK"
                    type="number"
                    min="10"
                    max="200"
                    placeholder="50"
                    class="h-10 bg-muted/30 border-border/50 focus:border-primary/50"
                    @input="markDirty(SettingKey.RERANK_FETCH_K)"
                  />
                  <p class="text-xs text-muted-foreground">
                    精排前先召回多少条候选交给 reranker，越大越准但越慢
                  </p>
                </div>
              </div>

              <Button
                variant="outline"
                size="sm"
                :disabled="testing"
                @click="testConnection"
              >
                <span v-if="testing" class="icon-[lucide--loader-circle] animate-spin mr-2" />
                <span v-else class="icon-[lucide--plug] mr-2" />
                测试连接
              </Button>
            </div>
          </div>
        </div>

        <!-- 2. 启发式降级（仅在未启用 Rerank 模型时展示） -->
        <div v-if="!rerankerEnabled" class="space-y-4">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <span class="icon-[lucide--list-ordered]" />
              <span>启发式重排（默认开启）</span>
            </div>
            <Switch
              :model-value="heuristicEnabled"
              @update:model-value="(val: boolean) => { heuristicEnabled = val; markDirty(SettingKey.HEURISTIC_RERANK_ENABLED) }"
            />
          </div>
          <div class="rounded-xl bg-muted/30 border border-border/30 p-4">
            <p class="text-sm text-muted-foreground">
              未启用 Rerank 模型时的兜底排序：在向量分数基础上叠加精确标识符匹配、查询词覆盖率、
              路径相关性、定义优先等词法信号，不依赖任何外部服务、几乎零开销。默认开启，建议保留。
            </p>
          </div>
        </div>
      </div>

      <div class="flex justify-end px-6 py-4 border-t border-border/50">
        <Button
          :disabled="saving || !hasChanges()"
          @click="saveAll"
        >
          <span v-if="saving" class="icon-[lucide--loader-circle] animate-spin mr-2" />
          <span v-else class="icon-[lucide--save] mr-2" />
          保存设置
        </Button>
      </div>
    </div>
  </section>
</template>
