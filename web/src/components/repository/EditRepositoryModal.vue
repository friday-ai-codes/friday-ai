<script setup lang="ts">
import type { GitPlatform } from '~/types'
import { VueFinalModal } from 'vue-final-modal'
import { repositoriesApi } from '~/api'
import BranchCombobox from '~/components/repository/BranchCombobox.vue'
import SpaceMultiSelect from '~/components/repository/SpaceMultiSelect.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { PLATFORM_LABELS } from '~/types'

const props = defineProps<{
  repository: {
    id: string
    name: string
    git_url: string
    git_platform: GitPlatform
    default_branch: string
    remote_head_branch?: string | null
    proxy_url?: string
    has_credential: boolean
    spaces?: { id: string, name: string }[]
  }
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
  closed: []
}>()

const repositoriesStore = useRepositoriesStore()
const { handleError } = useErrorHandler()
const { success } = useToast()

// 表单数据
const form = reactive({
  name: props.repository.name,
  git_url: props.repository.git_url,
  git_platform: props.repository.git_platform,
  default_branch: props.repository.default_branch,
  proxy_url: props.repository.proxy_url || '',
})

// 关联空间（必须至少保留一个）
const spaceIds = ref<string[]>((props.repository.spaces ?? []).map(s => s.id))

// 一键配置 Webhook（仅 GitLab）：保存后自动在 GitLab 侧创建/更新 push webhook
const autoSetupWebhook = ref(false)
const showWebhookOption = computed(
  () => form.git_platform === 'gitlab' && props.repository.has_credential,
)

const branches = ref<string[]>([])
const headBranch = ref<string | null>(props.repository.remote_head_branch ?? null)
const recommendedBranch = ref<string | null>(null)
const loadingBranches = ref(false)

async function fetchBranches() {
  if (!props.repository.has_credential)
    return
  loadingBranches.value = true
  try {
    const result = await repositoriesApi.testRepositoryConnection(props.repository.id)
    if (result.success) {
      branches.value = result.branches || []
      headBranch.value = result.head_branch ?? headBranch.value
      recommendedBranch.value = result.recommended_branch ?? null
      if (result.recommended_branch && !form.default_branch)
        form.default_branch = result.recommended_branch
    }
  }
  catch {
    // 降级为文本输入（branches 保持空数组）
  }
  finally {
    loadingBranches.value = false
  }
}

onMounted(fetchBranches)

// 表单验证
const errors = reactive({
  name: '',
  git_url: '',
  spaces: '',
})

function validate(): boolean {
  errors.name = ''
  errors.git_url = ''
  errors.spaces = ''

  if (!form.name.trim()) {
    errors.name = '请输入仓库名称'
  }
  if (!form.git_url.trim()) {
    errors.git_url = '请输入仓库 URL'
  }
  else if (!/^https?:\/\//.test(form.git_url)) {
    errors.git_url = '当前仅支持 HTTPS 仓库 URL'
  }
  if (spaceIds.value.length === 0) {
    errors.spaces = '仓库必须至少关联一个空间'
  }

  return !errors.name && !errors.git_url && !errors.spaces
}

// 提交表单
const submitting = ref(false)

async function handleSubmit() {
  if (!validate())
    return

  const defaultBranchChanged = form.default_branch !== props.repository.default_branch
  const originalSpaceIds = (props.repository.spaces ?? []).map(s => s.id)
  const spacesChanged
    = spaceIds.value.length !== originalSpaceIds.length
      || spaceIds.value.some(id => !originalSpaceIds.includes(id))

  submitting.value = true
  try {
    await repositoriesStore.updateRepository(props.repository.id, form)
    if (spacesChanged)
      await repositoriesApi.setLinkedSpaces(props.repository.id, spaceIds.value)
    if (defaultBranchChanged) {
      success('更新成功', '默认分支已变更，正在滚动更新索引')
    }
    else {
      success('更新成功', '仓库信息已更新')
    }

    // best-effort 自动配置 Webhook：失败不阻塞保存
    if (showWebhookOption.value && autoSetupWebhook.value) {
      try {
        const result = await repositoriesApi.setupWebhook(props.repository.id)
        success('Webhook 已自动配置', `GitLab push webhook 已${result.action === 'created' ? '创建' : '更新'}（分支：${result.branch_filter || '全部'}）`)
      }
      catch (e: unknown) {
        handleError(e, '自动配置 Webhook（可稍后在仓库详情的 Webhook 面板重试）')
      }
    }

    emit('confirm')
  }
  catch (e: unknown) {
    handleError(e, '更新仓库')
  }
  finally {
    submitting.value = false
  }
}

function handleCancel() {
  emit('cancel')
}

// 测试连接
const testing = ref(false)
const testResult = ref<{ success: boolean, message?: string, error?: string, branches?: string[] } | null>(null)

// 当 repository prop 变化时，重置表单数据
watch(() => props.repository, (newRepo) => {
  form.name = newRepo.name
  form.git_url = newRepo.git_url
  form.git_platform = newRepo.git_platform
  form.default_branch = newRepo.default_branch
  form.proxy_url = newRepo.proxy_url || ''
  spaceIds.value = (newRepo.spaces ?? []).map(s => s.id)
  errors.name = ''
  errors.git_url = ''
  errors.spaces = ''
  testResult.value = null
  branches.value = []
  headBranch.value = newRepo.remote_head_branch ?? null
  recommendedBranch.value = null
  fetchBranches()
}, { deep: true })

async function handleTestConnection() {
  testing.value = true
  testResult.value = null

  try {
    const result = await repositoriesApi.testRepositoryConnection(props.repository.id)
    testResult.value = result

    if (result.success) {
      success('连接成功', '仓库可访问')
    }
    // 失败时不弹 toast，错误已在状态条内联显示
  }
  catch (e: unknown) {
    testResult.value = { success: false, error: e instanceof Error ? e.message : '测试连接失败' }
  }
  finally {
    testing.value = false
  }
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
    content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-4xl w-full mx-4 max-h-[90vh]"
    overlay-transition="vfm-fade"
    content-transition="vfm-zoom"
    @closed="emit('closed')"
  >
    <!-- Header -->
    <div class="flex items-center justify-between px-6 py-5 border-b border-border/50 shrink-0">
      <div class="flex items-center gap-3">
        <div class="p-2.5 rounded-xl bg-primary/10">
          <span class="icon-[lucide--edit] text-xl text-violet-600" />
        </div>
        <div>
          <h3 class="text-lg font-semibold text-foreground">
            编辑仓库
          </h3>
          <p class="text-sm text-muted-foreground">
            修改仓库基本信息和配置
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
          仅支持 HTTPS 格式（认证基于 Access Token，暂不支持 SSH）
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
          <div v-if="loadingBranches" class="flex items-center gap-2 h-10 px-3 text-sm text-muted-foreground">
            <span class="icon-[lucide--loader-circle] animate-spin" />
            加载分支列表...
          </div>
          <BranchCombobox
            v-else
            v-model="form.default_branch"
            :branches="branches"
            :head-branch="headBranch"
            :recommended-branch="recommendedBranch"
          />
          <p class="text-xs text-muted-foreground">
            代码索引会使用这个默认分支，HEAD 为远端默认分支
          </p>
        </div>
      </div>

      <!-- 一键配置 Webhook（仅 GitLab 且已有凭证） -->
      <label
        v-if="showWebhookOption"
        class="flex items-start gap-2.5 p-3 rounded-lg border border-border/50 bg-muted/20 cursor-pointer hover:bg-muted/30 transition-colors"
      >
        <input
          v-model="autoSetupWebhook"
          type="checkbox"
          class="mt-0.5 accent-primary"
        >
        <span class="min-w-0">
          <span class="block text-sm font-medium text-foreground">
            自动配置 Webhook
          </span>
          <span class="block text-xs text-muted-foreground">
            保存后用仓库凭证自动在 GitLab 项目中创建/更新 push webhook：默认分支变更时自动通知本服务更新索引（需要 token 为项目 Maintainer 及以上且具有 api scope）
          </span>
        </span>
      </label>

      <!-- 关联空间 -->
      <div class="space-y-2">
        <Label class="flex items-center gap-1 text-foreground">
          关联空间
          <span class="text-destructive">*</span>
        </Label>
        <SpaceMultiSelect v-model="spaceIds" />
        <p v-if="errors.spaces" class="text-sm text-destructive flex items-center gap-1">
          <span class="icon-[lucide--alert-circle]" />
          {{ errors.spaces }}
        </p>
        <p v-else class="text-xs text-muted-foreground">
          仓库必须至少关联一个空间
        </p>
      </div>

      <!-- 测试连接 -->
      <div class="flex items-start justify-between gap-3 p-4 rounded-xl bg-muted/30 border border-border/50">
        <div class="flex items-start gap-3 flex-1 min-w-0">
          <div class="p-2 rounded-lg bg-primary/10 shrink-0">
            <span
              v-if="testing"
              class="icon-[lucide--loader-circle] text-lg text-muted-foreground animate-spin"
            />
            <span
              v-else-if="testResult?.success"
              class="icon-[lucide--check-circle] text-lg text-emerald-600"
            />
            <span
              v-else-if="testResult && !testResult.success"
              class="icon-[lucide--x-circle] text-lg text-red-500"
            />
            <span
              v-else
              class="icon-[lucide--plug] text-lg text-muted-foreground"
            />
          </div>
          <div class="min-w-0 flex-1">
            <h4 class="font-medium text-sm text-foreground">
              {{ testing ? '正在测试连接...' : testResult?.success ? '连接成功' : testResult && !testResult.success ? '连接失败' : '连接测试' }}
            </h4>
            <p class="text-xs leading-relaxed wrap-break-word" :class="testResult && !testResult.success ? 'text-red-600' : 'text-muted-foreground'">
              <template v-if="testing">
                验证仓库凭证中
              </template>
              <template v-else-if="testResult?.success">
                仓库可访问
              </template>
              <template v-else-if="testResult && !testResult.success">
                {{ testResult.error || '无法连接到仓库' }}
              </template>
              <template v-else>
                验证仓库凭证是否有效
              </template>
            </p>
          </div>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          class="shrink-0"
          :disabled="testing"
          @click="handleTestConnection"
        >
          <span v-if="testing" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
          <span v-else-if="testResult" class="icon-[lucide--refresh-cw] mr-2" />
          <span v-else class="icon-[lucide--zap] mr-2" />
          {{ testing ? '测试中...' : testResult ? '重新测试' : '测试连接' }}
        </Button>
      </div>

      <!-- Footer -->
      <div class="flex justify-end gap-3 pt-4 border-t border-border/50">
        <Button type="button" variant="outline" :disabled="submitting" @click="handleCancel">
          取消
        </Button>
        <Button type="submit" :disabled="submitting">
          <span v-if="submitting" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
          <span v-else class="icon-[lucide--save] mr-2" />
          保存修改
        </Button>
      </div>
    </form>
  </VueFinalModal>
</template>
