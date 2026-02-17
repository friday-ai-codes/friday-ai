<script setup lang="ts">
import type { CreateBranchConfig } from '~/types/workflow/schemas'
import { computed } from 'vue'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
import { Switch } from '~/components/ui/switch'
import RepositoryPicker from '~/components/workflow/RepositoryPicker.vue'
import VariablePicker from '~/components/workflow/VariablePicker.vue'
import { useConfigModel } from '~/composables/useConfigModel'
import { createBranchConfigSchema } from '~/types/workflow/schemas'
// ============================================================================
// Props & Emits
// ============================================================================
interface Props {
 config: CreateBranchConfig
 repositories?: Array<{ id: string, name: string }>
}
const props = withDefaults(defineProps<Props>, {
 repositories: =>,
})
const emit = defineEmits<{
 (e: 'update:config', value: CreateBranchConfig): void
}>
// ============================================================================
// Config Model
// ============================================================================
const { field } = useConfigModel({
 config: => props.config,
 emit: v => emit('update:config', v),
 schema: createBranchConfigSchema,
})
// Repositories (computed for v-model compatibility)
const repositories = computed({
 get: => props.config.repositories ??,
 set: (val: string) => emit('update:config', { ...props.config, repositories: val }),
})
// Other fields
const branchName = field('branch_name', '')
const baseBranch = field('base_branch', 'main')
const checkout = field('checkout', true)
const push = field('push', false)
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
 v-model="repositories":repositories="props.repositories"
 placeholder="选择要创建分支的仓库..."
 />
 <p class="text-xs text-muted-foreground">
 选择需要创建分支的代码仓库，支持多选
 </p>
 </div>
 <Separator />
 <!-- 分支配置 -->
 <div class="space-y-4">
 <!-- 分支名称 -->
 <div class="space-y-2">
 <Label class="flex items-center gap-1">
 分支名称
 <span class="text-destructive">*</span>
 </Label>
 <div class="flex gap-2">
 <Input
 v-model="branchName"
 placeholder="feature/xxx 或 {{ global.branch_name }}"
 class="font-mono text-sm flex-1"
 />
 <VariablePicker @select="v => branchName = v" />
 </div>
 <p class="text-xs text-muted-foreground">
 新分支名称，支持模板变量
 </p>
 </div>
 <!-- 基础分支 -->
 <div class="space-y-2">
 <Label>基础分支</Label>
 <div class="flex gap-2">
 <Input
 v-model="baseBranch"
 placeholder="main"
 class="font-mono text-sm flex-1"
 />
 <VariablePicker @select="v => baseBranch = v" />
 </div>
 <p class="text-xs text-muted-foreground">
 从此分支创建新分支，默认为 main
 </p>
 </div>
 </div>
 <Separator />
 <!-- 操作选项 -->
 <div class="space-y-3">
 <Label>操作选项</Label>
 <div class="flex items-center justify-between">
 <div>
 <span class="text-sm">切换到新分支</span>
 <p class="text-xs text-muted-foreground">
 创建后自动切换到新分支
 </p>
 </div>
 <Switch v-model:checked="checkout" />
 </div>
 <div class="flex items-center justify-between">
 <div>
 <span class="text-sm">推送到远程</span>
 <p class="text-xs text-muted-foreground">
 创建后自动推送新分支到远程仓库
 </p>
 </div>
 <Switch v-model:checked="push" />
 </div>
 </div>
 <!-- 输出变量说明 -->
 <div class="rounded-lg bg-muted/50 space-y-2">
 <p class="text-xs font-medium text-muted-foreground flex items-center gap-1">
 <span class="icon-[lucide--code] text-cyan-500" />
 输出变量
 </p>
 <div class="bg-muted rounded-lg space-y-1.5 text-xs">
 <div class="flex gap-2">
 <code class="bg-background px-1.5 py-0.5 rounded min-w-40">$.branch_name</code>
 <span class="text-muted-foreground">创建的分支名称</span>
 </div>
 <div class="flex gap-2">
 <code class="bg-background px-1.5 py-0.5 rounded min-w-40">$.succeeded</code>
 <span class="text-muted-foreground">成功创建分支的仓库列表</span>
 </div>
 <div class="flex gap-2">
 <code class="bg-background px-1.5 py-0.5 rounded min-w-40">$.failed</code>
 <span class="text-muted-foreground">创建失败的仓库列表</span>
 </div>
 </div>
 </div>
 </div>
</template>
