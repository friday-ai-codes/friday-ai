<script setup lang="ts">
import { Clock, Settings2 } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'

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
import ConditionBuilder from './ConditionBuilder.vue'

interface Props {
  config: Record<string, unknown>
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:config', config: Record<string, unknown>): void
}>()

// Local state
const workItemId = ref((props.config?.work_item_id as string) || '{{trigger.work_item_id}}')
const workItemType = ref((props.config?.work_item_type as string) || 'story')
const projectKey = ref((props.config?.project_key as string) || '{{trigger.project_key}}')
const condition = ref((props.config?.condition as { logic: 'and' | 'or', conditions: Array<{ field: string, operator: string, value: string }> }) || { logic: 'and' as const, conditions: [] })
const timeoutSeconds = ref((props.config?.timeout_seconds as number) || 0)
const timeoutAction = ref((props.config?.timeout_action as string) || 'fail')

// Watch for external config changes
watch(() => props.config, (newConfig) => {
  if (newConfig) {
    workItemId.value = (newConfig.work_item_id as string) || '{{trigger.work_item_id}}'
    workItemType.value = (newConfig.work_item_type as string) || 'story'
    projectKey.value = (newConfig.project_key as string) || '{{trigger.project_key}}'
    condition.value = (newConfig.condition as typeof condition.value) || { logic: 'and', conditions: [] }
    timeoutSeconds.value = (newConfig.timeout_seconds as number) || 0
    timeoutAction.value = (newConfig.timeout_action as string) || 'fail'
  }
}, { deep: true })

// Emit changes
function updateConfig() {
  emit('update:config', {
    work_item_id: workItemId.value,
    work_item_type: workItemType.value,
    project_key: projectKey.value,
    condition: condition.value,
    timeout_seconds: timeoutSeconds.value,
    timeout_action: timeoutAction.value,
  })
}

// Watch all fields and emit
watch([workItemId, workItemType, projectKey, condition, timeoutSeconds, timeoutAction], updateConfig, { deep: true })

// Timeout display options
const timeoutOptions = [
  { value: -1, label: '不超时' },
  { value: 0, label: '默认 (7 天)' },
  { value: 3600, label: '1 小时' },
  { value: 86400, label: '1 天' },
  { value: 259200, label: '3 天' },
  { value: 604800, label: '7 天' },
]

const timeoutActionOptions = [
  { value: 'fail', label: '失败终止' },
  { value: 'skip', label: '跳过继续' },
  { value: 'retry', label: '重试' },
]

// Computed for timeout select
const selectedTimeout = computed({
  get: () => {
    const found = timeoutOptions.find(o => o.value === timeoutSeconds.value)
    return found ? timeoutSeconds.value : 'custom'
  },
  set: (val) => {
    if (val !== 'custom') {
      timeoutSeconds.value = Number(val)
    }
  },
})

const isCustomTimeout = computed(() => {
  return !timeoutOptions.some(o => o.value === timeoutSeconds.value)
})
</script>

<template>
  <div class="space-y-5">
    <!-- Section: 工作项配置 -->
    <div class="space-y-4">
      <h4 class="text-sm font-medium text-muted-foreground flex items-center gap-2">
        <Settings2 class="w-4 h-4" />
        工作项配置
      </h4>

      <div class="space-y-3">
        <div class="space-y-1.5">
          <Label class="text-sm">工作项 ID</Label>
          <Input
            v-model="workItemId"
            placeholder="{{trigger.work_item_id}}"
            class="bg-background/50"
          />
          <p v-pre class="text-xs text-muted-foreground">
            支持变量引用，如 {{trigger.work_item_id}}
          </p>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div class="space-y-1.5">
            <Label class="text-sm">项目标识</Label>
            <Input
              v-model="projectKey"
              placeholder="{{trigger.project_key}}"
              class="bg-background/50"
            />
          </div>
          <div class="space-y-1.5">
            <Label class="text-sm">工作项类型</Label>
            <Select v-model="workItemType">
              <SelectTrigger class="w-full bg-background/50">
                <SelectValue placeholder="选择类型" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="story">
                  需求 (story)
                </SelectItem>
                <SelectItem value="task">
                  任务 (task)
                </SelectItem>
                <SelectItem value="bug">
                  缺陷 (bug)
                </SelectItem>
                <SelectItem value="epic">
                  史诗 (epic)
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
    </div>

    <Separator class="bg-border/50" />

    <!-- Section: 等待条件 -->
    <div class="space-y-4">
      <h4 class="text-sm font-medium text-muted-foreground flex items-center gap-2">
        <Clock class="w-4 h-4" />
        等待条件
      </h4>

      <ConditionBuilder v-model="condition" />
    </div>

    <Separator class="bg-border/50" />

    <!-- Section: 超时配置 -->
    <div class="space-y-4">
      <h4 class="text-sm font-medium text-muted-foreground">
        超时配置
      </h4>

      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1.5">
          <Label class="text-sm">超时时间</Label>
          <Select v-model="selectedTimeout">
            <SelectTrigger class="w-full bg-background/50">
              <SelectValue placeholder="选择超时时间" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="opt in timeoutOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </SelectItem>
              <SelectItem v-if="isCustomTimeout" value="custom">
                自定义 ({{ timeoutSeconds }}秒)
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div class="space-y-1.5">
          <Label class="text-sm">超时动作</Label>
          <Select v-model="timeoutAction">
            <SelectTrigger class="w-full bg-background/50">
              <SelectValue placeholder="选择动作" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="opt in timeoutActionOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <p class="text-xs text-muted-foreground">
        超时后将根据配置的动作处理：失败终止、跳过继续或重试等待
      </p>
    </div>
  </div>
</template>
