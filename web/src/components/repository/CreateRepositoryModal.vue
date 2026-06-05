<script setup lang="ts">
import type { GitPlatform } from '~/types'
import { VueFinalModal } from 'vue-final-modal'
import { repositoriesApi } from '~/api'
import BranchCombobox from '~/components/repository/BranchCombobox.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { MarkdownEditor } from '~/components/ui/markdown-editor'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { PLATFORM_LABELS } from '~/types'

const emit = defineEmits<{
  confirm: [repositoryId: string]
  cancel: []
  closed: []
}>()

const repositoriesStore = useRepositoriesStore()
const { handleError } = useErrorHandler()
const { success } = useToast()

// 表单数据
const form = reactive({
  name: '',
  git_url: '',
  git_platform: 'gitlab' as GitPlatform,
  default_branch: 'main',
  description: '',
  proxy_url: '',
  // 凭证信息（必填）
  access_token: '',
  git_user_name: 'Friday Codes AI Agent',
  git_user_email: 'ai@friday.codes',
})

// 表单验证
const errors = reactive({
  name: '',
  git_url: '',
  access_token: '',
})

function validate(): boolean {
  errors.name = ''
  errors.git_url = ''
  errors.access_token = ''

  if (!form.name.trim()) {
    errors.name = '请输入仓库名称'
  }
  if (!form.git_url.trim()) {
    errors.git_url = '请输入仓库 URL'
  }
  else if (!form.git_url.match(/^https?:\/\//)) {
    errors.git_url = '当前仅支持 HTTPS 仓库 URL'
  }
  if (!form.access_token.trim()) {
    errors.access_token = '请输入 Access Token'
  }

  return !errors.name && !errors.git_url && !errors.access_token
}

// 测试连接
const testing = ref(false)
const testResult = ref<{ success: boolean, message?: string, error?: string, branches?: string[], recommended_branch?: string | null } | null>(null)

async function handleTestConnection() {
  // 验证必填字段
  errors.git_url = ''
  errors.access_token = ''

  if (!form.git_url.trim()) {
    errors.git_url = '请输入仓库 URL'
    return
  }
  if (!form.git_url.match(/^https?:\/\//)) {
    errors.git_url = '当前仅支持 HTTPS 仓库 URL'
    return
  }
  if (!form.access_token.trim()) {
    errors.access_token = '请输入 Access Token'
    return
  }

  testing.value = true
  testResult.value = null

  try {
    const result = await repositoriesApi.testConnection({
      git_url: form.git_url,
      access_token: form.access_token,
      proxy_url: form.proxy_url || undefined,
    })
    testResult.value = result

    if (result.success) {
      if (result.recommended_branch) {
        form.default_branch = result.recommended_branch
      }
      success('连接成功', result.branches?.length ? `发现 ${result.branches.length} 个分支` : '仓库可访问')
    }
    // 失败时不再弹 toast，避免与下方 inline 提示重复
  }
  catch (e: unknown) {
    testResult.value = { success: false, error: e instanceof Error ? e.message : '测试连接失败' }
  }
  finally {
    testing.value = false
  }
}

// 提交表单
const submitting = ref(false)

async function handleSubmit() {
  if (!validate())
    return

  submitting.value = true
  try {
    const repository = await repositoriesStore.createRepository(form)
    success('创建成功', '仓库和凭证已创建')
    emit('confirm', repository.id)
  }
  catch (e: unknown) {
    handleError(e, '创建仓库')
  }
  finally {
    submitting.value = false
  }
}

function handleCancel() {
  emit('cancel')
}

// 平台选项
const platforms: { value: GitPlatform, label: string, icon: string }[] = [
  { value: 'github', label: PLATFORM_LABELS.github, icon: 'lucide--github' },
  { value: 'gitlab', label: PLATFORM_LABELS.gitlab, icon: 'simple-icons--gitlab' },
  { value: 'gitea', label: PLATFORM_LABELS.gitea, icon: 'simple-icons--gitea' },
  { value: 'bitbucket', label: PLATFORM_LABELS.bitbucket, icon: 'simple-icons--bitbucket' },
]

const selectedPlatform = computed(() => platforms.find(p => p.value === form.git_platform))
</script>

<template>
  <VueFinalModal
    class="flex justify-center items-center"
    content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-2xl w-full mx-4 max-h-[90vh]"
    overlay-transition="vfm-fade"
    content-transition="vfm-zoom"
    @closed="emit('closed')"
  >
    <!-- Header -->
    <div class="flex items-center justify-between px-6 py-5 border-b border-border/50 shrink-0">
      <div class="flex items-center gap-3">
        <div class="p-2.5 rounded-xl bg-primary/10">
          <span class="icon-[lucide--git-branch] text-xl text-violet-600" />
        </div>
        <div>
          <h3 class="text-lg font-semibold text-foreground">
            新建仓库
          </h3>
          <p class="text-sm text-muted-foreground">
            配置 Git 仓库信息，用于 AI 辅助开发任务
          </p>
        </div>
      </div>
      <button
        type="button"
        class="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
        @click="handleCancel"
      >
        <span class="icon-[lucide--x] text-lg" />
      </button>
    </div>

    <!-- Body -->
    <form class="flex-1 overflow-y-auto px-6 py-5 space-y-5" @submit.prevent="handleSubmit">
      <!-- 仓库名称 -->
      <div class="space-y-2">
        <Label for="name" class="flex items-center gap-1 text-foreground">
          仓库名称
          <span class="text-destructive">*</span>
        </Label>
        <Input
          id="name"
          v-model="form.name"
          placeholder="例如：friday-ai"
          class="h-10"
          :class="{ 'border-destructive': errors.name }"
        />
        <p v-if="errors.name" class="text-sm text-destructive flex items-center gap-1">
          <span class="icon-[lucide--alert-circle]" />
          {{ errors.name }}
        </p>
      </div>

      <!-- 仓库 URL -->
      <div class="space-y-2">
        <Label for="git_url" class="flex items-center gap-1 text-foreground">
          仓库 URL
          <span class="text-destructive">*</span>
        </Label>
        <Input
          id="git_url"
          v-model="form.git_url"
          placeholder="https://github.com/user/repo.git"
          class="h-10"
          :class="{ 'border-destructive': errors.git_url }"
        />
        <p v-if="errors.git_url" class="text-sm text-destructive flex items-center gap-1">
          <span class="icon-[lucide--alert-circle]" />
          {{ errors.git_url }}
        </p>
        <p class="text-xs text-muted-foreground">
          支持 HTTPS 或 SSH 格式
        </p>
      </div>

      <!-- 代理 URL (可选) -->
      <div class="space-y-2">
        <Label for="proxy_url" class="flex items-center gap-1 text-foreground">
          Git 代理 URL
          <span class="text-xs font-normal text-muted-foreground">(可选)</span>
        </Label>
        <Input
          id="proxy_url"
          v-model="form.proxy_url"
          placeholder="http://proxy.example.com:8080"
          class="h-10"
        />
        <p class="text-xs text-muted-foreground">
          用于该仓库 Git 操作的 HTTP 代理
        </p>
      </div>

      <!-- 仓库简介 -->
      <div class="space-y-2">
        <Label for="description" class="flex items-center gap-1 text-foreground">
          仓库简介
          <span class="text-xs font-normal text-muted-foreground">(可选，支持 Markdown)</span>
        </Label>
        <MarkdownEditor
          v-model="form.description"
          placeholder="简要描述仓库的用途和功能，支持 Markdown 语法..."
          height="200px"
        />
      </div>

      <!-- Git 平台和默认分支 -->
      <div class="grid gap-4 md:grid-cols-2">
        <div class="space-y-2">
          <Label class="text-foreground">Git 平台</Label>
          <Select v-model="form.git_platform">
            <SelectTrigger class="h-10">
              <SelectValue placeholder="选择平台">
                <div v-if="selectedPlatform" class="flex items-center gap-2">
                  <span :class="`icon-[${selectedPlatform.icon}]`" />
                  {{ selectedPlatform.label }}
                </div>
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="p in platforms" :key="p.value" :value="p.value">
                <div class="flex items-center gap-2">
                  <span :class="`icon-[${p.icon}]`" />
                  {{ p.label }}
                </div>
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div class="space-y-2">
          <Label for="default_branch" class="text-foreground">默认分支（索引用）</Label>
          <BranchCombobox
            v-if="testResult?.success"
            v-model="form.default_branch"
            :branches="testResult?.branches || []"
            :recommended-branch="testResult?.recommended_branch"
          />
          <Input
            v-else
            id="default_branch"
            v-model="form.default_branch"
            placeholder="main"
            class="h-10"
          />
          <p class="text-xs text-muted-foreground">
            代码索引会使用这个默认分支
          </p>
        </div>
      </div>

      <!-- 凭证配置区域 -->
      <div class="relative p-5 -mx-2 border border-amber-200/50 rounded-xl">
        <div class="flex items-center gap-3 mb-4">
          <div class="p-2 rounded-lg bg-primary/10">
            <span class="icon-[lucide--key] text-lg text-amber-600" />
          </div>
          <div>
            <h4 class="font-semibold text-sm text-foreground">
              Git 凭证配置
            </h4>
            <p class="text-xs text-muted-foreground">
              配置用于访问仓库的 Access Token（必填）
            </p>
          </div>
        </div>

        <!-- Access Token -->
        <div class="space-y-4">
          <div class="space-y-2">
            <Label for="access_token" class="flex items-center gap-1 text-foreground">
              Access Token
              <span class="text-destructive">*</span>
            </Label>
            <Input
              id="access_token"
              v-model="form.access_token"
              type="password"
              placeholder="ghp_xxxxxxxxxxxx 或 glpat-xxxxxxxxxxxx"
              class="h-10 bg-card"
              :class="{ 'border-destructive': errors.access_token }"
            />
            <p v-if="errors.access_token" class="text-sm text-destructive flex items-center gap-1">
              <span class="icon-[lucide--alert-circle]" />
              {{ errors.access_token }}
            </p>
            <p class="text-xs text-muted-foreground">
              需要仓库读写权限的个人访问令牌（PAT），该令牌会被加密存储
            </p>
          </div>

          <!-- Git 用户信息 -->
          <div class="grid gap-4 md:grid-cols-2">
            <div class="space-y-2">
              <Label for="git_user_name" class="text-foreground">Git 用户名</Label>
              <Input
                id="git_user_name"
                v-model="form.git_user_name"
                placeholder="Friday AI Agent"
                class="h-10 bg-card"
              />
            </div>
            <div class="space-y-2">
              <Label for="git_user_email" class="text-foreground">Git 邮箱</Label>
              <Input
                id="git_user_email"
                v-model="form.git_user_email"
                type="email"
                placeholder="ai@friday.codes"
                class="h-10 bg-card"
              />
            </div>
          </div>

          <!-- 测试连接按钮 -->
          <div class="pt-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              class="w-full"
              :disabled="testing || !form.git_url || !form.access_token"
              @click="handleTestConnection"
            >
              <span v-if="testing" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
              <span v-else class="icon-[lucide--plug] mr-2" />
              {{ testing ? '测试中...' : '测试连接' }}
            </Button>
            <!-- 测试结果 -->
            <div
              v-if="testResult"
              class="mt-3 px-3 py-2.5 rounded-xl text-sm border flex items-start gap-2"
              :class="testResult.success
                ? 'bg-emerald-50/80 text-emerald-700 border-emerald-200/60'
                : 'bg-red-50/80 text-red-700 border-red-200/60'"
            >
              <span
                class="text-base shrink-0 mt-0.5"
                :class="testResult.success ? 'icon-[lucide--check-circle]' : 'icon-[lucide--x-circle]'"
              />
              <span class="leading-relaxed wrap-break-word min-w-0">
                {{ testResult.success ? '连接成功' : (testResult.error || '连接失败') }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="flex justify-end gap-3 pt-4 border-t border-border/50">
        <Button type="button" variant="outline" :disabled="submitting" @click="handleCancel">
          取消
        </Button>
        <Button type="submit" :disabled="submitting">
          <span v-if="submitting" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
          <span v-else class="icon-[lucide--plus] mr-2" />
          创建仓库
        </Button>
      </div>
    </form>
  </VueFinalModal>
</template>
