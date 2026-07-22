<script setup lang="ts">
import type { GitInstanceCredential } from '~/api/gitInstanceCredentials'
import type { GitPlatform } from '~/types'
import { watchDebounced } from '@vueuse/core'
import { VueFinalModal } from 'vue-final-modal'
import { repositoriesApi } from '~/api'
import { gitInstanceCredentialsApi } from '~/api/gitInstanceCredentials'
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

const emit = defineEmits<{
  confirm: [repositoryId: string]
  cancel: []
  closed: []
}>()

const repositoriesStore = useRepositoriesStore()
const { handleError } = useErrorHandler()
const { success } = useToast()

// 表单数据（默认分支不再让用户手填：测试连接成功后从远端分支列表中必选）
const form = reactive({
  name: '',
  git_url: '',
  git_platform: 'gitlab' as GitPlatform,
  default_branch: '' as string,
  proxy_url: '',
  // 凭证信息（TOKEN-02：access_token 可选——可填自有 token 或选密钥提供方）
  access_token: '',
  // TOKEN-01：密钥提供方（实例凭证）id；空串=不指定（按 host 自动匹配或填自有 token）
  git_instance_credential_id: '',
  git_user_name: 'Friday Codes AI Agent',
  git_user_email: 'ai@friday.codes',
})

// 密钥提供方（实例凭证）列表：供「不填自有 token」时选择
const instanceCredentials = ref<GitInstanceCredential[]>([])
onMounted(async () => {
  try {
    instanceCredentials.value = await gitInstanceCredentialsApi.list()
  }
  catch {
    // 加载失败不阻塞建仓：用户仍可填自有 token
    instanceCredentials.value = []
  }
})
// 有自有 token 或选了密钥提供方任一即视为「凭证已就绪」（host 自动匹配由后端兜底）
const hasCredentialInput = computed(
  () => Boolean(form.access_token.trim()) || Boolean(form.git_instance_credential_id),
)

// 关联空间（可选，可后期再绑定）
const spaceIds = ref<string[]>([])

// 一键配置 Webhook（仅 GitLab）：建仓成功后自动在 GitLab 侧创建 push webhook
const autoSetupWebhook = ref(true)
const showWebhookOption = computed(
  () => form.git_platform === 'gitlab' && Boolean(testResult.value?.success),
)

// 表单验证
const errors = reactive({
  name: '',
  git_url: '',
  access_token: '',
  default_branch: '',
  spaces: '',
})

function validate(): boolean {
  errors.name = ''
  errors.git_url = ''
  errors.access_token = ''
  errors.default_branch = ''
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
  // TOKEN-02：token 可选——但必须有自有 token 或选定密钥提供方之一（host 自动匹配由后端兜底，
  // 这里仅做最基本引导：两者都空时提示，但不强制阻断 host-匹配场景由后端校验）
  if (!hasCredentialInput.value && !testResult.value?.success) {
    errors.access_token = '请填写 Access Token 或选择密钥提供方'
  }
  if (!testResult.value?.success) {
    errors.default_branch = '请先测试连接，从远端分支列表中选择默认分支'
  }
  else if (!form.default_branch) {
    errors.default_branch = '请选择默认分支'
  }
  // #9：空间为可选——允许先建仓、之后再绑定空间

  return !errors.name && !errors.git_url && !errors.access_token
    && !errors.default_branch && !errors.spaces
}

// 测试连接
const testing = ref(false)
const testResult = ref<{ success: boolean, message?: string, error?: string, branches?: string[], head_branch?: string | null, recommended_branch?: string | null } | null>(null)

const canTest = computed(() =>
  /^https?:\/\//.test(form.git_url.trim()) && hasCredentialInput.value,
)

async function handleTestConnection() {
  if (!canTest.value || testing.value)
    return

  testing.value = true

  try {
    const result = await repositoriesApi.testConnection({
      git_url: form.git_url,
      access_token: form.access_token,
      // TOKEN-02：无自有 token 时由后端按 FK / host 实例池 fallback 校验
      git_instance_credential_id: form.git_instance_credential_id || undefined,
      proxy_url: form.proxy_url || undefined,
    })
    testResult.value = result

    if (result.success) {
      errors.default_branch = ''
      // 自动选中 HEAD 所在分支（其次推荐分支）
      const auto = result.head_branch || result.recommended_branch
      if (auto && (!form.default_branch || !result.branches?.includes(form.default_branch)))
        form.default_branch = auto
      success('连接成功', result.branches?.length ? `发现 ${result.branches.length} 个分支，已自动选中 HEAD 分支` : '仓库可访问')
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

// 填完 URL + Token 后自动探测分支列表（防抖，无需手动点按钮）
watchDebounced(
  () => [form.git_url, form.access_token, form.git_instance_credential_id, form.proxy_url],
  () => {
    testResult.value = null
    form.default_branch = ''
    if (canTest.value)
      handleTestConnection()
  },
  { debounce: 800 },
)

// 提交表单
const submitting = ref(false)

async function handleSubmit() {
  if (!validate())
    return

  submitting.value = true
  try {
    const repository = await repositoriesStore.createRepository({
      ...form,
      // 空串归一为 undefined：后端 UUIDField 不接受空串（TOKEN-01）
      git_instance_credential_id: form.git_instance_credential_id || undefined,
      space_ids: spaceIds.value,
      remote_head_branch: testResult.value?.head_branch ?? undefined,
    })
    success('创建成功', '仓库已创建，正在自动建立知识')

    // best-effort 自动配置 Webhook：失败不阻塞建仓，仅提示到面板手动配置
    if (showWebhookOption.value && autoSetupWebhook.value) {
      try {
        const result = await repositoriesApi.setupWebhook(repository.id)
        success('Webhook 已自动配置', `GitLab push webhook 已${result.action === 'created' ? '创建' : '更新'}（分支：${result.branch_filter || '全部'}）`)
      }
      catch (e: unknown) {
        handleError(e, '自动配置 Webhook（可稍后在仓库详情的 Webhook 面板重试）')
      }
    }

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

      <!-- 仓库 URL + 平台 -->
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
              填写 Access Token 后会自动测试连接并获取远端分支
            </p>
          </div>
        </div>

        <!-- 凭证：密钥提供方（实例凭证）或自有 Access Token（TOKEN-01/02，二选一即可） -->
        <div class="space-y-4">
          <!-- 密钥提供方（实例凭证）下拉 -->
          <div v-if="instanceCredentials.length > 0" class="space-y-2">
            <Label for="git_instance_credential" class="text-foreground">
              密钥提供方（实例凭证，可选）
            </Label>
            <Select v-model="form.git_instance_credential_id">
              <SelectTrigger id="git_instance_credential" class="h-10 bg-card">
                <SelectValue placeholder="不指定（填自有 token 或按 host 自动匹配）" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">
                  不指定（填自有 token 或按 host 自动匹配）
                </SelectItem>
                <SelectItem v-for="ic in instanceCredentials" :key="ic.id" :value="ic.id">
                  {{ ic.label || ic.host }}（{{ ic.host }}）
                </SelectItem>
              </SelectContent>
            </Select>
            <p class="text-xs text-muted-foreground">
              选择已配置的实例凭证后，下方 Access Token 可留空；按 provider + host 生效。
            </p>
          </div>

          <div class="space-y-2">
            <Label for="access_token" class="flex items-center gap-1 text-foreground">
              Access Token
              <span class="text-muted-foreground text-xs font-normal">（可选）</span>
            </Label>
            <Input
              id="access_token"
              v-model="form.access_token"
              type="password"
              placeholder="ghp_xxxxxxxxxxxx 或 glpat-xxxxxxxxxxxx（留空则用密钥提供方）"
              class="h-10 bg-card"
              :class="{ 'border-destructive': errors.access_token }"
            />
            <p v-if="errors.access_token" class="text-sm text-destructive flex items-center gap-1">
              <span class="icon-[lucide--alert-circle]" />
              {{ errors.access_token }}
            </p>
            <p class="text-xs text-muted-foreground">
              需要仓库读写权限的个人访问令牌（PAT），加密存储；留空则使用所选密钥提供方或按 host 自动匹配。
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

          <!-- 连接状态 / 手动重试 -->
          <div class="flex items-center justify-between gap-3">
            <div
              class="flex items-center gap-2 text-sm min-w-0"
              :class="testing ? 'text-muted-foreground'
                : testResult?.success ? 'text-emerald-600'
                  : testResult ? 'text-red-600' : 'text-muted-foreground'"
            >
              <span
                class="shrink-0"
                :class="testing ? 'icon-[lucide--loader-circle] animate-spin'
                  : testResult?.success ? 'icon-[lucide--check-circle]'
                    : testResult ? 'icon-[lucide--x-circle]' : 'icon-[lucide--plug]'"
              />
              <span class="truncate">
                {{ testing ? '正在连接仓库获取分支列表...'
                  : testResult?.success ? `连接成功，发现 ${testResult.branches?.length ?? 0} 个分支`
                    : testResult ? (testResult.error || '连接失败') : '填写 URL 与 Token 后自动测试连接' }}
              </span>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              class="shrink-0"
              :disabled="testing || !canTest"
              @click="handleTestConnection"
            >
              <span v-if="testing" class="icon-[lucide--loader-circle] mr-1.5 animate-spin" />
              <span v-else class="icon-[lucide--refresh-cw] mr-1.5" />
              {{ testResult ? '重新测试' : '测试连接' }}
            </Button>
          </div>
        </div>
      </div>

      <!-- 默认分支（必选，来自远端分支列表） -->
      <div class="space-y-2">
        <Label class="flex items-center gap-1 text-foreground">
          默认分支（索引用）
          <span class="text-destructive">*</span>
        </Label>
        <BranchCombobox
          v-if="testResult?.success && testResult.branches?.length"
          v-model="form.default_branch"
          :branches="testResult.branches"
          :head-branch="testResult.head_branch"
          :recommended-branch="testResult.recommended_branch"
        />
        <div
          v-else
          class="flex items-center gap-2 h-10 px-3 rounded-lg border border-dashed border-border/70 bg-muted/20 text-sm text-muted-foreground"
        >
          <span :class="testing ? 'icon-[lucide--loader-circle] animate-spin' : 'icon-[lucide--git-branch]'" />
          {{ testing ? '正在获取分支列表...' : '测试连接成功后从远端分支中选择' }}
        </div>
        <p v-if="errors.default_branch" class="text-sm text-destructive flex items-center gap-1">
          <span class="icon-[lucide--alert-circle]" />
          {{ errors.default_branch }}
        </p>
        <p v-else class="text-xs text-muted-foreground">
          代码索引会使用这个分支，默认选中远端 HEAD 所在分支
        </p>

        <!-- 一键配置 Webhook（仅 GitLab，测连成功后可选） -->
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
              建仓后用该凭证自动在 GitLab 项目中创建 push webhook：默认分支变更时自动通知本服务更新索引（需要 token 为项目 Maintainer 及以上且具有 api scope）
            </span>
          </span>
        </label>
      </div>

      <!-- 关联空间（可选，可后期再绑定） -->
      <div class="space-y-2">
        <Label class="flex items-center gap-1 text-foreground">
          关联空间
          <span class="text-xs font-normal text-muted-foreground">（可选）</span>
        </Label>
        <SpaceMultiSelect v-model="spaceIds" />
        <p v-if="errors.spaces" class="text-sm text-destructive flex items-center gap-1">
          <span class="icon-[lucide--alert-circle]" />
          {{ errors.spaces }}
        </p>
        <p v-else class="text-xs text-muted-foreground">
          可暂不关联空间，先创建仓库；之后在仓库详情里随时绑定到空间
        </p>
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
