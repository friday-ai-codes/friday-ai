<script setup lang="ts">
import type { CreatePRConfig } from '~/types/workflow/schemas'

import { computed } from 'vue'

import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
import { Switch } from '~/components/ui/switch'
import { Textarea } from '~/components/ui/textarea'
import RepositoryPicker from '~/components/workflow/RepositoryPicker.vue'
import VariablePicker from '~/components/workflow/VariablePicker.vue'
import { useConfigModel } from '~/composables/useConfigModel'
import { createPRConfigSchema } from '~/types/workflow/schemas'

// ============================================================================
// Types
// ============================================================================

interface Repository {
  id: string
  name: string
}

// ============================================================================
// Props & Emits
// ============================================================================

interface Props {
  config: CreatePRConfig
  repositories?: Repository[]
}

const props = withDefaults(defineProps<Props>(), {
  repositories: () => [],
})

const emit = defineEmits<{
  (e: 'update:config', value: CreatePRConfig): void
}>()

// ============================================================================
// Config Model
// ============================================================================

const { field } = useConfigModel({
  config: () => props.config,
  emit: v => emit('update:config', v),
  schema: createPRConfigSchema,
})

// Repositories
const repositories = computed({
  get: () => props.config.repositories ?? [],
  set: (val: string[]) => emit('update:config', { ...props.config, repositories: val }),
})

// PR fields
const title = field('title', '')
const body = field('body', '')
const headBranch = field('head_branch', '')
const baseBranch = field('base_branch', 'main')
const draft = field('draft', false)
const addCrossReferences = field('add_cross_references', true)
</script>

<template>
  <div class="space-y-4">
    <!-- 目标仓库 -->
    <div class="space-y-2">
      <Label class="flex items-center gap-1">
        目标仓库
        <span class="text-destructive">*</span>
      </Label>
      <RepositoryPicker
        v-model="repositories"
        :repositories="props.repositories"
        placeholder="选择要创建 PR 的仓库..."
      />
      <p class="text-xs text-muted-foreground">
        选择需要创建 Pull Request 的仓库，支持多选
      </p>
    </div>

    <Separator />

    <!-- PR 内容 -->
    <div class="space-y-4">
      <!-- 标题 -->
      <div class="space-y-2">
        <Label class="flex items-center gap-1">
          PR 标题
          <span class="text-destructive">*</span>
        </Label>
        <div class="flex gap-2">
          <Input
            v-model="title"
            placeholder="feat: xxx 或 {{ global.pr_title }}"
            class="flex-1"
          />
          <VariablePicker @select="v => title = v" />
        </div>
      </div>

      <!-- 描述 -->
      <div class="space-y-2">
        <Label>PR 描述</Label>
        <div class="flex gap-2">
          <Textarea
            v-model="body"
            placeholder="PR 描述内容，支持 Markdown 和模板变量"
            rows="4"
            class="flex-1"
          />
        </div>
        <div class="flex items-center justify-between">
          <p class="text-xs text-muted-foreground">
            支持 Markdown 格式和模板变量
          </p>
          <VariablePicker @select="v => body += v" />
        </div>
      </div>
    </div>

    <Separator />

    <!-- 分支配置 -->
    <div class="space-y-4">
      <!-- 源分支 -->
      <div class="space-y-2">
        <Label class="flex items-center gap-1">
          源分支 (Head)
          <span class="text-destructive">*</span>
        </Label>
        <div class="flex gap-2">
          <Input
            v-model="headBranch"
            placeholder="feature/xxx 或 {{ nodes.create_branch.branch_name }}"
            class="font-mono text-sm flex-1"
          />
          <VariablePicker @select="v => headBranch = v" />
        </div>
        <p class="text-xs text-muted-foreground">
          包含更改的分支
        </p>
      </div>

      <!-- 目标分支 -->
      <div class="space-y-2">
        <Label>目标分支 (Base)</Label>
        <div class="flex gap-2">
          <Input
            v-model="baseBranch"
            placeholder="main"
            class="font-mono text-sm flex-1"
          />
          <VariablePicker @select="v => baseBranch = v" />
        </div>
        <p class="text-xs text-muted-foreground">
          PR 将合入的目标分支，默认为 main
        </p>
      </div>
    </div>

    <Separator />

    <!-- 高级选项 -->
    <div class="space-y-3">
      <Label>高级选项</Label>

      <!-- 草稿 PR -->
      <div class="flex items-center justify-between">
        <div>
          <span class="text-sm">创建为草稿</span>
          <p class="text-xs text-muted-foreground">
            PR 将标记为草稿状态，暂不可合并
          </p>
        </div>
        <Switch v-model:checked="draft" />
      </div>

      <!-- 交叉引用 - 使用 Glassmorphism 卡片样式 -->
      <div class="flex items-center justify-between rounded-lg border border-border/50 p-3">
        <div class="flex items-center gap-3">
          <div class="p-2 rounded-lg bg-primary/10">
            <span class="icon-[lucide--link] text-primary" />
          </div>
          <div>
            <span class="text-sm font-medium">添加交叉引用</span>
            <p class="text-xs text-muted-foreground">
              在 PR 描述中添加关联 PR 链接
            </p>
          </div>
        </div>
        <Switch v-model:checked="addCrossReferences" />
      </div>
    </div>

    <!-- 输出变量说明 -->
    <div class="rounded-lg bg-muted/50 p-3 space-y-2">
      <p class="text-xs font-medium text-muted-foreground flex items-center gap-1">
        <span class="icon-[lucide--code] text-primary" />
        输出变量
      </p>
      <div class="bg-muted rounded-lg p-3 space-y-1.5 text-xs">
        <div class="flex gap-2">
          <code class="bg-background px-1.5 py-0.5 rounded min-w-40">$.pull_requests</code>
          <span class="text-muted-foreground">创建的 PR 列表（含 URL、编号）</span>
        </div>
        <div class="flex gap-2">
          <code class="bg-background px-1.5 py-0.5 rounded min-w-40">$.succeeded</code>
          <span class="text-muted-foreground">成功创建 PR 的仓库列表</span>
        </div>
        <div class="flex gap-2">
          <code class="bg-background px-1.5 py-0.5 rounded min-w-40">$.failed</code>
          <span class="text-muted-foreground">创建失败的仓库列表</span>
        </div>
      </div>
    </div>
  </div>
</template>
