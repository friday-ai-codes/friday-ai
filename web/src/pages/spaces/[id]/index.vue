<script setup lang="ts">
import type { NavSection } from '~/components/layout/AnchorNavLayout.vue'
import { useClipboard } from '@vueuse/core'
import { useHead } from '@vueuse/head'
import { computed, markRaw } from 'vue'
import { refreshWebhookToken, updateWebhookToken } from '~/api/spaces'
import StatusBadge from '~/components/common/StatusBadge.vue'
import AnchorNavLayout from '~/components/layout/AnchorNavLayout.vue'
import BaseModal from '~/components/modal/BaseModal.vue'
import EditSpaceModal from '~/components/space/EditSpaceModal.vue'
import FeishuConfigModal from '~/components/space/FeishuConfigModal.vue'
import SpaceMembersModal from '~/components/space/SpaceMembersModal.vue'
import SpacePromptsModal from '~/components/space/SpacePromptsModal.vue'
import SpaceProvidersModal from '~/components/space/SpaceProvidersModal.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { usePermission } from '~/composables/usePermission'
import { PLATFORM_LABELS } from '~/types'

const route = useRoute('/spaces/[id]/')
const router = useRouter()
const spacesStore = useSpacesStore()
const repositoriesStore = useRepositoriesStore()
const executionsStore = useExecutionsStore()
const { handleError } = useErrorHandler()
const { success } = useToast()
const { copy } = useClipboard()

const spaceId = computed(() => route.params.id)

// 权限：删除空间仅系统管理员（#10）；编辑/配置为空间管理员（#11）。
const { isSystemAdmin, isSpaceAdmin } = usePermission(spaceId)

useHead({
  title: computed(() => spacesStore.currentSpace?.name
    ? `${spacesStore.currentSpace.name} - Friday AI`
    : '空间详情 - Friday AI'),
})

// 加载空间和相关任务
const loading = ref(true)

onMounted(async () => {
  try {
    const results = await Promise.allSettled([
      spacesStore.fetchSpace(spaceId.value),
      spacesStore.fetchFeishuConfig(spaceId.value),
      executionsStore.fetchExecutions(undefined, spaceId.value),
      repositoriesStore.fetchRepositories(),
    ])

    const names = ['空间信息', '飞书配置', '执行记录', '仓库列表']
    results.forEach((result, index) => {
      if (result.status === 'rejected') {
        handleError(result.reason, `加载${names[index]}`)
      }
    })
  }
  finally {
    loading.value = false
  }

  // 旧子页面 URL 重定向过来时自动打开对应弹窗
  if (route.hash === '#feishu')
    feishuModalOpen.value = true
  else if (route.hash === '#edit')
    openEditSpace()
  else if (route.hash === '#prompts')
    promptsModalOpen.value = true
  else if (route.hash === '#providers')
    providersModalOpen.value = true
  else if (route.hash === '#members')
    membersModalOpen.value = true
})

// 编辑空间弹窗
async function openEditSpace() {
  const { open } = useModal({
    component: markRaw(EditSpaceModal),
    attrs: { spaceId: spaceId.value },
    onConfirm: async () => {
      await spacesStore.fetchSpace(spaceId.value)
    },
  })
  await open()
}

// 飞书配置弹窗
const feishuModalOpen = ref(false)

// Prompt 覆盖 / Provider 凭证 / 成员管理弹窗（原独立子页面已降级为弹窗）
const promptsModalOpen = ref(false)
const providersModalOpen = ref(false)
const membersModalOpen = ref(false)

async function handleFeishuUpdated() {
  try {
    await spacesStore.fetchFeishuConfig(spaceId.value)
  }
  catch {
    // 忽略刷新失败
  }
}

// 飞书弹窗内点击「去设置」飞书项目 Key → 切换到编辑空间弹窗
function handleEditSpaceFromFeishu() {
  feishuModalOpen.value = false
  openEditSpace()
}

// 删除空间
const deleteDialogOpen = ref(false)
const deleting = ref(false)

async function handleDelete() {
  deleting.value = true
  try {
    await spacesStore.deleteSpace(spaceId.value)
    success('删除成功', '空间已删除')
    router.push('/spaces')
  }
  catch (e: unknown) {
    handleError(e, '删除空间')
  }
  finally {
    deleting.value = false
    deleteDialogOpen.value = false
  }
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleString('zh-CN')
}

const space = computed(() => spacesStore.currentSpace)
const feishuConfig = computed(() => spacesStore.currentFeishuConfig)
const spaceExecutions = computed(() => executionsStore.executions)

const repoCount = computed(() => space.value?.repositories?.length ?? 0)
const executionTotal = computed(() => space.value?.execution_count ?? spaceExecutions.value.length ?? 0)
const feishuConfigured = computed(() => Boolean(feishuConfig.value?.is_configured))
const hasToken = computed(() => Boolean(space.value?.webhook_token))
const hasFullConfig = computed(() => feishuConfigured.value && repoCount.value > 0)

const sections = computed<NavSection[]>(() => [
  { id: 'basic-info', label: '基本信息', icon: 'icon-[lucide--info]' },
  {
    id: 'repositories',
    label: '关联仓库',
    icon: 'icon-[lucide--git-branch]',
    badge: repoCount.value || undefined,
    badgeTone: repoCount.value > 0 ? 'primary' : 'muted',
  },
  {
    id: 'feishu',
    label: '飞书配置',
    icon: 'icon-[lucide--message-square]',
    badge: feishuConfigured.value ? '✓' : '!',
    badgeTone: feishuConfigured.value ? 'success' : 'warning',
  },
  { id: 'prompts', label: 'Prompt 覆盖', icon: 'icon-[lucide--file-text]' },
  { id: 'providers', label: 'Provider 凭证', icon: 'icon-[lucide--key-round]' },
  { id: 'members', label: '成员管理', icon: 'icon-[lucide--users]' },
  {
    id: 'webhook-token',
    label: 'Webhook Token',
    icon: 'icon-[lucide--key]',
    badge: hasToken.value ? '✓' : undefined,
    badgeTone: 'success',
  },
  {
    id: 'executions',
    label: '相关执行',
    icon: 'icon-[lucide--layers]',
    badge: spaceExecutions.value.length || undefined,
    badgeTone: 'primary',
  },
  // 危险操作（删除空间）仅系统管理员可见（#10）。
  ...(isSystemAdmin.value ? [{ id: 'danger-zone', label: '危险操作', icon: 'icon-[lucide--alert-triangle]' }] : []),
])

// 关联仓库 - 穿梭框模式
const linkDialogOpen = ref(false)
const selectedToLink = ref<Set<string>>(new Set())
const selectedToUnlink = ref<Set<string>>(new Set())
const linking = ref(false)

const availableRepositories = computed(() => {
  if (!space.value)
    return []
  const linkedIds = space.value.repositories?.map(r => r.id) ?? []
  return repositoriesStore.repositories.filter(r => !linkedIds.includes(r.id))
})

const linkedRepositories = computed(() => {
  return space.value?.repositories ?? []
})

function toggleSelectToLink(id: string) {
  if (selectedToLink.value.has(id)) {
    selectedToLink.value.delete(id)
  }
  else {
    selectedToLink.value.add(id)
  }
}

function toggleSelectToUnlink(id: string) {
  if (selectedToUnlink.value.has(id)) {
    selectedToUnlink.value.delete(id)
  }
  else {
    selectedToUnlink.value.add(id)
  }
}

function selectAllAvailable() {
  availableRepositories.value.forEach(r => selectedToLink.value.add(r.id))
}

function clearSelectToLink() {
  selectedToLink.value.clear()
}

function selectAllLinked() {
  linkedRepositories.value.forEach(r => selectedToUnlink.value.add(r.id))
}

function clearSelectToUnlink() {
  selectedToUnlink.value.clear()
}

async function handleLinkSelected() {
  if (selectedToLink.value.size === 0)
    return
  linking.value = true
  try {
    const promises = Array.from(selectedToLink.value).map(id =>
      spacesStore.addRepository(spaceId.value, id),
    )
    await Promise.all(promises)
    success('关联成功', `已关联 ${selectedToLink.value.size} 个仓库`)
    selectedToLink.value.clear()
  }
  catch (e: unknown) {
    handleError(e, '关联仓库')
  }
  finally {
    linking.value = false
  }
}

async function handleUnlinkSelected() {
  if (selectedToUnlink.value.size === 0)
    return
  linking.value = true
  try {
    const promises = Array.from(selectedToUnlink.value).map(id =>
      spacesStore.removeRepository(spaceId.value, id),
    )
    await Promise.all(promises)
    success('解除关联成功', `已解除 ${selectedToUnlink.value.size} 个仓库`)
    selectedToUnlink.value.clear()
  }
  catch (e: unknown) {
    handleError(e, '解除关联')
  }
  finally {
    linking.value = false
  }
}

function openLinkDialog() {
  selectedToLink.value.clear()
  selectedToUnlink.value.clear()
  linkDialogOpen.value = true
}

// Webhook Token 管理
async function copyWebhookToken() {
  if (!space.value?.webhook_token)
    return
  await copy(space.value.webhook_token)
  success('已复制', 'Webhook Token 已复制到剪贴板')
}

async function copySpaceId() {
  if (!space.value)
    return
  await copy(space.value.id)
  success('已复制', '空间 ID 已复制到剪贴板')
}

function scrollToSection(id: string) {
  const el = document.getElementById(id)
  if (!el)
    return
  const offset = 88
  const top = el.getBoundingClientRect().top + window.scrollY - offset
  window.scrollTo({ top, behavior: 'smooth' })
}

const refreshTokenDialogOpen = ref(false)
const refreshingToken = ref(false)

async function handleRefreshToken() {
  refreshingToken.value = true
  try {
    await refreshWebhookToken(spaceId.value)
    await spacesStore.fetchSpace(spaceId.value)
    success('刷新成功', '已生成新的 Webhook Token')
    refreshTokenDialogOpen.value = false
  }
  catch (e: unknown) {
    handleError(e, '刷新 Token')
  }
  finally {
    refreshingToken.value = false
  }
}

const customTokenDialogOpen = ref(false)
const customTokenValue = ref('')
const customTokenLoading = ref(false)

function openCustomTokenDialog() {
  customTokenValue.value = space.value?.webhook_token || ''
  customTokenDialogOpen.value = true
}

async function handleCustomToken() {
  if (!customTokenValue.value.trim()) {
    handleError(new Error('Token 不能为空'), '验证')
    return
  }
  if (customTokenValue.value.length > 32) {
    handleError(new Error('Token 长度不能超过 32 个字符'), '验证')
    return
  }

  customTokenLoading.value = true
  try {
    await updateWebhookToken(spaceId.value, { token: customTokenValue.value })
    await spacesStore.fetchSpace(spaceId.value)
    success('保存成功', 'Webhook Token 已更新')
    customTokenDialogOpen.value = false
  }
  catch (e: unknown) {
    handleError(e, '更新 Token')
  }
  finally {
    customTokenLoading.value = false
  }
}
</script>

<template>
  <div>
    <!-- 加载状态 -->
    <LoadingState v-if="loading" variant="skeleton" :count="4" />

    <!-- 空间不存在 -->
    <EmptyState
      v-else-if="!space"
      icon="lucide--help-circle"
      title="空间不存在"
      description="未找到该空间，可能已被删除"
      action-label="返回列表"
      gradient="from-primary/20 to-primary/20"
      @action="router.push('/spaces')"
    />

    <!-- 空间详情 -->
    <div v-else class="space-y-6">
      <!-- 面包屑 -->
      <RouterLink
        to="/spaces"
        class="group inline-flex items-center text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <span class="icon-[lucide--arrow-left] mr-1.5 group-hover:-translate-x-0.5 transition-transform" />
        空间列表
      </RouterLink>

      <!-- Hero 区 -->
      <div class="card overflow-hidden">
        <div class="relative px-6 py-5 sm:px-7 sm:py-6">
          <!-- 装饰背景（极淡 primary tint） -->
          <div class="absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-primary/5 to-transparent pointer-events-none" />
          <div class="absolute -top-20 -right-12 h-60 w-60 rounded-full bg-primary/5 blur-3xl pointer-events-none" />
          <div class="relative flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div class="flex items-start gap-4 min-w-0 flex-1">
              <div class="shrink-0 p-3 rounded-2xl bg-primary/10 ring-1 ring-primary/15">
                <span class="icon-[lucide--folder-open] text-3xl text-primary" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 flex-wrap">
                  <h1 class="text-2xl font-bold text-foreground truncate">
                    {{ space.name }}
                  </h1>
                  <Badge :variant="hasFullConfig ? 'success' : 'warning'" class="shrink-0 gap-1">
                    <span :class="hasFullConfig ? 'icon-[lucide--circle-check] text-[12px]' : 'icon-[lucide--loader-circle] text-[12px]'" />
                    {{ hasFullConfig ? '已就绪' : '配置中' }}
                  </Badge>
                </div>
                <p v-if="space.description" class="text-sm text-muted-foreground mt-1.5">
                  {{ space.description }}
                </p>
                <!-- 元数据行 -->
                <div class="flex items-center gap-x-5 gap-y-1.5 mt-3 text-xs text-muted-foreground flex-wrap">
                  <button
                    class="group/copy flex items-center gap-1.5 hover:text-primary transition-colors"
                    @click="copySpaceId"
                  >
                    <span class="icon-[lucide--fingerprint] opacity-60 group-hover/copy:opacity-100" />
                    <code class="font-mono">{{ space.id.slice(0, 8) }}</code>
                    <span class="icon-[lucide--copy] text-[11px] opacity-0 group-hover/copy:opacity-100 transition-opacity" />
                  </button>
                  <span v-if="space.admins?.length" class="flex items-center gap-1.5" :title="`空间管理员：${space.admins.map(a => a.display_name).join('、')}`">
                    <span class="icon-[lucide--shield-user] opacity-60" />
                    管理员 {{ space.admins.map(a => a.display_name).join('、') }}
                  </span>
                  <span class="flex items-center gap-1.5">
                    <span class="icon-[lucide--calendar-plus] opacity-60" />
                    创建于 {{ formatDate(space.created_at) }}
                  </span>
                  <span class="flex items-center gap-1.5">
                    <span class="icon-[lucide--calendar-clock] opacity-60" />
                    更新于 {{ formatDate(space.updated_at) }}
                  </span>
                </div>
              </div>
            </div>
            <div v-if="isSpaceAdmin" class="flex items-center gap-2 shrink-0 sm:self-start">
              <Button variant="outline" size="sm" class="group" @click="openEditSpace">
                <span class="icon-[lucide--pencil] mr-1.5 group-hover:scale-110 transition-transform" />
                编辑
              </Button>
            </div>
          </div>
        </div>
      </div>

      <!-- KPI 概览 -->
      <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <button
          type="button"
          class="card text-left p-4 hover:shadow-card-hover hover:-translate-y-0.5 transition-all group"
          @click="scrollToSection('repositories')"
        >
          <div class="flex items-start justify-between">
            <div class="p-2 rounded-lg bg-primary/10">
              <span class="icon-[lucide--git-branch] text-base text-primary" />
            </div>
            <span class="icon-[lucide--arrow-up-right] text-muted-foreground/40 group-hover:text-primary group-hover:-translate-y-0.5 group-hover:translate-x-0.5 transition-all" />
          </div>
          <div class="mt-3">
            <div class="text-2xl font-bold text-foreground tabular-nums leading-none">
              {{ repoCount }}
            </div>
            <div class="text-xs text-muted-foreground mt-1.5">
              关联仓库
            </div>
          </div>
        </button>
        <button
          type="button"
          class="card text-left p-4 hover:shadow-card-hover hover:-translate-y-0.5 transition-all group"
          @click="scrollToSection('executions')"
        >
          <div class="flex items-start justify-between">
            <div class="p-2 rounded-lg bg-primary/10">
              <span class="icon-[lucide--layers] text-base text-primary" />
            </div>
            <span class="icon-[lucide--arrow-up-right] text-muted-foreground/40 group-hover:text-primary group-hover:-translate-y-0.5 group-hover:translate-x-0.5 transition-all" />
          </div>
          <div class="mt-3">
            <div class="text-2xl font-bold text-foreground tabular-nums leading-none">
              {{ executionTotal }}
            </div>
            <div class="text-xs text-muted-foreground mt-1.5">
              累计执行
            </div>
          </div>
        </button>
        <button
          type="button"
          class="card text-left p-4 hover:shadow-card-hover hover:-translate-y-0.5 transition-all group"
          @click="scrollToSection('feishu')"
        >
          <div class="flex items-start justify-between">
            <div class="p-2 rounded-lg bg-primary/10">
              <span class="icon-[lucide--message-square] text-base text-primary" />
            </div>
            <span
              class="h-2 w-2 rounded-full"
              :class="feishuConfigured
                ? 'bg-emerald-500 ring-4 ring-emerald-500/15'
                : 'bg-amber-500 ring-4 ring-amber-500/15'"
            />
          </div>
          <div class="mt-3">
            <div class="text-base font-semibold text-foreground">
              {{ feishuConfigured ? '已配置' : '未配置' }}
            </div>
            <div class="text-xs text-muted-foreground mt-1">
              飞书集成
            </div>
          </div>
        </button>
        <button
          type="button"
          class="card text-left p-4 hover:shadow-card-hover hover:-translate-y-0.5 transition-all group"
          @click="scrollToSection('webhook-token')"
        >
          <div class="flex items-start justify-between">
            <div class="p-2 rounded-lg bg-primary/10">
              <span class="icon-[lucide--key] text-base text-primary" />
            </div>
            <span
              class="h-2 w-2 rounded-full"
              :class="hasToken
                ? 'bg-emerald-500 ring-4 ring-emerald-500/15'
                : 'bg-muted-foreground/30 ring-4 ring-muted-foreground/10'"
            />
          </div>
          <div class="mt-3">
            <div class="text-base font-semibold text-foreground">
              {{ hasToken ? '已生成' : '未配置' }}
            </div>
            <div class="text-xs text-muted-foreground mt-1">
              Webhook Token
            </div>
          </div>
        </button>
      </div>

      <AnchorNavLayout :sections="sections">
        <!-- 基本信息 -->
        <section id="basic-info" class="scroll-mt-22">
          <div class="card">
            <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
              <span class="icon-[lucide--info] text-primary" />
              <h3 class="text-sm font-semibold">
                基本信息
              </h3>
            </div>
            <div class="p-5">
              <dl class="grid gap-x-8 gap-y-4 sm:grid-cols-2">
                <div class="space-y-1">
                  <dt class="text-xs text-muted-foreground">
                    飞书项目 Key
                  </dt>
                  <dd class="font-mono text-sm">
                    <span v-if="space.feishu_project_key" class="text-foreground">{{ space.feishu_project_key }}</span>
                    <span v-else class="text-muted-foreground italic">未配置</span>
                  </dd>
                </div>
                <div class="space-y-1">
                  <dt class="text-xs text-muted-foreground">
                    空间 ID
                  </dt>
                  <dd class="group flex items-center gap-2 font-mono text-xs text-foreground">
                    <span class="truncate">{{ space.id }}</span>
                    <button
                      class="shrink-0 opacity-50 hover:opacity-100 hover:text-primary transition-all"
                      @click="copySpaceId"
                    >
                      <span class="icon-[lucide--copy]" />
                    </button>
                  </dd>
                </div>
                <div class="space-y-1">
                  <dt class="text-xs text-muted-foreground">
                    创建时间
                  </dt>
                  <dd class="text-sm text-foreground">
                    {{ formatDate(space.created_at) }}
                  </dd>
                </div>
                <div class="space-y-1">
                  <dt class="text-xs text-muted-foreground">
                    更新时间
                  </dt>
                  <dd class="text-sm text-foreground">
                    {{ formatDate(space.updated_at) }}
                  </dd>
                </div>
              </dl>
            </div>
          </div>
        </section>

        <!-- 关联仓库 -->
        <section id="repositories" class="scroll-mt-22">
          <div class="card">
            <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="icon-[lucide--git-branch] text-primary" />
                <h3 class="text-sm font-semibold">
                  关联仓库
                </h3>
                <Badge variant="secondary" class="h-5 px-1.5 text-[10px]">
                  {{ repoCount }}
                </Badge>
              </div>
              <Button variant="outline" size="sm" class="h-8" @click="openLinkDialog">
                <span class="icon-[lucide--settings-2] mr-1.5" />
                管理
              </Button>
            </div>
            <div class="p-5">
              <div v-if="repoCount === 0" class="text-center py-8 space-y-3">
                <div class="inline-flex p-3 rounded-2xl bg-muted/50">
                  <span class="icon-[lucide--git-branch] text-2xl text-muted-foreground/60" />
                </div>
                <div>
                  <p class="text-sm font-medium text-foreground">
                    还没有关联仓库
                  </p>
                  <p class="text-xs text-muted-foreground mt-1">
                    关联仓库后才能在此空间内运行 Git 工作流
                  </p>
                </div>
                <div>
                  <Button variant="outline" size="sm" @click="openLinkDialog">
                    <span class="icon-[lucide--plus] mr-1.5" />
                    关联仓库
                  </Button>
                </div>
              </div>
              <div v-else class="grid gap-2 sm:grid-cols-2">
                <div
                  v-for="repo in space.repositories"
                  :key="repo.id"
                  class="group flex items-center gap-3 p-3 rounded-xl border border-border/50 hover:border-primary/30 hover:bg-primary/[0.03] transition-all"
                >
                  <div class="shrink-0 p-2 rounded-lg bg-primary/10">
                    <span class="icon-[lucide--git-branch] text-sm text-primary" />
                  </div>
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2">
                      <span class="text-sm font-medium text-foreground truncate">{{ repo.name }}</span>
                      <Badge variant="outline" class="h-4 px-1.5 text-[10px] shrink-0">
                        {{ PLATFORM_LABELS[repo.git_platform] }}
                      </Badge>
                    </div>
                    <p class="text-xs text-muted-foreground mt-0.5 font-mono truncate">
                      {{ repo.git_url }}
                    </p>
                  </div>
                  <RouterLink :to="`/repositories/${repo.id}`" class="shrink-0">
                    <TooltipProvider :delay-duration="300">
                      <Tooltip>
                        <TooltipTrigger as-child>
                          <Button
                            variant="ghost"
                            size="icon"
                            class="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity"
                          >
                            <span class="icon-[lucide--external-link] text-sm" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>查看仓库</TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </RouterLink>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- 飞书配置 -->
        <section id="feishu" class="scroll-mt-22">
          <div class="card">
            <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="icon-[lucide--message-square] text-primary" />
                <h3 class="text-sm font-semibold">
                  飞书配置
                </h3>
              </div>
              <Button variant="ghost" size="sm" class="h-8 text-xs group" @click="feishuModalOpen = true">
                管理
                <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
              </Button>
            </div>
            <div class="p-5">
              <div v-if="feishuConfigured" class="flex items-center justify-between gap-4">
                <div class="flex items-center gap-3 min-w-0 flex-1">
                  <div class="shrink-0 p-2 rounded-xl bg-emerald-500/10">
                    <span class="icon-[lucide--check] text-lg text-emerald-500" />
                  </div>
                  <div class="min-w-0">
                    <p class="text-sm font-medium text-foreground">
                      已连接到飞书
                    </p>
                    <p class="text-xs text-muted-foreground mt-0.5 truncate">
                      插件 ID：<code class="font-mono">{{ feishuConfig?.plugin_id }}</code>
                    </p>
                  </div>
                </div>
                <Badge variant="success" class="shrink-0">
                  运行中
                </Badge>
              </div>
              <div v-else class="flex items-center justify-between gap-4">
                <div class="flex items-center gap-3 min-w-0 flex-1">
                  <div class="shrink-0 p-2 rounded-xl bg-amber-500/10">
                    <span class="icon-[lucide--link] text-lg text-amber-500" />
                  </div>
                  <div class="min-w-0">
                    <p class="text-sm font-medium text-foreground">
                      尚未配置飞书集成
                    </p>
                    <p class="text-xs text-muted-foreground mt-0.5">
                      配置后空间可接收并响应飞书事件
                    </p>
                  </div>
                </div>
                <Button size="sm" class="shrink-0" @click="feishuModalOpen = true">
                  <span class="icon-[lucide--plug] mr-1.5" />
                  立即配置
                </Button>
              </div>
            </div>
          </div>
        </section>

        <!-- Prompt 覆盖 -->
        <section id="prompts" class="scroll-mt-22">
          <div class="card">
            <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="icon-[lucide--file-text] text-primary" />
                <h3 class="text-sm font-semibold">
                  Prompt 覆盖
                </h3>
              </div>
              <Button variant="ghost" size="sm" class="h-8 text-xs group" @click="promptsModalOpen = true">
                管理
                <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
              </Button>
            </div>
            <div class="p-5">
              <div class="flex items-center gap-3">
                <div class="shrink-0 p-2 rounded-xl bg-primary/10">
                  <span class="icon-[lucide--file-text] text-lg text-primary" />
                </div>
                <div class="min-w-0 flex-1">
                  <p class="text-sm font-medium text-foreground">
                    空间级提示词覆盖
                  </p>
                  <p class="text-xs text-muted-foreground mt-0.5">
                    未覆盖的提示词将 fallback 至系统级
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- Provider 凭证 -->
        <section id="providers" class="scroll-mt-22">
          <div class="card">
            <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="icon-[lucide--key-round] text-primary" />
                <h3 class="text-sm font-semibold">
                  Provider 凭证
                </h3>
              </div>
              <Button variant="ghost" size="sm" class="h-8 text-xs group" @click="providersModalOpen = true">
                管理
                <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
              </Button>
            </div>
            <div class="p-5">
              <div class="flex items-center gap-3">
                <div class="shrink-0 p-2 rounded-xl bg-primary/10">
                  <span class="icon-[lucide--key-round] text-lg text-primary" />
                </div>
                <div class="min-w-0 flex-1">
                  <p class="text-sm font-medium text-foreground">
                    空间级 Provider 凭证
                  </p>
                  <p class="text-xs text-muted-foreground mt-0.5">
                    仅本空间可见，覆盖系统默认凭证
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- 成员管理 -->
        <section id="members" class="scroll-mt-22">
          <div class="card">
            <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="icon-[lucide--users] text-primary" />
                <h3 class="text-sm font-semibold">
                  成员管理
                </h3>
              </div>
              <Button variant="ghost" size="sm" class="h-8 text-xs group" @click="membersModalOpen = true">
                管理
                <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
              </Button>
            </div>
            <div class="p-5">
              <div class="flex items-center gap-3">
                <div class="shrink-0 p-2 rounded-xl bg-primary/10">
                  <span class="icon-[lucide--users] text-lg text-primary" />
                </div>
                <div class="min-w-0 flex-1">
                  <p class="text-sm font-medium text-foreground">
                    空间成员与角色
                  </p>
                  <p class="text-xs text-muted-foreground mt-0.5">
                    管理成员的访问权限：管理员 / 成员 / 观察者
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- Webhook Token -->
        <section id="webhook-token" class="scroll-mt-22">
          <div class="card">
            <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
              <span class="icon-[lucide--key] text-primary" />
              <h3 class="text-sm font-semibold">
                Webhook Token
              </h3>
              <span class="text-xs text-muted-foreground">用于验证飞书 Webhook 请求来源</span>
            </div>
            <div class="p-5 space-y-4">
              <div class="space-y-2">
                <Label class="text-xs text-muted-foreground">当前 Token</Label>
                <div class="flex items-center gap-2 p-2.5 pl-3 rounded-xl border border-border/50 bg-muted/30 hover:border-primary/30 transition-colors">
                  <span class="icon-[lucide--key] text-primary/60 shrink-0" />
                  <code class="flex-1 font-mono text-sm text-foreground truncate">{{ space.webhook_token }}</code>
                  <TooltipProvider :delay-duration="300">
                    <Tooltip>
                      <TooltipTrigger as-child>
                        <Button
                          variant="ghost"
                          size="icon"
                          class="h-7 w-7 shrink-0"
                          @click="copyWebhookToken"
                        >
                          <span class="icon-[lucide--copy]" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>复制 Token</TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
              </div>

              <div class="flex items-start gap-2.5 p-3 rounded-xl bg-amber-500/[0.08] border border-amber-500/20">
                <span class="icon-[lucide--shield-alert] text-amber-500 shrink-0 mt-0.5" />
                <div class="text-xs leading-relaxed text-amber-700 dark:text-amber-300">
                  <p class="font-medium">
                    请勿泄露此 Token
                  </p>
                  <p class="opacity-80 mt-0.5">
                    如果 Token 已泄露，请立即点击"刷新 Token"重新生成。
                  </p>
                </div>
              </div>

              <div class="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" @click="refreshTokenDialogOpen = true">
                  <span class="icon-[lucide--refresh-cw] mr-1.5" />
                  刷新 Token
                </Button>
                <Button variant="outline" size="sm" @click="openCustomTokenDialog">
                  <span class="icon-[lucide--pencil-line] mr-1.5" />
                  自定义 Token
                </Button>
              </div>
            </div>
          </div>
        </section>

        <!-- 相关执行 -->
        <section id="executions" class="scroll-mt-22">
          <div class="card">
            <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="icon-[lucide--layers] text-primary" />
                <h3 class="text-sm font-semibold">
                  相关执行
                </h3>
                <Badge variant="secondary" class="h-5 px-1.5 text-[10px]">
                  {{ spaceExecutions.length }}
                </Badge>
              </div>
              <RouterLink :to="`/executions?space_id=${space.id}`">
                <Button variant="ghost" size="sm" class="h-8 text-xs group">
                  查看全部
                  <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
                </Button>
              </RouterLink>
            </div>
            <div class="p-5">
              <div v-if="spaceExecutions.length === 0" class="text-center py-8 space-y-3">
                <div class="inline-flex p-3 rounded-2xl bg-muted/50">
                  <span class="icon-[lucide--inbox] text-2xl text-muted-foreground/60" />
                </div>
                <div>
                  <p class="text-sm font-medium text-foreground">
                    暂无执行记录
                  </p>
                  <p class="text-xs text-muted-foreground mt-1">
                    在飞书或工作流中触发后会显示在这里
                  </p>
                </div>
              </div>
              <div v-else class="space-y-1">
                <RouterLink
                  v-for="(execution, index) in spaceExecutions.slice(0, 5)"
                  :key="execution.id"
                  :to="`/executions/${execution.id}`"
                  class="group flex items-center justify-between gap-3 p-3 rounded-lg hover:bg-muted/40 transition-colors"
                >
                  <div class="flex items-center gap-3 min-w-0 flex-1">
                    <div class="w-7 h-7 shrink-0 rounded-md bg-muted/60 flex items-center justify-center text-xs font-medium text-muted-foreground tabular-nums">
                      {{ index + 1 }}
                    </div>
                    <div class="min-w-0 flex-1">
                      <div class="flex items-center gap-2">
                        <span class="text-sm font-medium text-foreground group-hover:text-primary transition-colors truncate">
                          {{ execution.workflow_name }}
                        </span>
                        <StatusBadge type="execution" :status="execution.status" size="sm" class="shrink-0" />
                      </div>
                      <div class="text-xs text-muted-foreground mt-0.5">
                        {{ formatDate(execution.created_at) }}
                      </div>
                    </div>
                  </div>
                  <span class="icon-[lucide--chevron-right] text-sm text-muted-foreground/60 group-hover:text-primary group-hover:translate-x-0.5 transition-all shrink-0" />
                </RouterLink>
              </div>
            </div>
          </div>
        </section>

        <!-- 危险操作（删除空间仅系统管理员可见，#10） -->
        <section v-if="isSystemAdmin" id="danger-zone" class="scroll-mt-22">
          <div class="card border-destructive/30">
            <div class="px-5 py-3.5 border-b border-destructive/20 bg-destructive/[0.03] flex items-center gap-2">
              <span class="icon-[lucide--alert-triangle] text-destructive" />
              <h3 class="text-sm font-semibold text-destructive">
                危险操作
              </h3>
            </div>
            <div class="p-5">
              <div class="flex items-start justify-between gap-4">
                <div class="min-w-0 flex-1">
                  <p class="text-sm font-medium text-foreground">
                    删除空间
                  </p>
                  <p class="text-xs text-muted-foreground mt-1">
                    此操作不可撤销，空间内所有配置将被永久清除。
                  </p>
                </div>
                <Button variant="destructive" size="sm" class="shrink-0" @click="deleteDialogOpen = true">
                  <span class="icon-[lucide--trash-2] mr-1.5" />
                  删除空间
                </Button>
              </div>
            </div>
          </div>
        </section>
      </AnchorNavLayout>
    </div>

    <!-- 飞书配置弹窗 -->
    <FeishuConfigModal
      v-model:open="feishuModalOpen"
      :space-id="spaceId"
      @updated="handleFeishuUpdated"
      @edit-space="handleEditSpaceFromFeishu"
    />

    <!-- Prompt 覆盖弹窗 -->
    <SpacePromptsModal
      v-model:open="promptsModalOpen"
      :space-id="spaceId"
    />

    <!-- Provider 凭证弹窗 -->
    <SpaceProvidersModal
      v-model:open="providersModalOpen"
      :space-id="spaceId"
    />

    <!-- 成员管理弹窗 -->
    <SpaceMembersModal
      v-model:open="membersModalOpen"
      :space-id="spaceId"
    />

    <!-- 删除确认对话框 -->
    <ConfirmDialog
      v-model:open="deleteDialogOpen"
      title="删除空间"
      description="确定要删除此空间吗？此操作不可撤销，空间内所有配置将被清除。"
      confirm-text="删除"
      variant="destructive"
      :loading="deleting"
      @confirm="handleDelete"
    />
  </div>

  <!-- 管理仓库关联对话框 - 穿梭框样式 -->
  <BaseModal
    v-model="linkDialogOpen"
    title="管理仓库关联"
    size="md"
  >
    <div class="space-y-4">
      <p class="text-sm text-muted-foreground">
        在左侧选择要关联的仓库，在右侧选择要解除关联的仓库
      </p>

      <div class="grid grid-cols-2 gap-6">
        <!-- 左侧：可用仓库 -->
        <div class="flex flex-col">
          <div class="flex items-center justify-between h-9 mb-3">
            <h4 class="text-sm font-medium flex items-center gap-2">
              <span class="icon-[lucide--inbox] text-muted-foreground" />
              可用仓库
              <span class="text-xs text-muted-foreground font-normal">({{ availableRepositories.length }})</span>
            </h4>
            <div class="flex items-center gap-1">
              <Button
                v-if="availableRepositories.length > 0"
                variant="ghost"
                size="sm"
                class="h-7 px-2 text-xs"
                @click="selectAllAvailable"
              >
                全选
              </Button>
              <Button
                v-if="selectedToLink.size > 0"
                variant="ghost"
                size="sm"
                class="h-7 px-2 text-xs"
                @click="clearSelectToLink"
              >
                清空
              </Button>
            </div>
          </div>
          <div class="border border-border/50 rounded-xl bg-muted/20 h-72 overflow-y-auto mb-3">
            <div v-if="availableRepositories.length === 0" class="flex flex-col items-center justify-center h-full text-muted-foreground">
              <span class="icon-[lucide--package] text-2xl mb-2 opacity-50" />
              <span class="text-sm">没有可用仓库</span>
            </div>
            <div v-else class="p-2 space-y-1">
              <div
                v-for="repo in availableRepositories"
                :key="repo.id"
                class="flex items-center gap-3 p-2.5 rounded-lg cursor-pointer transition-colors"
                :class="selectedToLink.has(repo.id) ? 'bg-primary/10 border border-primary/30' : 'hover:bg-muted/50 border border-transparent'"
                @click="toggleSelectToLink(repo.id)"
              >
                <div
                  class="w-5 h-5 rounded border-2 flex items-center justify-center shrink-0 transition-colors"
                  :class="selectedToLink.has(repo.id) ? 'bg-primary border-primary' : 'border-muted-foreground/30'"
                >
                  <span v-if="selectedToLink.has(repo.id)" class="icon-[lucide--check] text-xs text-primary-foreground" />
                </div>
                <div class="min-w-0 flex-1">
                  <div class="font-medium text-sm truncate">
                    {{ repo.name }}
                  </div>
                  <div class="text-xs text-muted-foreground truncate">
                    {{ repo.git_url }}
                  </div>
                </div>
              </div>
            </div>
          </div>
          <Button
            class="w-full h-10 group"
            :disabled="selectedToLink.size === 0 || linking"
            @click="handleLinkSelected"
          >
            <span v-if="linking" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
            <span v-else class="icon-[lucide--arrow-right] mr-2 group-hover:translate-x-1 transition-transform" />
            关联选中 ({{ selectedToLink.size }})
          </Button>
        </div>

        <!-- 右侧：已关联仓库 -->
        <div class="flex flex-col">
          <div class="flex items-center justify-between h-9 mb-3">
            <h4 class="text-sm font-medium flex items-center gap-2">
              <span class="icon-[lucide--link] text-primary" />
              已关联仓库
              <span class="text-xs text-muted-foreground font-normal">({{ linkedRepositories.length }})</span>
            </h4>
            <div class="flex items-center gap-1">
              <Button
                v-if="linkedRepositories.length > 0"
                variant="ghost"
                size="sm"
                class="h-7 px-2 text-xs"
                @click="selectAllLinked"
              >
                全选
              </Button>
              <Button
                v-if="selectedToUnlink.size > 0"
                variant="ghost"
                size="sm"
                class="h-7 px-2 text-xs"
                @click="clearSelectToUnlink"
              >
                清空
              </Button>
            </div>
          </div>
          <div class="border border-border/50 rounded-xl bg-muted/20 h-72 overflow-y-auto mb-3">
            <div v-if="linkedRepositories.length === 0" class="flex flex-col items-center justify-center h-full text-muted-foreground">
              <span class="icon-[lucide--unlink] text-2xl mb-2 opacity-50" />
              <span class="text-sm">暂无关联仓库</span>
            </div>
            <div v-else class="p-2 space-y-1">
              <div
                v-for="repo in linkedRepositories"
                :key="repo.id"
                class="flex items-center gap-3 p-2.5 rounded-lg cursor-pointer transition-colors"
                :class="selectedToUnlink.has(repo.id) ? 'bg-destructive/10 border border-destructive/30' : 'hover:bg-muted/50 border border-transparent'"
                @click="toggleSelectToUnlink(repo.id)"
              >
                <div
                  class="w-5 h-5 rounded border-2 flex items-center justify-center shrink-0 transition-colors"
                  :class="selectedToUnlink.has(repo.id) ? 'bg-destructive border-destructive' : 'border-muted-foreground/30'"
                >
                  <span v-if="selectedToUnlink.has(repo.id)" class="icon-[lucide--check] text-xs text-destructive-foreground" />
                </div>
                <div class="min-w-0 flex-1">
                  <div class="font-medium text-sm truncate">
                    {{ repo.name }}
                  </div>
                  <div class="text-xs text-muted-foreground truncate">
                    {{ repo.git_url }}
                  </div>
                </div>
              </div>
            </div>
          </div>
          <Button
            variant="outline"
            class="w-full h-10 group text-destructive hover:bg-destructive/10"
            :disabled="selectedToUnlink.size === 0 || linking"
            @click="handleUnlinkSelected"
          >
            <span v-if="linking" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
            <span v-else class="icon-[lucide--arrow-left] mr-2 group-hover:-translate-x-1 transition-transform" />
            解除关联 ({{ selectedToUnlink.size }})
          </Button>
        </div>
      </div>

      <p v-if="availableRepositories.length === 0 && linkedRepositories.length === 0" class="text-sm text-muted-foreground text-center py-2">
        没有可用的仓库，请先<RouterLink to="/repositories" class="text-primary hover:underline">
          创建仓库
        </RouterLink>
      </p>
    </div>

    <template #footer>
      <div class="flex justify-end w-full">
        <Button variant="outline" @click="linkDialogOpen = false">
          完成
        </Button>
      </div>
    </template>
  </BaseModal>

  <!-- 刷新 Token 确认对话框 -->
  <ConfirmDialog
    v-model:open="refreshTokenDialogOpen"
    title="刷新 Webhook Token"
    description="刷新后，旧的 Token 将立即失效。请确保在飞书项目自动化规则中更新新的 Token，否则 Webhook 请求将无法验证通过。"
    confirm-text="刷新"
    variant="destructive"
    :loading="refreshingToken"
    @confirm="handleRefreshToken"
  />

  <!-- 自定义 Token 对话框 -->
  <BaseModal
    v-model="customTokenDialogOpen"
    title="自定义 Webhook Token"
    size="md"
  >
    <div class="space-y-4">
      <p class="text-sm text-muted-foreground">
        输入自定义 Token（最大 32 字符），用于在飞书项目自动化规则中配置
      </p>
      <div class="py-2 space-y-4">
        <div class="space-y-2">
          <Label for="customToken">Token</Label>
          <Input
            id="customToken"
            v-model="customTokenValue"
            placeholder="输入自定义 Token"
            maxlength="32"
            class="h-11 bg-muted/30 border-border/50 focus:border-primary/50"
          />
          <p class="text-sm text-muted-foreground">
            {{ customTokenValue.length }}/32 字符
          </p>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="flex justify-end gap-3 w-full">
        <Button variant="outline" @click="customTokenDialogOpen = false">
          取消
        </Button>
        <Button :disabled="customTokenLoading" class="group relative overflow-hidden" @click="handleCustomToken">
          <span class="absolute inset-0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
          <span v-if="customTokenLoading" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
          {{ customTokenLoading ? '保存中...' : '保存' }}
        </Button>
      </div>
    </template>
  </BaseModal>
</template>
