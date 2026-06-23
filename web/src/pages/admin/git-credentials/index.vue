<script setup lang="ts">
/**
 * /admin/git-credentials — 实例级 Git 凭证管理页（Plan 26-04，REPO-01）
 *
 * 路由：unplugin-vue-router 按文件系统注册 `/admin/git-credentials`。
 * 守卫：definePage({ meta: { requiresAdmin: true } }) —— 与其它 admin 子页一致，
 *       由全局导航守卫拦截非 superuser；后端 IsSuperUser 纵深防御。
 *
 * 安全（D-04 / 威胁 T-26-15）：列表仅展示 has_token 徽标，绝不渲染明文 token；
 * token 输入框为 password 型、不回填既有 token、提交后清空。
 */
import type {
  CreateGitInstanceCredentialPayload,
  GitInstanceCredential,
  GitInstanceProvider,
  UpdateGitInstanceCredentialPayload,
} from '~/api/gitInstanceCredentials'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiError } from '~/api/client'
import { gitInstanceCredentialsApi } from '~/api/gitInstanceCredentials'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

definePage({ meta: { requiresAdmin: true } })

const { t } = useI18n()
const { confirm } = useConfirmDialog()
const { handleError } = useErrorHandler()
const { success } = useToast()
const queryClient = useQueryClient()

const queryKey = ['git-instance-credentials'] as const
const { data, isLoading, isError } = useQuery({
  queryKey,
  queryFn: () => gitInstanceCredentialsApi.list(),
})
const credentials = computed(() => data.value ?? [])

function invalidate() {
  queryClient.invalidateQueries({ queryKey })
}

const providerOptions: GitInstanceProvider[] = ['gitlab', 'github', 'gitea', 'bitbucket']

/** 从后端错误中提取首条字段级错误（DRF `{field: [msg]}`），回退到 ApiError.detail。 */
function fieldError(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    const body = e.body as Record<string, unknown> | null
    if (body) {
      if (typeof body.detail === 'string')
        return body.detail
      for (const v of Object.values(body)) {
        if (Array.isArray(v) && typeof v[0] === 'string')
          return v[0]
        if (typeof v === 'string')
          return v
      }
    }
    return e.detail || fallback
  }
  return fallback
}

// ==================== 表单状态（新建 / 编辑共用） ====================
const showForm = ref(false)
const editingId = ref<string | null>(null)
const formHost = ref('')
const formProvider = ref<GitInstanceProvider>('gitlab')
const formLabel = ref('')
// token 输入：password 型，绝不回填既有 token（威胁 T-26-15）
const formToken = ref('')
const formError = ref<string | null>(null)

const isEditing = computed(() => editingId.value !== null)

function openCreate() {
  editingId.value = null
  formHost.value = ''
  formProvider.value = 'gitlab'
  formLabel.value = ''
  formToken.value = ''
  formError.value = null
  showForm.value = true
}

function openEdit(cred: GitInstanceCredential) {
  editingId.value = cred.id
  formHost.value = cred.host
  formProvider.value = cred.provider
  formLabel.value = cred.label
  // 绝不回填既有 token：编辑态 token 框初值为空，留空 = 不修改
  formToken.value = ''
  formError.value = null
  showForm.value = true
}

function closeForm() {
  showForm.value = false
  formToken.value = ''
}

const createMutation = useMutation({
  mutationFn: (payload: CreateGitInstanceCredentialPayload) =>
    gitInstanceCredentialsApi.create(payload),
})
const updateMutation = useMutation({
  mutationFn: (vars: { id: string, payload: UpdateGitInstanceCredentialPayload }) =>
    gitInstanceCredentialsApi.update(vars.id, vars.payload),
})

const saving = computed(
  () => createMutation.isPending.value || updateMutation.isPending.value,
)

async function submitForm() {
  formError.value = null
  const host = formHost.value.trim()
  if (!host) {
    formError.value = t('gitCredentials.validation.hostRequired')
    return
  }
  const token = formToken.value.trim()

  try {
    if (isEditing.value && editingId.value) {
      const payload: UpdateGitInstanceCredentialPayload = {
        host,
        provider: formProvider.value,
        label: formLabel.value.trim(),
      }
      // 仅当输入了 token 才提交，留空 = 保留既有 token
      if (token)
        payload.access_token = token
      await updateMutation.mutateAsync({ id: editingId.value, payload })
      success(t('gitCredentials.toast.updated'))
    }
    else {
      if (!token) {
        formError.value = t('gitCredentials.validation.tokenRequired')
        return
      }
      await createMutation.mutateAsync({
        host,
        provider: formProvider.value,
        label: formLabel.value.trim(),
        access_token: token,
      })
      success(t('gitCredentials.toast.created'))
    }
    // 提交后清空 token 输入，绝不回显
    formToken.value = ''
    closeForm()
    invalidate()
  }
  catch (e) {
    formError.value = fieldError(
      e,
      isEditing.value ? t('gitCredentials.error.update') : t('gitCredentials.error.create'),
    )
  }
}

const deleteMutation = useMutation({
  mutationFn: (id: string) => gitInstanceCredentialsApi.remove(id),
})

async function removeCredential(cred: GitInstanceCredential) {
  const ok = await confirm({
    title: t('gitCredentials.actions.deleteConfirmTitle'),
    description: t('gitCredentials.actions.deleteConfirmDescription'),
    confirmText: t('gitCredentials.actions.deleteConfirmText'),
    variant: 'destructive',
  })
  if (!ok)
    return
  try {
    await deleteMutation.mutateAsync(cred.id)
    success(t('gitCredentials.toast.deleted'))
    invalidate()
  }
  catch (e) {
    handleError(e, t('gitCredentials.error.delete'))
  }
}
</script>

<template>
  <PageContainer show-background>
    <div class="card overflow-hidden">
      <div class="flex items-center justify-between gap-3 p-6 border-b border-border/50">
        <div class="flex items-center gap-3 min-w-0">
          <div class="p-2.5 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
            <span class="icon-[lucide--key-round] text-2xl text-primary" />
          </div>
          <div class="min-w-0">
            <h2 class="text-lg font-semibold">
              {{ t('gitCredentials.title') }}
            </h2>
            <p class="text-sm text-muted-foreground">
              {{ t('gitCredentials.subtitle') }}
            </p>
          </div>
        </div>
        <Button class="shrink-0" @click="openCreate">
          <span class="icon-[lucide--plus]" />
          {{ t('gitCredentials.actions.create') }}
        </Button>
      </div>

      <div class="p-6 space-y-4">
        <!-- TOKEN-02：实例凭证「按 provider + host 生效」用途说明 -->
        <div class="flex items-start gap-2 p-3 rounded-lg border border-border/60 bg-muted/40 text-xs text-muted-foreground">
          <span class="icon-[lucide--info] mt-0.5 text-primary shrink-0" />
          <span>
            实例凭证按 <b>provider + host</b> 生效：同一 Git 实例（host）下的多个仓库可复用一份凭证。
            建仓时可不填自有 Access Token，改选「密钥提供方」(实例凭证)，或由系统按仓库 URL 的 host 自动匹配此处配置的凭证。
            解析优先级：仓库自有 token → 仓库指定的密钥提供方 → host 自动匹配 → 无。
          </span>
        </div>

        <!-- 新建 / 编辑表单 -->
        <div v-if="showForm" class="p-4 rounded-xl border border-primary/20 bg-primary/5 space-y-4">
          <h3 class="text-sm font-semibold">
            {{ isEditing ? t('gitCredentials.form.editTitle') : t('gitCredentials.form.createTitle') }}
          </h3>
          <div class="grid gap-4 sm:grid-cols-2">
            <div>
              <Label for="gic-host" class="text-xs text-muted-foreground mb-1.5 block">
                {{ t('gitCredentials.form.host') }}
              </Label>
              <Input
                id="gic-host"
                v-model="formHost"
                :placeholder="t('gitCredentials.form.hostPlaceholder')"
                class="bg-background/50"
              />
              <p class="text-[11px] text-muted-foreground mt-1">
                {{ t('gitCredentials.form.hostHint') }}
              </p>
            </div>
            <div>
              <Label for="gic-provider" class="text-xs text-muted-foreground mb-1.5 block">
                {{ t('gitCredentials.form.provider') }}
              </Label>
              <select
                id="gic-provider"
                v-model="formProvider"
                class="h-9 w-full rounded-lg border border-border/50 bg-background px-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option v-for="p in providerOptions" :key="p" :value="p">
                  {{ p }}
                </option>
              </select>
            </div>
            <div>
              <Label for="gic-label" class="text-xs text-muted-foreground mb-1.5 block">
                {{ t('gitCredentials.form.label') }}
              </Label>
              <Input
                id="gic-label"
                v-model="formLabel"
                :placeholder="t('gitCredentials.form.labelPlaceholder')"
                class="bg-background/50"
              />
            </div>
            <div>
              <Label for="gic-token" class="text-xs text-muted-foreground mb-1.5 block">
                {{ t('gitCredentials.form.accessToken') }}
              </Label>
              <Input
                id="gic-token"
                v-model="formToken"
                type="password"
                autocomplete="new-password"
                :placeholder="isEditing
                  ? t('gitCredentials.form.accessTokenPlaceholderEdit')
                  : t('gitCredentials.form.accessTokenPlaceholderCreate')"
                class="bg-background/50"
              />
              <p class="text-[11px] text-muted-foreground mt-1">
                {{ t('gitCredentials.form.accessTokenHint') }}
              </p>
            </div>
          </div>

          <p v-if="formError" class="text-xs text-destructive flex items-center gap-1">
            <span class="icon-[lucide--alert-circle]" />
            {{ formError }}
          </p>

          <div class="flex items-center gap-2">
            <Button :disabled="saving" @click="submitForm">
              <span v-if="saving" class="icon-[lucide--loader-2] animate-spin" />
              {{ saving ? t('gitCredentials.actions.saving') : t('gitCredentials.actions.save') }}
            </Button>
            <Button variant="ghost" :disabled="saving" @click="closeForm">
              {{ t('gitCredentials.actions.cancel') }}
            </Button>
          </div>
        </div>

        <!-- 状态 -->
        <div v-if="isLoading" class="text-sm text-muted-foreground">
          <span class="icon-[lucide--loader-2] animate-spin mr-1.5" />
          {{ t('gitCredentials.loading') }}
        </div>
        <div v-else-if="isError" class="text-sm text-destructive">
          {{ t('gitCredentials.loadError') }}
        </div>
        <div v-else-if="credentials.length === 0" class="text-sm text-muted-foreground py-8 text-center">
          {{ t('gitCredentials.empty') }}
        </div>

        <!-- 列表 -->
        <table v-else class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs text-muted-foreground border-b border-border/50">
              <th class="py-2 pr-3 font-medium">
                {{ t('gitCredentials.columns.host') }}
              </th>
              <th class="py-2 pr-3 font-medium">
                {{ t('gitCredentials.columns.provider') }}
              </th>
              <th class="py-2 pr-3 font-medium">
                {{ t('gitCredentials.columns.label') }}
              </th>
              <th class="py-2 pr-3 font-medium">
                {{ t('gitCredentials.columns.token') }}
              </th>
              <th class="py-2 pr-3 font-medium text-right">
                {{ t('gitCredentials.columns.actions') }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="cred in credentials"
              :key="cred.id"
              class="border-b border-border/30 last:border-0"
            >
              <td class="py-2.5 pr-3 font-mono text-xs">
                {{ cred.host }}
              </td>
              <td class="py-2.5 pr-3">
                <Badge variant="outline" class="text-xs">
                  {{ cred.provider }}
                </Badge>
              </td>
              <td class="py-2.5 pr-3 text-muted-foreground">
                {{ cred.label || '—' }}
              </td>
              <td class="py-2.5 pr-3">
                <Badge
                  :variant="cred.has_token ? 'default' : 'destructive'"
                  class="text-xs"
                >
                  {{ cred.has_token ? t('gitCredentials.tokenConfigured') : t('gitCredentials.tokenMissing') }}
                </Badge>
              </td>
              <td class="py-2.5 pr-3">
                <div class="flex items-center justify-end gap-1">
                  <Button variant="ghost" size="sm" @click="openEdit(cred)">
                    <span class="icon-[lucide--pencil]" />
                    {{ t('gitCredentials.actions.edit') }}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="text-destructive hover:text-destructive"
                    @click="removeCredential(cred)"
                  >
                    <span class="icon-[lucide--trash-2]" />
                    {{ t('gitCredentials.actions.delete') }}
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </PageContainer>
</template>
