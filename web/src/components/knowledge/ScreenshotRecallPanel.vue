<script setup lang="ts">
import type { ScreenshotRecallResult } from '~/api/screenshotRecall'
import { useMutation } from '@tanstack/vue-query'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { screenshotRecallApi } from '~/api/screenshotRecall'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Button } from '~/components/ui/button'
import { Skeleton } from '~/components/ui/skeleton'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { error: toastError } = useToast()

// 前后端共享语义阈值（后端 35-01 为权威，前端为体验前置）。
const MAX_SIZE = 10 * 1024 * 1024
const ACCEPTED_TYPES = ['image/png', 'image/jpeg', 'image/webp']

// ==================== 上传 / 校验态 ====================
const file = ref<File | null>(null)
const previewUrl = ref('')
const validationError = ref('')
const isDragging = ref(false)
const dropzoneRef = ref<HTMLElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

// ==================== 结果态 ====================
// result 仅在 onSuccess 写入；mutation rejected 时不清空（保留上次成功/降级结果）。
const result = ref<ScreenshotRecallResult | null>(null)
const semanticsExpanded = ref(false)

const mutation = useMutation({
  mutationFn: (f: File) => screenshotRecallApi.recall(f),
  onSuccess: (data) => {
    result.value = data
  },
  onError: (e) => {
    // 错误态：红字 + toast（降级态走 onSuccess，不在此弹错误 toast）。
    handleError(e, t('screenshotRecall.title'))
  },
})

const isPending = computed(() => mutation.isPending.value)
const isError = computed(() => mutation.isError.value)

const hasSemantics = computed(() => {
  const s = result.value?.semantics
  return !!s && !!(s.text || s.ui_elements || s.business_intent)
})

// 降级双因（WR-01）：extraction_failed 为运行期失败（模型已配置），不引导去系统设置，
// 改提示重试；no_vision_model（或缺 code 的旧响应）走配置文案 + 系统设置入口。
const isExtractionFailed = computed(
  () => result.value?.degraded_code === 'extraction_failed',
)
const degradedTitle = computed(() =>
  isExtractionFailed.value
    ? t('screenshotRecall.degraded.extractionFailedTitle')
    : t('screenshotRecall.degraded.title'),
)
const degradedBody = computed(() =>
  isExtractionFailed.value
    ? t('screenshotRecall.degraded.extractionFailedBody')
    : t('screenshotRecall.degraded.body'),
)
const showSettingsLink = computed(() => !isExtractionFailed.value)

// ==================== 文件释放（防 objectURL 内存泄漏，T-35F-03） ====================
function revokePreview() {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
}

function focusDropzone() {
  nextTick(() => dropzoneRef.value?.focus())
}

/** 三种上传入口（点击/拖拽/粘贴）统一汇入：先校验，再预览。 */
function handleFile(f: File) {
  validationError.value = ''
  if (!ACCEPTED_TYPES.includes(f.type)) {
    validationError.value = t('screenshotRecall.validation.invalidType')
    toastError(validationError.value)
    focusDropzone()
    return
  }
  if (f.size > MAX_SIZE) {
    validationError.value = t('screenshotRecall.validation.tooLarge')
    toastError(validationError.value)
    focusDropzone()
    return
  }
  revokePreview()
  file.value = f
  previewUrl.value = URL.createObjectURL(f)
}

function openFilePicker() {
  fileInputRef.value?.click()
}

function onInputChange(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  if (f)
    handleFile(f)
  // 复位以便重复选择同一文件仍触发 change。
  input.value = ''
}

function onDrop(e: DragEvent) {
  isDragging.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f)
    handleFile(f)
}

function onPaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items)
    return
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      const f = item.getAsFile()
      if (f) {
        handleFile(f)
        break
      }
    }
  }
}

function removeFile() {
  revokePreview()
  file.value = null
  validationError.value = ''
  result.value = null
  mutation.reset()
  focusDropzone()
}

function onSubmit() {
  if (!file.value) {
    validationError.value = t('screenshotRecall.validation.required')
    toastError(validationError.value)
    focusDropzone()
    return
  }
  mutation.mutate(file.value)
}

function formatSize(bytes: number): string {
  if (bytes < 1024)
    return `${bytes} B`
  if (bytes < 1024 * 1024)
    return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function relevancePercent(relevance: number): number {
  return Math.round(relevance * 100)
}

onMounted(() => window.addEventListener('paste', onPaste))
onBeforeUnmount(() => {
  window.removeEventListener('paste', onPaste)
  revokePreview()
})
</script>

<template>
  <div class="space-y-8">
    <!-- ==================== 上传卡片 ==================== -->
    <div class="card">
      <div class="px-5 py-3.5 border-b border-border/50">
        <div class="flex items-center gap-2">
          <span class="icon-[lucide--scan-search] text-primary" aria-hidden="true" />
          <h3 class="text-sm font-semibold">
            {{ t('screenshotRecall.title') }}
          </h3>
        </div>
        <p class="text-xs text-muted-foreground mt-0.5">
          {{ t('screenshotRecall.subtitle') }}
        </p>
      </div>

      <div class="p-5 space-y-4">
        <!-- Dropzone（无选中时）：点击 / 拖拽 / 键盘激活 -->
        <div
          v-if="!file"
          ref="dropzoneRef"
          role="button"
          tabindex="0"
          :aria-label="t('screenshotRecall.upload.dropzoneTitle')"
          aria-describedby="recall-dropzone-hint"
          class="flex flex-col items-center justify-center gap-2 min-h-40 rounded-lg border-2 border-dashed border-border px-4 py-6 text-center cursor-pointer transition-colors hover:border-primary/60"
          :class="isDragging ? 'border-primary bg-primary/5' : ''"
          data-testid="recall-dropzone"
          @click="openFilePicker"
          @keydown.enter.prevent="openFilePicker"
          @keydown.space.prevent="openFilePicker"
          @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false"
          @drop.prevent="onDrop"
        >
          <span class="icon-[lucide--image-up] text-2xl text-muted-foreground/70" aria-hidden="true" />
          <p class="text-sm font-medium">
            {{ t('screenshotRecall.upload.dropzoneTitle') }}
          </p>
          <p id="recall-dropzone-hint" class="text-xs text-muted-foreground">
            {{ t('screenshotRecall.upload.dropzoneHint') }}
          </p>
          <span class="mt-1 text-xs text-primary">
            {{ t('screenshotRecall.upload.selectButton') }}
          </span>
          <input
            ref="fileInputRef"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            class="sr-only"
            data-testid="recall-file-input"
            @change="onInputChange"
          >
        </div>

        <!-- Preview（有选中时） -->
        <div v-else class="space-y-2" data-testid="recall-preview">
          <img
            :src="previewUrl"
            :alt="t('screenshotRecall.upload.previewAlt')"
            class="max-h-48 w-auto object-contain rounded-md border border-border/50"
          >
          <div class="flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
            <span class="font-medium text-foreground break-all">{{ file.name }}</span>
            <span>{{ formatSize(file.size) }}</span>
            <Button
              variant="ghost"
              size="sm"
              type="button"
              data-testid="recall-remove"
              @click="removeFile"
            >
              <span class="icon-[lucide--x] mr-1" aria-hidden="true" />
              {{ t('screenshotRecall.upload.remove') }}
            </Button>
          </div>
        </div>

        <!-- 校验错误（内联红字，进 live region 由结果区承载，此处 role=alert 即时播报） -->
        <p
          v-if="validationError"
          class="text-xs text-destructive"
          role="alert"
          data-testid="recall-validation"
        >
          {{ validationError }}
        </p>

        <Button
          type="button"
          class="w-full sm:w-auto"
          data-testid="recall-submit"
          :disabled="!file || isPending"
          @click="onSubmit"
        >
          <span v-if="isPending" class="icon-[lucide--loader-circle] animate-spin mr-1.5" aria-hidden="true" />
          {{ isPending ? t('screenshotRecall.upload.submitting') : t('screenshotRecall.upload.submit') }}
        </Button>
      </div>
    </div>

    <!-- ==================== 结果区（6 态状态机） ==================== -->
    <div aria-live="polite" :aria-busy="isPending" class="space-y-6">
      <!-- error：红字，保留上次结果不清空，可重试 -->
      <p
        v-if="isError"
        class="text-sm text-destructive"
        data-testid="recall-error"
      >
        {{ t('screenshotRecall.error') }}
      </p>

      <!-- loading：Skeleton + spinner 文案 -->
      <div v-if="isPending" class="card p-5 space-y-3" data-testid="recall-loading">
        <div class="flex items-center gap-2 text-sm text-muted-foreground">
          <span class="icon-[lucide--loader-circle] animate-spin text-primary" aria-hidden="true" />
          <span>{{ t('screenshotRecall.loading') }}</span>
        </div>
        <Skeleton class="h-4 w-3/4" />
        <Skeleton class="h-4 w-1/2" />
        <Skeleton class="h-4 w-2/3" />
      </div>

      <!-- 有结果（非 pending） -->
      <template v-else-if="result">
        <!-- degraded：amber 卡片 + 前往系统设置（区别于错误，不弹 error toast） -->
        <div
          v-if="result.degraded"
          class="card p-5 space-y-2 border-amber-300/60 dark:border-amber-400/30"
          data-testid="recall-degraded"
        >
          <div class="flex items-center gap-2 text-sm font-medium text-amber-700 dark:text-amber-400">
            <span class="icon-[lucide--alert-triangle]" aria-hidden="true" />
            <span>{{ degradedTitle }}</span>
          </div>
          <p class="text-sm text-muted-foreground">
            {{ degradedBody }}
          </p>
          <a
            v-if="showSettingsLink"
            href="/admin"
            class="inline-flex items-center gap-1 text-sm text-primary hover:underline"
            data-testid="recall-degraded-link"
          >
            <span class="icon-[lucide--settings]" aria-hidden="true" />
            {{ t('screenshotRecall.degraded.settingsLink') }}
          </a>
        </div>

        <!-- success / no-results -->
        <template v-else>
          <!-- 可选语义卡（默认折叠，三段任一为空不渲染该段） -->
          <div v-if="hasSemantics" class="card" data-testid="recall-semantics">
            <button
              type="button"
              class="w-full flex items-center gap-2 px-5 py-3.5 text-left"
              :class="{ 'border-b border-border/50': semanticsExpanded }"
              :aria-expanded="semanticsExpanded"
              data-testid="recall-semantics-toggle"
              @click="semanticsExpanded = !semanticsExpanded"
            >
              <span class="icon-[lucide--scan-text] text-primary" aria-hidden="true" />
              <h3 class="text-sm font-semibold flex-1">
                {{ t('screenshotRecall.semantics.title') }}
              </h3>
              <span class="text-xs text-muted-foreground">
                {{ semanticsExpanded ? t('screenshotRecall.semantics.collapse') : t('screenshotRecall.semantics.expand') }}
              </span>
              <span
                class="icon-[lucide--chevron-down] transition-transform"
                :class="{ 'rotate-180': semanticsExpanded }"
                aria-hidden="true"
              />
            </button>
            <div v-if="semanticsExpanded" class="p-5 space-y-3">
              <div v-if="result.semantics?.text" class="space-y-0.5">
                <p class="text-xs text-muted-foreground">
                  {{ t('screenshotRecall.semantics.text') }}
                </p>
                <p class="text-sm whitespace-pre-wrap break-words">
                  {{ result.semantics.text }}
                </p>
              </div>
              <div v-if="result.semantics?.ui_elements" class="space-y-0.5">
                <p class="text-xs text-muted-foreground">
                  {{ t('screenshotRecall.semantics.uiElements') }}
                </p>
                <p class="text-sm whitespace-pre-wrap break-words">
                  {{ result.semantics.ui_elements }}
                </p>
              </div>
              <div v-if="result.semantics?.business_intent" class="space-y-0.5">
                <p class="text-xs text-muted-foreground">
                  {{ t('screenshotRecall.semantics.businessIntent') }}
                </p>
                <p class="text-sm whitespace-pre-wrap break-words">
                  {{ result.semantics.business_intent }}
                </p>
              </div>
            </div>
          </div>

          <!-- 召回列表 或 no-results 空态 -->
          <div v-if="result.results.length" class="space-y-3" data-testid="recall-list">
            <h2 class="text-sm font-semibold">
              {{ t('screenshotRecall.results.title') }}
            </h2>
            <ul class="space-y-3">
              <li
                v-for="(item, idx) in result.results"
                :key="`${item.work_item_id}-${idx}`"
                class="flex items-start gap-2 flex-wrap"
                :data-testid="`recall-item-${idx}`"
              >
                <span class="icon-[lucide--file-text] text-muted-foreground mt-0.5 shrink-0" aria-hidden="true" />
                <div class="min-w-0 space-y-0.5">
                  <p class="text-sm font-medium">
                    {{ item.title }}
                  </p>
                  <div class="flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
                    <code class="font-mono break-all">{{ item.work_item_id }}</code>
                    <span
                      v-if="item.relevance != null"
                      class="text-emerald-600 dark:text-emerald-400"
                    >
                      {{ t('screenshotRecall.results.relevance', { percent: relevancePercent(item.relevance) }) }}
                    </span>
                  </div>
                  <a
                    v-if="item.link"
                    :href="item.link"
                    target="_blank"
                    rel="noopener"
                    class="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                  >
                    <span class="icon-[lucide--external-link]" aria-hidden="true" />
                    {{ t('screenshotRecall.results.viewLink') }}
                  </a>
                </div>
              </li>
            </ul>
          </div>
          <CompactEmptyState
            v-else
            icon="lucide--search-x"
            :title="t('screenshotRecall.noResults.title')"
            :description="t('screenshotRecall.noResults.body')"
            data-testid="recall-no-results"
          />
        </template>
      </template>

      <!-- empty：初始 / 移除文件后（error 态时不渲染，避免与错误文案双显，UX-1） -->
      <CompactEmptyState
        v-else-if="!isError"
        icon="lucide--image"
        :title="t('screenshotRecall.empty.title')"
        :description="t('screenshotRecall.empty.body')"
        data-testid="recall-empty"
      />
    </div>
  </div>
</template>
