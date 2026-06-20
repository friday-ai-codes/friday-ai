<script setup lang="ts">
import type { FeishuEventTriggerConfig } from '~/types/workflow'
import { storeToRefs } from 'pinia'
import { computed, onMounted, ref } from 'vue'

import { Badge } from '~/components/ui/badge'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '~/components/ui/popover'
import { RadioGroup, RadioGroupItem } from '~/components/ui/radio-group'
import { Separator } from '~/components/ui/separator'
import { useConfigModel } from '~/composables/useConfigModel'
import { useSpacesStore } from '~/stores/spaces'
import {
  FEISHU_EVENT_TYPE_OPTIONS,
  feishuEventTriggerConfigSchema,
} from '~/types/workflow'

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:config', value: FeishuEventTriggerConfig): void
}>()

// ============================================================================
// 需求状态选项（飞书需求工作项的状态流）
// ============================================================================

const STORY_STATUS_OPTIONS = [
  { value: 'pending_plan', label: '待计划', category: 'todo' },
  { value: 'sprint_plan', label: 'Sprint 计划', category: 'todo' },
  { value: 'in_development', label: '开发中', category: 'doing' },
  { value: 'code_review', label: '代码审查', category: 'doing' },
  { value: 'testing', label: '测试中', category: 'doing' },
  { value: 'pending_release', label: '待发布', category: 'doing' },
  { value: 'released', label: '已发布', category: 'done' },
  { value: 'closed', label: '已关闭', category: 'done' },
] as const

// ============================================================================
// Props & Emits
// ============================================================================

interface Props {
  config: FeishuEventTriggerConfig
}

// ============================================================================
// Projects Store
// ============================================================================

const spacesStore = useSpacesStore()
const { spaces, loading: spacesLoading } = storeToRefs(spacesStore)

onMounted(async () => {
  if (spaces.value.length === 0) {
    await spacesStore.fetchSpaces()
  }
})

// 过滤有飞书配置的空间
const feishuProjects = computed(() => {
  return spaces.value.filter(p => p.feishu_project_key || p.has_feishu_config)
})

// ============================================================================
// Config Model
// ============================================================================

const { field, arrayField, updateFields } = useConfigModel({
  config: () => props.config,
  emit: v => emit('update:config', v),
  schema: feishuEventTriggerConfigSchema,
})

// 事件类型 - 单选
const eventType = field('event_type', '')

// 工作项类型 - 必选（目前只支持需求）
const workItemType = field('filter_work_item_type', 'story')

// 空间来源 - 多选
const projectIds = arrayField('project_ids', [])

// 过滤条件
const filterStatus = arrayField('filter_status', [])

// 状态输入
const statusInput = ref('')
const statusPopoverOpen = ref(false)

// 添加自定义状态
function addCustomStatus() {
  const value = statusInput.value.trim()
  if (value && !filterStatus.includes(value)) {
    filterStatus.toggle(value, true)
    statusInput.value = ''
  }
}

// 处理状态输入键盘事件
function handleStatusKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    e.preventDefault()
    addCustomStatus()
  }
}

// 移除状态
function removeStatus(value: string) {
  filterStatus.toggle(value, false)
}

// 获取状态标签显示名称
function getStatusLabel(value: string): string {
  const preset = STORY_STATUS_OPTIONS.find(s => s.value === value)
  return preset?.label || value
}

// 排除规则
const excludeProjectIds = arrayField('exclude_project_ids', [])

// 排除工作项：统一输入框写入两个互斥后端字段。
// 以 /pattern/flags 形式输入视为正则 → exclude_work_item_regex（去掉首尾斜杠存裸正则）；
// 否则视为子串包含 → exclude_work_item_pattern。读取时正则字段优先并补回斜杠便于展示。
const excludeWorkItemPatternRaw = field('exclude_work_item_pattern', '')
const excludeWorkItemRegexRaw = field('exclude_work_item_regex', '')
const excludeWorkItemPattern = computed<string>({
  get() {
    if (excludeWorkItemRegexRaw.value)
      return `/${excludeWorkItemRegexRaw.value}/`
    return excludeWorkItemPatternRaw.value
  },
  set(v: string) {
    const match = v.match(/^\/(.+)\/([gimsuvy]*)$/)
    if (v.startsWith('/') && match) {
      // 单次 emit 同时更新两字段，避免连续 set 读到过期 config 互相覆盖
      updateFields({ exclude_work_item_regex: match[1], exclude_work_item_pattern: '' })
    }
    else {
      updateFields({ exclude_work_item_pattern: v, exclude_work_item_regex: '' })
    }
  },
})

// ============================================================================
// 空间选择器
// ============================================================================

const projectSearchQuery = ref('')
const projectPopoverOpen = ref(false)
const excludeProjectSearchQuery = ref('')
const excludeProjectPopoverOpen = ref(false)

// 过滤后的空间列表
const filteredProjects = computed(() => {
  const query = projectSearchQuery.value.toLowerCase().trim()
  if (!query)
    return feishuProjects.value
  return feishuProjects.value.filter(p =>
    p.name.toLowerCase().includes(query)
    || p.feishu_project_key?.toLowerCase().includes(query),
  )
})

const filteredExcludeProjects = computed(() => {
  const query = excludeProjectSearchQuery.value.toLowerCase().trim()
  if (!query)
    return feishuProjects.value
  return feishuProjects.value.filter(p =>
    p.name.toLowerCase().includes(query)
    || p.feishu_project_key?.toLowerCase().includes(query),
  )
})

// 获取选中空间的信息
const selectedProjects = computed(() => {
  const ids = projectIds.value.value as string[] || []
  return ids
    .map(id => feishuProjects.value.find(p => p.id === id))
    .filter(Boolean) as typeof feishuProjects.value
})

const excludedProjects = computed(() => {
  const ids = excludeProjectIds.value.value as string[] || []
  return ids
    .map(id => feishuProjects.value.find(p => p.id === id))
    .filter(Boolean) as typeof feishuProjects.value
})

function toggleProject(projectId: string) {
  const isSelected = projectIds.includes(projectId)
  projectIds.toggle(projectId, !isSelected)
}

function removeProject(projectId: string) {
  projectIds.toggle(projectId, false)
}

function toggleExcludeProject(projectId: string) {
  const isSelected = excludeProjectIds.includes(projectId)
  excludeProjectIds.toggle(projectId, !isSelected)
}

function removeExcludeProject(projectId: string) {
  excludeProjectIds.toggle(projectId, false)
}

// ============================================================================
// 排除规则 - 名称/正则统一输入
// ============================================================================

// 检测是否为正则模式（以 / 开头）
const isRegexMode = computed(() => {
  return excludeWorkItemPattern.value.startsWith('/')
})

// 正则有效性检测
const regexValidation = computed(() => {
  const pattern = excludeWorkItemPattern.value
  if (!pattern.startsWith('/')) {
    return { valid: true, error: null }
  }

  // 尝试解析正则: /pattern/flags 格式
  const match = pattern.match(/^\/(.+)\/([gimsuvy]*)$/)
  if (!match) {
    // 可能正在输入中，还没闭合
    if (pattern.length > 1 && !pattern.endsWith('/')) {
      return { valid: null, error: '正则未闭合，需以 / 结尾' }
    }
    return { valid: null, error: null }
  }

  try {
    // eslint-disable-next-line no-new
    new RegExp(match[1], match[2])
    return { valid: true, error: null }
  }
  catch (e) {
    return { valid: false, error: (e as Error).message }
  }
})
</script>

<template>
  <div class="space-y-5">
    <!-- 事件类型 - 单选 -->
    <div class="space-y-3">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--zap] text-primary" />
        <Label class="text-sm font-medium">事件类型</Label>
        <span class="text-destructive">*</span>
      </div>

      <RadioGroup
        v-model="eventType"
        class="gap-1 p-3 rounded-xl border border-border/50 bg-background/30"
      >
        <Label
          v-for="option in FEISHU_EVENT_TYPE_OPTIONS"
          :key="option.value"
          :for="`event-${option.value}`"
          class="flex items-start gap-3 p-2 rounded-lg border transition-colors cursor-pointer font-normal"
          :class="eventType === option.value ? 'bg-primary/5 border-primary/20' : 'border-transparent hover:bg-muted/50'"
        >
          <RadioGroupItem :id="`event-${option.value}`" :value="option.value" class="mt-1" />
          <div class="flex-1">
            <div class="text-sm font-medium">{{ option.label }}</div>
            <div class="text-xs text-muted-foreground">{{ option.description }}</div>
          </div>
        </Label>
      </RadioGroup>
    </div>

    <Separator class="bg-border/50" />

    <!-- 工作项类型 - 必选 -->
    <div class="space-y-3">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--file-text] text-primary" />
        <Label class="text-sm font-medium">工作项类型</Label>
        <span class="text-destructive">*</span>
      </div>

      <RadioGroup
        v-model="workItemType"
        class="gap-1 p-3 rounded-xl border border-border/50 bg-background/30"
      >
        <Label
          for="work-item-story"
          class="flex items-center gap-3 p-2 rounded-lg border transition-colors cursor-pointer font-normal"
          :class="workItemType === 'story' ? 'bg-primary/5 border-primary/20' : 'border-transparent hover:bg-muted/50'"
        >
          <RadioGroupItem id="work-item-story" value="story" />
          <div class="flex-1">
            <div class="text-sm font-medium">需求 (Story)</div>
            <div class="text-xs text-muted-foreground">监听需求类型的工作项事件</div>
          </div>
        </Label>

        <!-- 其他类型 - 即将支持 -->
        <div class="flex items-center gap-3 p-2 rounded-lg opacity-50 cursor-not-allowed">
          <RadioGroupItem value="bug" disabled />
          <div class="flex-1">
            <div class="text-sm font-medium flex items-center gap-2">
              缺陷 (Bug)
              <Badge variant="outline" class="text-xs">
                即将支持
              </Badge>
            </div>
          </div>
        </div>

        <div class="flex items-center gap-3 p-2 rounded-lg opacity-50 cursor-not-allowed">
          <RadioGroupItem value="task" disabled />
          <div class="flex-1">
            <div class="text-sm font-medium flex items-center gap-2">
              任务 (Task)
              <Badge variant="outline" class="text-xs">
                即将支持
              </Badge>
            </div>
          </div>
        </div>
      </RadioGroup>
    </div>

    <Separator class="bg-border/50" />

    <!-- 状态过滤 - 标签化 -->
    <div class="space-y-3">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--git-branch] text-primary" />
        <Label class="text-sm font-medium">状态过滤</Label>
        <Badge variant="outline" class="text-xs">
          可选
        </Badge>
      </div>

      <p class="text-xs text-muted-foreground">
        选择或输入要监听的需求状态，留空则监听所有状态变更
      </p>

      <!-- 已选状态标签 -->
      <div v-if="(filterStatus.value.value as string[])?.length > 0" class="flex flex-wrap gap-1.5">
        <Badge
          v-for="status in (filterStatus.value.value as string[])"
          :key="status"
          variant="secondary"
          class="text-xs gap-1 pr-1"
        >
          {{ getStatusLabel(status) }}
          <button
            type="button"
            class="hover:bg-muted rounded-full p-0.5"
            @click="removeStatus(status)"
          >
            <span class="icon-[lucide--x] text-xs" />
          </button>
        </Badge>
      </div>

      <!-- 状态选择器 -->
      <Popover v-model:open="statusPopoverOpen">
        <PopoverTrigger as-child>
          <div class="relative">
            <Input
              v-model="statusInput"
              placeholder="选择或输入状态，回车添加..."
              class="bg-background/50 text-sm pr-8"
              @keydown="handleStatusKeydown"
            />
            <span class="icon-[lucide--chevron-down] absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          </div>
        </PopoverTrigger>
        <PopoverContent class="w-72 p-2" align="start">
          <div class="space-y-2">
            <div class="text-xs text-muted-foreground px-2">
              预设状态
            </div>
            <div class="max-h-48 overflow-y-auto space-y-0.5">
              <button
                v-for="status in STORY_STATUS_OPTIONS"
                :key="status.value"
                type="button"
                class="w-full flex items-center gap-2 p-2 rounded-lg text-left text-sm hover:bg-muted/50 transition-colors"
                :class="{ 'bg-primary/10': filterStatus.includes(status.value) }"
                @click="filterStatus.toggle(status.value, !filterStatus.includes(status.value))"
              >
                <span
                  class="w-4 h-4 rounded border flex items-center justify-center transition-colors"
                  :class="filterStatus.includes(status.value) ? 'bg-primary border-primary text-primary-foreground' : 'border-border'"
                >
                  <span v-if="filterStatus.includes(status.value)" class="icon-[lucide--check] text-xs" />
                </span>
                <span class="flex-1">{{ status.label }}</span>
                <span class="text-xs text-muted-foreground">{{ status.value }}</span>
              </button>
            </div>
            <div v-if="statusInput.trim()" class="border-t border-border/50 pt-2">
              <button
                type="button"
                class="w-full flex items-center gap-2 p-2 rounded-lg text-left text-sm hover:bg-muted/50 transition-colors"
                @click="addCustomStatus"
              >
                <span class="icon-[lucide--plus] text-primary" />
                <span>添加自定义状态: <strong>{{ statusInput.trim() }}</strong></span>
              </button>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>

    <Separator class="bg-border/50" />

    <!-- 空间监听与排除 -->
    <div class="space-y-4">
      <!-- 监听空间 -->
      <div class="space-y-2">
        <div class="flex items-center gap-2">
          <span class="icon-[lucide--folder] text-primary" />
          <Label class="text-sm font-medium">监听空间</Label>
          <Badge variant="outline" class="text-xs">
            可选
          </Badge>
        </div>

        <p class="text-xs text-muted-foreground">
          留空则监听所有已配置飞书的空间
        </p>

        <Popover v-model:open="projectPopoverOpen">
          <PopoverTrigger as-child>
            <button
              type="button"
              class="w-full min-h-[38px] px-3 py-2 rounded-xl border border-border/50 bg-background/50 text-left text-sm flex items-center gap-2 flex-wrap hover:border-primary/50 transition-colors"
            >
              <template v-if="selectedProjects.length === 0">
                <span class="text-muted-foreground">点击选择空间...</span>
              </template>
              <template v-else>
                <!-- 显示前2个标签 -->
                <Badge
                  v-for="project in selectedProjects.slice(0, 2)"
                  :key="project.id"
                  variant="secondary"
                  class="text-xs gap-1 pr-1"
                >
                  {{ project.name }}
                  <button
                    type="button"
                    class="hover:bg-muted rounded-full p-0.5"
                    @click.stop="removeProject(project.id)"
                  >
                    <span class="icon-[lucide--x] text-xs" />
                  </button>
                </Badge>
                <!-- 超过2个显示 +N -->
                <Badge v-if="selectedProjects.length > 2" variant="outline" class="text-xs">
                  +{{ selectedProjects.length - 2 }}
                </Badge>
              </template>
              <span class="icon-[lucide--chevron-down] ml-auto text-muted-foreground" />
            </button>
          </PopoverTrigger>
          <PopoverContent class="w-72 p-2" align="start">
            <div class="space-y-2">
              <Input
                v-model="projectSearchQuery"
                placeholder="搜索空间名称或 Key..."
                class="h-8 text-sm"
              />
              <div class="max-h-48 overflow-y-auto space-y-0.5">
                <template v-if="spacesLoading">
                  <div class="p-3 text-sm text-muted-foreground text-center">
                    加载中...
                  </div>
                </template>
                <template v-else-if="filteredProjects.length === 0">
                  <div class="p-3 text-sm text-muted-foreground text-center">
                    {{ projectSearchQuery ? '未找到匹配空间' : '暂无配置飞书的空间' }}
                  </div>
                </template>
                <template v-else>
                  <button
                    v-for="project in filteredProjects"
                    :key="project.id"
                    type="button"
                    class="w-full flex items-center gap-2 p-2 rounded-lg text-left text-sm hover:bg-muted/50 transition-colors"
                    :class="{ 'bg-primary/10': projectIds.includes(project.id) }"
                    @click="toggleProject(project.id)"
                  >
                    <span
                      class="w-4 h-4 rounded border flex items-center justify-center transition-colors"
                      :class="projectIds.includes(project.id) ? 'bg-primary border-primary text-primary-foreground' : 'border-border'"
                    >
                      <span v-if="projectIds.includes(project.id)" class="icon-[lucide--check] text-xs" />
                    </span>
                    <span class="flex-1 truncate">{{ project.name }}</span>
                    <span v-if="project.feishu_project_key" class="text-xs text-muted-foreground">
                      {{ project.feishu_project_key }}
                    </span>
                  </button>
                </template>
              </div>
            </div>
          </PopoverContent>
        </Popover>
      </div>

      <!-- 排除空间 -->
      <div class="space-y-2">
        <div class="flex items-center gap-2">
          <span class="icon-[lucide--folder-minus] text-red-500" />
          <Label class="text-sm font-medium">排除空间</Label>
          <Badge variant="outline" class="text-xs">
            可选
          </Badge>
        </div>

        <Popover v-model:open="excludeProjectPopoverOpen">
          <PopoverTrigger as-child>
            <button
              type="button"
              class="w-full min-h-[38px] px-3 py-2 rounded-xl border border-border/50 bg-background/50 text-left text-sm flex items-center gap-2 flex-wrap hover:border-red-500/50 transition-colors"
            >
              <template v-if="excludedProjects.length === 0">
                <span class="text-muted-foreground">点击选择要排除的空间...</span>
              </template>
              <template v-else>
                <Badge
                  v-for="project in excludedProjects.slice(0, 2)"
                  :key="project.id"
                  variant="destructive"
                  class="text-xs gap-1 pr-1"
                >
                  {{ project.name }}
                  <button
                    type="button"
                    class="hover:bg-red-600 rounded-full p-0.5"
                    @click.stop="removeExcludeProject(project.id)"
                  >
                    <span class="icon-[lucide--x] text-xs" />
                  </button>
                </Badge>
                <Badge v-if="excludedProjects.length > 2" variant="destructive" class="text-xs">
                  +{{ excludedProjects.length - 2 }}
                </Badge>
              </template>
              <span class="icon-[lucide--chevron-down] ml-auto text-muted-foreground" />
            </button>
          </PopoverTrigger>
          <PopoverContent class="w-72 p-2" align="start">
            <div class="space-y-2">
              <Input
                v-model="excludeProjectSearchQuery"
                placeholder="搜索空间名称或 Key..."
                class="h-8 text-sm"
              />
              <div class="max-h-48 overflow-y-auto space-y-0.5">
                <template v-if="filteredExcludeProjects.length === 0">
                  <div class="p-3 text-sm text-muted-foreground text-center">
                    {{ excludeProjectSearchQuery ? '未找到匹配空间' : '暂无可排除的空间' }}
                  </div>
                </template>
                <template v-else>
                  <button
                    v-for="project in filteredExcludeProjects"
                    :key="project.id"
                    type="button"
                    class="w-full flex items-center gap-2 p-2 rounded-lg text-left text-sm hover:bg-muted/50 transition-colors"
                    :class="{ 'bg-red-500/10': excludeProjectIds.includes(project.id) }"
                    @click="toggleExcludeProject(project.id)"
                  >
                    <span
                      class="w-4 h-4 rounded border flex items-center justify-center transition-colors"
                      :class="excludeProjectIds.includes(project.id) ? 'bg-red-500 border-red-500 text-white' : 'border-border'"
                    >
                      <span v-if="excludeProjectIds.includes(project.id)" class="icon-[lucide--check] text-xs" />
                    </span>
                    <span class="flex-1 truncate">{{ project.name }}</span>
                    <span v-if="project.feishu_project_key" class="text-xs text-muted-foreground">
                      {{ project.feishu_project_key }}
                    </span>
                  </button>
                </template>
              </div>
            </div>
          </PopoverContent>
        </Popover>
      </div>

      <!-- 排除工作项 - 统一输入框 -->
      <div class="space-y-2">
        <div class="flex items-center gap-2">
          <span class="icon-[lucide--file-minus] text-red-500" />
          <Label class="text-sm font-medium">排除工作项</Label>
          <Badge variant="outline" class="text-xs">
            可选
          </Badge>
        </div>

        <div class="relative">
          <Input
            v-model="excludeWorkItemPattern"
            :placeholder="isRegexMode ? '如: /^\\[测试\\].*/' : '如: [测试]、临时'"
            class="bg-background/50 text-sm pr-16"
            :class="{ 'font-mono': isRegexMode, 'border-red-500/50': regexValidation.valid === false, 'border-green-500/50': regexValidation.valid === true && isRegexMode }"
          />
          <span
            class="absolute right-3 top-1/2 -translate-y-1/2 text-xs px-1.5 py-0.5 rounded"
            :class="isRegexMode ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'"
          >
            {{ isRegexMode ? '正则' : '包含' }}
          </span>
        </div>

        <p v-if="regexValidation.error" class="text-xs text-red-500">
          {{ regexValidation.error }}
        </p>
        <p v-else class="text-xs text-muted-foreground">
          输入文本匹配名称包含，以 <code class="px-1 py-0.5 rounded bg-muted font-mono">/</code> 开头则为正则模式
        </p>
      </div>
    </div>
  </div>
</template>
