<script setup lang="ts">
import { AlertTriangle, ChevronDown, RotateCcw, SkipForward } from 'lucide-vue-next'
import { ref, watch } from 'vue'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { Textarea } from '~/components/ui/textarea'

type OnErrorStrategy = 'abort' | 'retry' | 'ignore'

const props = defineProps<{
  onError: OnErrorStrategy
  retryTimes: number
  retryDelay: number
  nodeTimeoutSeconds: number | null
  fallbackValues: Record<string, unknown> | null
}>()

const emit = defineEmits<{
  'update:onError': [value: OnErrorStrategy]
  'update:retryTimes': [value: number]
  'update:retryDelay': [value: number]
  'update:nodeTimeoutSeconds': [value: number | null]
  'update:fallbackValues': [value: Record<string, unknown> | null]
}>()

const isOpen = ref(false)

// Fallback JSON editor
const fallbackJson = ref(JSON.stringify(props.fallbackValues ?? {}, null, 2))
const fallbackError = ref('')

watch(() => props.fallbackValues, (val) => {
  fallbackJson.value = JSON.stringify(val ?? {}, null, 2)
})

function onFallbackChange(value: string | number) {
  const text = String(value)
  fallbackJson.value = text
  try {
    const parsed = JSON.parse(text)
    fallbackError.value = ''
    emit('update:fallbackValues', parsed)
  }
  catch {
    fallbackError.value = 'JSON 格式无效'
  }
}

function onRetryTimesChange(e: Event) {
  const val = Number.parseInt((e.target as HTMLInputElement).value, 10)
  if (!Number.isNaN(val) && val >= 0) {
    emit('update:retryTimes', val)
  }
}

function onRetryDelayChange(e: Event) {
  const val = Number.parseInt((e.target as HTMLInputElement).value, 10)
  if (!Number.isNaN(val) && val >= 1) {
    emit('update:retryDelay', val)
  }
}

function onTimeoutChange(e: Event) {
  const raw = (e.target as HTMLInputElement).value
  if (raw === '' || raw === null) {
    emit('update:nodeTimeoutSeconds', null)
    return
  }
  const val = Number.parseInt(raw, 10)
  if (!Number.isNaN(val) && val > 0) {
    emit('update:nodeTimeoutSeconds', val)
  }
}

function handleOnErrorChange(v: unknown) {
  if (v === 'abort' || v === 'retry' || v === 'ignore') {
    emit('update:onError', v)
  }
}

const strategyOptions: Array<{ value: OnErrorStrategy, label: string, description: string, icon: typeof AlertTriangle }> = [
  { value: 'abort', label: '中止执行', description: '节点失败后终止整个工作流', icon: AlertTriangle },
  { value: 'retry', label: '自动重试', description: '失败后按配置次数重试（指数退避）', icon: RotateCcw },
  { value: 'ignore', label: '忽略继续', description: '失败后使用默认值继续下游执行', icon: SkipForward },
]
</script>

<template>
  <Collapsible v-model:open="isOpen">
    <CollapsibleTrigger class="flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm font-medium transition-colors hover:bg-accent/50">
      <div class="flex items-center gap-2">
        <AlertTriangle class="h-4 w-4 text-muted-foreground" />
        <span>错误处理</span>
      </div>
      <ChevronDown
        class="h-4 w-4 text-muted-foreground transition-transform duration-200"
        :class="{ 'rotate-180': isOpen }"
      />
    </CollapsibleTrigger>

    <CollapsibleContent class="space-y-4 px-3 pt-3 pb-1">
      <!-- on_error strategy selector -->
      <div class="space-y-1.5">
        <Label class="text-xs text-muted-foreground">错误策略</Label>
        <Select :model-value="onError" @update:model-value="handleOnErrorChange">
          <SelectTrigger class="h-9">
            <SelectValue placeholder="选择错误处理策略" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem
              v-for="opt in strategyOptions"
              :key="opt.value"
              :value="opt.value"
            >
              <div class="flex items-center gap-2">
                <component :is="opt.icon" class="h-3.5 w-3.5" />
                <span>{{ opt.label }}</span>
              </div>
            </SelectItem>
          </SelectContent>
        </Select>
        <p class="text-xs text-muted-foreground">
          {{ strategyOptions.find(o => o.value === onError)?.description }}
        </p>
      </div>

      <!-- retry_times (only when on_error=retry) -->
      <div v-if="onError === 'retry'" class="space-y-1.5">
        <Label class="text-xs text-muted-foreground">重试次数</Label>
        <Input
          type="number"
          :model-value="retryTimes"
          min="0"
          max="10"
          placeholder="0"
          class="h-9"
          @input="onRetryTimesChange"
        />
        <p class="text-xs text-muted-foreground">
          失败后最多重试的次数（0 = 不重试）
        </p>
      </div>

      <!-- retry_delay (only when on_error=retry) -->
      <div v-if="onError === 'retry'" class="space-y-1.5">
        <Label class="text-xs text-muted-foreground">重试间隔（秒）</Label>
        <Input
          type="number"
          :model-value="retryDelay"
          min="1"
          max="300"
          placeholder="5"
          class="h-9"
          @input="onRetryDelayChange"
        />
        <p class="text-xs text-muted-foreground">
          基础间隔，实际按指数退避计算（最大 300 秒）
        </p>
      </div>

      <!-- node_timeout_seconds (always visible) -->
      <div class="space-y-1.5">
        <Label class="text-xs text-muted-foreground">节点超时（秒）</Label>
        <Input
          type="number"
          :model-value="nodeTimeoutSeconds ?? ''"
          min="1"
          placeholder="不限制"
          class="h-9"
          @input="onTimeoutChange"
        />
        <p class="text-xs text-muted-foreground">
          超时后自动触发上方配置的错误策略
        </p>
      </div>

      <!-- fallback_values (only when on_error=ignore) -->
      <div v-if="onError === 'ignore'" class="space-y-1.5">
        <Label class="text-xs text-muted-foreground">容错默认值 (JSON)</Label>
        <Textarea
          :model-value="fallbackJson"
          rows="4"
          class="font-mono"
          placeholder="{&quot;result&quot;: &quot;default_value&quot;}"
          @update:model-value="onFallbackChange"
        />
        <p v-if="fallbackError" class="text-xs text-destructive">
          {{ fallbackError }}
        </p>
        <p v-else class="text-xs text-muted-foreground">
          节点失败后传递给下游节点的默认输出（留空则传递 {status: "skipped"}）
        </p>
      </div>
    </CollapsibleContent>
  </Collapsible>
</template>
