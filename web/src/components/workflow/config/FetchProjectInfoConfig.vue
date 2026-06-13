<script setup lang="ts">
import type { FetchSpaceInfoConfig, WorkflowEdgeStore, WorkflowNodeStore } from '~/types/workflow'

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
import SmartInput from '~/components/workflow/smart-input/SmartInput.vue'
import { useConfigModel } from '~/composables/useConfigModel'
import { fetchSpaceInfoConfigSchema } from '~/types/workflow'

// ============================================================================
// Props & Emits
// ============================================================================

interface Props {
  config: FetchSpaceInfoConfig
  workflowNodes?: WorkflowNodeStore[]
  workflowEdges?: WorkflowEdgeStore[]
  currentNodeId?: string
}

const props = withDefaults(defineProps<Props>(), {
  workflowNodes: () => [],
  workflowEdges: () => [],
  currentNodeId: '',
})
const emit = defineEmits<{
  (e: 'update:config', value: FetchSpaceInfoConfig): void
}>()

// ============================================================================
// Config Model
// ============================================================================

const { field } = useConfigModel({
  config: () => props.config,
  emit: v => emit('update:config', v),
  schema: fetchSpaceInfoConfigSchema,
})

const projectIdentifier = field('project_identifier', '')
const identifierType = field('identifier_type', 'auto')
const includeRepositories = field('include_repositories', true)
const includeFeishuConfig = field('include_feishu_config', false)
const includeClaudeConfig = field('include_claude_config', false)
const includeWebhookToken = field('include_webhook_token', false)

// ============================================================================
// Options
// ============================================================================

const identifierTypeOptions = [
  { value: 'auto', label: '自动检测', description: '优先尝试 UUID，再尝试飞书项目 Key' },
  { value: 'id', label: '项目 ID', description: '使用项目 UUID' },
  { value: 'feishu_project_key', label: '飞书项目 Key', description: '使用飞书项目标识' },
]
</script>

<template>
  <div class="space-y-4">
    <!-- 项目标识 -->
    <div class="space-y-2">
      <Label class="flex items-center gap-1">
        项目标识
        <span class="text-destructive">*</span>
      </Label>
      <SmartInput
        v-model="projectIdentifier"
        :workflow-nodes="workflowNodes"
        :workflow-edges="workflowEdges"
        :current-node-id="currentNodeId"
        placeholder="输入 {{ 触发变量联想"
      />
    </div>

    <!-- 标识类型 -->
    <div class="space-y-2">
      <Label>标识类型</Label>
      <Select v-model="identifierType">
        <SelectTrigger>
          <SelectValue placeholder="选择标识类型" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem
            v-for="opt in identifierTypeOptions"
            :key="opt.value"
            :value="opt.value"
          >
            <div>
              <div>{{ opt.label }}</div>
              <div class="text-xs text-muted-foreground">
                {{ opt.description }}
              </div>
            </div>
          </SelectItem>
        </SelectContent>
      </Select>
    </div>

    <Separator />

    <!-- 获取内容选项 -->
    <div class="space-y-3">
      <Label>获取内容</Label>

      <!-- 仓库列表 -->
      <div class="flex items-center justify-between rounded-lg border border-border/50 p-3">
        <div class="flex items-center gap-3">
          <div class="p-2 rounded-lg bg-primary/10">
            <span class="icon-[lucide--git-branch] text-primary" />
          </div>
          <div>
            <span class="text-sm font-medium">仓库列表</span>
            <p class="text-xs text-muted-foreground">
              项目关联的所有代码仓库
            </p>
          </div>
        </div>
        <Switch v-model="includeRepositories" />
      </div>

      <!-- 飞书配置 -->
      <div class="flex items-center justify-between rounded-lg border border-border/50 p-3">
        <div class="flex items-center gap-3">
          <div class="p-2 rounded-lg bg-primary/10">
            <span class="icon-[lucide--message-square] text-primary" />
          </div>
          <div>
            <span class="text-sm font-medium">飞书配置</span>
            <p class="text-xs text-muted-foreground">
              插件 ID、用户 Key 等集成配置
            </p>
          </div>
        </div>
        <Switch v-model="includeFeishuConfig" />
      </div>

      <!-- Claude 配置 -->
      <div class="flex items-center justify-between rounded-lg border border-border/50 p-3">
        <div class="flex items-center gap-3">
          <div class="p-2 rounded-lg bg-primary/10">
            <span class="icon-[lucide--bot] text-primary" />
          </div>
          <div>
            <span class="text-sm font-medium">Claude 配置</span>
            <p class="text-xs text-muted-foreground">
              API 密钥状态、Base URL 等
            </p>
          </div>
        </div>
        <Switch v-model="includeClaudeConfig" />
      </div>

      <!-- Webhook Token -->
      <div class="flex items-center justify-between rounded-lg border border-border/50 p-3">
        <div class="flex items-center gap-3">
          <div class="p-2 rounded-lg bg-primary/10">
            <span class="icon-[lucide--key] text-primary" />
          </div>
          <div>
            <span class="text-sm font-medium">Webhook Token</span>
            <p class="text-xs text-muted-foreground">
              飞书 Webhook 验证令牌
            </p>
          </div>
        </div>
        <Switch v-model="includeWebhookToken" />
      </div>
    </div>
  </div>
</template>
