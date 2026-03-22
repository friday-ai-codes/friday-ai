<script setup lang="ts">
import { useClipboard } from '@vueuse/core'
import { useHead } from '@vueuse/head'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Switch } from '~/components/ui/switch'
useHead({ title: '新建 Runner - Friday AI' })
const router = useRouter
const runnersStore = useRunnersStore
const { success: toastSuccess, error: showError } = useToast
const { copy } = useClipboard
const step = ref<'form' | 'success'>('form')
const createdToken = ref<string | null>(null)
const submitting = ref(false)
const form = reactive({
 tags: '' as string,
 run_untagged: true,
 description: '',
 is_paused: false,
 is_protected: false,
 max_timeout: '' as string,
})
async function handleSubmit {
 submitting.value = true
 try {
 const tags = form.tags.split(',').map(t => t.trim).filter(Boolean)
 const result = await runnersStore.addToken({
 scope: 'global',
 expires_in: 3600,
 tags,
 run_untagged: form.run_untagged,
 description: form.description || undefined,
 is_paused: form.is_paused,
 is_protected: form.is_protected,
 max_timeout: form.max_timeout ? Number(form.max_timeout): null,
 })
 createdToken.value = result.token
 step.value = 'success'
 }
 catch (e) { showError('创建失败', e instanceof Error ? e.message: '无法创建 Runner') }
 finally { submitting.value = false }
}
const registerCommand = computed( =>
 `friday-runner register --token ${createdToken.value}`,
)
async function copyCommand {
 await copy(registerCommand.value)
 toastSuccess('已复制注册命令')
}
async function copyToken {
 if (!createdToken.value)
 return
 await copy(createdToken.value)
 toastSuccess('已复制令牌')
}
</script>
<template>
 <PageContainer>
 <!-- 页头 -->
 <div class="flex items-center gap-3">
 <Button variant="ghost" size="icon" @click="router.push('/runners')">
 <span class="icon-[lucide--arrow-left] w-5 " />
 </Button>
 <div>
 <h1 class="text-2xl font-bold">
 {{ step === 'form' ? '创建 Runner': '注册 Runner' }}
 </h1>
 <p class="text-muted-foreground text-sm mt-0.5">
 {{ step === 'form' ? '创建实例 Runner 来生成一个命令，该命令使用其所有配置注册 Runner。': '使用以下命令在目标机器上注册 Runner。' }}
 </p>
 </div>
 </div>
 <!-- Step 1: 表单 -->
 <template v-if="step === 'form'">
 <div class="max-w-2xl space-y-8">
 <!-- 标签 -->
 <div class="space-y-2">
 <Label class="text-sm font-medium">标签</Label>
 <Input v-model="form.tags" placeholder="使用逗号分隔多个标签。例如，macos, shared" />
 <p class="text-xs text-muted-foreground">
 添加标签以指定 Runner 可以运行的作业。
 </p>
 </div>
 <!-- 运行未打标签的作业 -->
 <div class="flex items-center justify-between">
 <div>
 <Label class="text-sm font-medium">运行未打标签的作业</Label>
 <p class="text-xs text-muted-foreground mt-0.5">
 除了标记的任务外，使用 Runner 来执行没有标签的任务。
 </p>
 </div>
 <Switch v-model:checked="form.run_untagged" />
 </div>
 <!-- 配置（可选） -->
 <div class="space-y-6 border-t border-border/50 pt-6">
 <h3 class="text-base font-medium text-muted-foreground">
 配置（可选）
 </h3>
 <!-- Runner 描述 -->
 <div class="space-y-2">
 <Label class="text-sm font-medium">Runner 描述</Label>
 <Input v-model="form.description" placeholder="可选，用于标识 Runner 用途" />
 </div>
 <!-- 已暂停 -->
 <div class="flex items-center justify-between">
 <div>
 <Label class="text-sm font-medium">已暂停</Label>
 <p class="text-xs text-muted-foreground mt-0.5">
 停止 Runner 接收新的作业。
 </p>
 </div>
 <Switch v-model:checked="form.is_paused" />
 </div>
 <!-- 受保护 -->
 <div class="flex items-center justify-between">
 <div>
 <Label class="text-sm font-medium">受保护</Label>
 <p class="text-xs text-muted-foreground mt-0.5">
 只为受保护的分支使用流水线上的 Runner。
 </p>
 </div>
 <Switch v-model:checked="form.is_protected" />
 </div>
 <!-- 最大作业超时 -->
 <div class="space-y-2">
 <Label class="text-sm font-medium">最大作业超时</Label>
 <Input v-model="form.max_timeout" type="number" min="600" placeholder="请以秒为单位输入作业超时时间。必须至少 600 秒。" />
 <p class="text-xs text-muted-foreground">
 Runner 在结束前可以运行的最大时间。如果一个项目的任务超时时间较短，则使用实例 Runner 的任务超时时间。
 </p>
 </div>
 </div>
 <!-- 提交按钮 -->
 <div class="flex justify-end pt-4 border-t border-border/50">
 <Button:disabled="submitting" @click="handleSubmit">
 <span v-if="submitting" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 创建 Runner
 </Button>
 </div>
 </div>
 </template>
 <!-- Step 2: 成功 -->
 <template v-else>
 <div class="max-w-2xl space-y-6">
 <!-- 警告 -->
 <div class="rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 text-sm text-amber-700 dark:text-amber-400">
 <span class="icon-[lucide--alert-triangle] mr-1.5 align-text-bottom" />
 请确保在令牌过期前使用以下注册令牌注册此 Runner。此令牌仅显示一次，关闭后无法再次查看。
 </div>
 <!-- 注册令牌 -->
 <div class="space-y-2">
 <Label class="text-sm font-medium">注册令牌</Label>
 <div class="flex items-center gap-2">
 <code class="flex-1 font-mono bg-muted rounded-lg break-all text-sm">{{ createdToken }}</code>
 <Button variant="outline" size="sm" @click="copyToken">
 <span class="icon-[lucide--copy] mr-1.5" />复制
 </Button>
 </div>
 </div>
 <!-- 注册命令 -->
 <div class="space-y-2">
 <Label class="text-sm font-medium">在目标机器上运行以下命令</Label>
 <div class="flex items-center gap-2">
 <code class="flex-1 font-mono bg-muted rounded-lg break-all text-sm">{{ registerCommand }}</code>
 <Button variant="outline" size="sm" @click="copyCommand">
 <span class="icon-[lucide--copy] mr-1.5" />复制
 </Button>
 </div>
 </div>
 <!-- 操作按钮 -->
 <div class="flex justify-end gap-3 pt-4 border-t border-border/50">
 <Button variant="outline" @click="router.push('/runners')">
 <span class="icon-[lucide--arrow-left] mr-1.5" />
 返回列表
 </Button>
 </div>
 </div>
 </template>
 </PageContainer>
</template>
