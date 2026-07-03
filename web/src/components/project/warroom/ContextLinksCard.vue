<script setup lang="ts">
import type {
  ContextLinkKind,
  ContextLinkRepoCandidate,
  ProjectContextLink,
} from '~/api/projectContextLinks'
import type { BadgeVariants } from '~/components/ui/badge'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, reactive, ref, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { contextLinksApi } from '~/api/projectContextLinks'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

// 「生成知识关联」面板：一键生成 仓库/知识/工件/MR 候选 → 成员就地审阅（关联/忽略）
// + 手动添加/删除。仓库候选走 RepoAssociation 状态机，其余走 ProjectContextLink。
const props = defineProps<{ projectId: string, canManage?: boolean }>()

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { success } = useToast()
const { confirm } = useConfirmDialog()
const queryClient = useQueryClient()
const projectIdRef = toRef(props, 'projectId')

const KIND_ICONS: Record<ContextLinkKind, string> = {
  knowledge: 'icon-[lucide--book-open]',
  artifact: 'icon-[lucide--file-text]',
  merge_request: 'icon-[lucide--git-pull-request]',
  external: 'icon-[lucide--link]',
}

const { data, isLoading, isError, refetch } = useQuery({
  queryKey: ['project-context-links', projectIdRef],
  queryFn: () => contextLinksApi.list(props.projectId),
})

const proposedLinks = computed<ProjectContextLink[]>(
  () => (data.value?.links ?? []).filter(l => l.status === 'proposed'),
)
const acceptedLinks = computed<ProjectContextLink[]>(
  () => (data.value?.links ?? []).filter(l => l.status === 'accepted'),
)
const proposedRepos = computed<ContextLinkRepoCandidate[]>(
  () => (data.value?.repos ?? []).filter(r => r.status === 'proposed'),
)
const linkedRepos = computed<ContextLinkRepoCandidate[]>(
  () => (data.value?.repos ?? []).filter(r =>
    ['confirmed', 'verifying', 'verified'].includes(r.status),
  ),
)
const proposedCount = computed(() => proposedLinks.value.length + proposedRepos.value.length)
const isEmpty = computed(
  () =>
    proposedCount.value === 0
    && acceptedLinks.value.length === 0
    && linkedRepos.value.length === 0,
)

function invalidate() {
  queryClient.invalidateQueries({ queryKey: ['project-context-links', projectIdRef] })
}

function repoStatusVariant(status: string): BadgeVariants['variant'] {
  switch (status) {
    case 'verified':
      return 'success'
    case 'confirmed':
    case 'verifying':
      return 'info'
    default:
      return 'muted'
  }
}

// ── 一键生成 ────────────────────────────────────────────────
const generateMutation = useMutation({
  mutationFn: () => contextLinksApi.generate(props.projectId),
  onSuccess: (result) => {
    success(t('projects.warroom.contextLinks.generated', { created: result.summary.created }))
    invalidate()
  },
  onError: (e: unknown) => handleError(e, t('projects.warroom.contextLinks.generateFailed')),
})

// ── 候选裁决 ────────────────────────────────────────────────
const decideMutation = useMutation({
  mutationFn: (vars: { linkId: string, action: 'accept' | 'reject' }) =>
    vars.action === 'accept'
      ? contextLinksApi.accept(props.projectId, vars.linkId)
      : contextLinksApi.reject(props.projectId, vars.linkId),
  onSuccess: (_link, vars) => {
    success(
      vars.action === 'accept'
        ? t('projects.warroom.contextLinks.accepted')
        : t('projects.warroom.contextLinks.rejectedToast'),
    )
    invalidate()
  },
  onError: (e: unknown) => handleError(e, t('projects.warroom.contextLinks.actionFailed')),
})

const repoDecideMutation = useMutation({
  mutationFn: (vars: { repositoryId: string, action: 'accept' | 'reject' }) =>
    contextLinksApi.repoDecision(props.projectId, {
      repository_id: vars.repositoryId,
      action: vars.action,
    }),
  onSuccess: (_res, vars) => {
    success(
      vars.action === 'accept'
        ? t('projects.warroom.contextLinks.accepted')
        : t('projects.warroom.contextLinks.rejectedToast'),
    )
    invalidate()
    // 仓库关联状态变化也影响「关联仓库」区。
    queryClient.invalidateQueries({ queryKey: ['project-deps-repos', projectIdRef] })
  },
  onError: (e: unknown) => handleError(e, t('projects.warroom.contextLinks.actionFailed')),
})

async function removeLink(link: ProjectContextLink) {
  const ok = await confirm({
    title: t('projects.warroom.contextLinks.removeTitle'),
    description: link.title || link.url,
    confirmText: t('projects.warroom.contextLinks.removeConfirm'),
    variant: 'destructive',
  })
  if (!ok)
    return
  try {
    await contextLinksApi.remove(props.projectId, link.id)
    success(t('projects.warroom.contextLinks.removed'))
    invalidate()
  }
  catch (e: unknown) {
    handleError(e, t('projects.warroom.contextLinks.actionFailed'))
  }
}

// ── 手动添加 ────────────────────────────────────────────────
const showAddForm = ref(false)
const manualForm = reactive({
  target_kind: 'external' as ContextLinkKind,
  target_id: '',
  title: '',
  url: '',
})
const canSubmitManual = computed(() => {
  if (manualForm.target_kind === 'external')
    return manualForm.title.trim().length > 0 && manualForm.url.trim().length > 0
  return manualForm.target_id.trim().length > 0
})

const addMutation = useMutation({
  mutationFn: () =>
    contextLinksApi.addManual(props.projectId, {
      target_kind: manualForm.target_kind,
      target_id: manualForm.target_kind === 'external' ? undefined : manualForm.target_id.trim(),
      title: manualForm.title.trim(),
      url: manualForm.url.trim(),
    }),
  onSuccess: () => {
    success(t('projects.warroom.contextLinks.added'))
    showAddForm.value = false
    manualForm.target_id = ''
    manualForm.title = ''
    manualForm.url = ''
    invalidate()
  },
  onError: (e: unknown) => handleError(e, t('projects.warroom.contextLinks.addFailed')),
})
</script>

<template>
  <section class="card" data-testid="warroom-context-links">
    <header class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2.5">
      <span class="section-chip"><span class="icon-[lucide--waypoints]" /></span>
      <h2 class="text-sm font-semibold text-foreground">
        {{ t('projects.warroom.contextLinks.title') }}
      </h2>
      <Badge v-if="proposedCount > 0" variant="warning" class="tabular-nums" data-testid="ctx-proposed-count">
        {{ proposedCount }}
      </Badge>
      <div class="ml-auto flex items-center gap-1.5">
        <Button
          v-if="canManage"
          size="sm"
          variant="ghost"
          class="h-7"
          data-testid="ctx-add-btn"
          @click="showAddForm = !showAddForm"
        >
          <span class="icon-[lucide--plus] mr-1" />{{ t('projects.warroom.contextLinks.addManual') }}
        </Button>
        <Button
          v-if="canManage"
          size="sm"
          variant="outline"
          class="h-7"
          :disabled="generateMutation.isPending.value"
          data-testid="ctx-generate-btn"
          @click="generateMutation.mutate()"
        >
          <span
            :class="generateMutation.isPending.value
              ? 'icon-[lucide--loader-2] animate-spin mr-1'
              : 'icon-[lucide--sparkles] mr-1'"
          />
          {{ generateMutation.isPending.value
            ? t('projects.warroom.contextLinks.generating')
            : t('projects.warroom.contextLinks.generate') }}
        </Button>
      </div>
    </header>

    <div class="p-5 space-y-4">
      <!-- 手动添加表单 -->
      <div
        v-if="showAddForm && canManage"
        class="space-y-2 rounded-md border border-border/60 p-3"
        data-testid="ctx-add-form"
      >
        <div class="flex items-center gap-2">
          <Select v-model="manualForm.target_kind">
            <SelectTrigger class="h-8 w-32 text-xs" :aria-label="t('projects.warroom.contextLinks.form.kind')">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="k in (['external', 'knowledge', 'artifact', 'merge_request'] as ContextLinkKind[])" :key="k" :value="k">
                {{ t(`projects.warroom.contextLinks.kind.${k}`) }}
              </SelectItem>
            </SelectContent>
          </Select>
          <Input
            v-if="manualForm.target_kind !== 'external'"
            v-model="manualForm.target_id"
            class="h-8 flex-1 text-xs font-mono"
            :placeholder="t('projects.warroom.contextLinks.form.targetIdHint')"
            data-testid="ctx-form-target-id"
          />
        </div>
        <Input
          v-model="manualForm.title"
          class="h-8 text-xs"
          :placeholder="t('projects.warroom.contextLinks.form.title')"
          data-testid="ctx-form-title"
        />
        <Input
          v-if="manualForm.target_kind === 'external' || manualForm.url"
          v-model="manualForm.url"
          class="h-8 text-xs"
          :placeholder="t('projects.warroom.contextLinks.form.url')"
          data-testid="ctx-form-url"
        />
        <div class="flex justify-end">
          <Button
            size="sm"
            class="h-7"
            :disabled="!canSubmitManual || addMutation.isPending.value"
            data-testid="ctx-form-submit"
            @click="addMutation.mutate()"
          >
            {{ t('projects.warroom.contextLinks.addSubmit') }}
          </Button>
        </div>
      </div>

      <LoadingState v-if="isLoading" variant="skeleton" :count="2" />

      <div v-else-if="isError" class="py-6 text-center space-y-2">
        <p class="text-sm text-destructive">
          {{ t('projects.warroom.contextLinks.loadError') }}
        </p>
        <button class="text-sm text-primary underline" @click="() => refetch()">
          {{ t('projects.retry') }}
        </button>
      </div>

      <CompactEmptyState
        v-else-if="isEmpty"
        icon="lucide--waypoints"
        :title="t('projects.warroom.contextLinks.emptyTitle')"
        :description="canManage
          ? t('projects.warroom.contextLinks.empty')
          : t('projects.warroom.contextLinks.emptyReadonly')"
        data-testid="ctx-empty"
      >
        <Button
          v-if="canManage"
          size="sm"
          variant="outline"
          class="h-7 text-xs"
          :disabled="generateMutation.isPending.value"
          @click="generateMutation.mutate()"
        >
          <span class="icon-[lucide--sparkles] mr-1" />
          {{ t('projects.warroom.contextLinks.generate') }}
        </Button>
      </CompactEmptyState>

      <template v-else>
        <!-- 待确认候选 -->
        <div v-if="proposedCount > 0" class="space-y-1.5">
          <h3 class="text-xs font-medium text-muted-foreground">
            {{ t('projects.warroom.contextLinks.proposedTitle') }}
          </h3>
          <ul class="divide-y divide-border/40">
            <li
              v-for="repo in proposedRepos"
              :key="repo.repository_id"
              class="flex items-center gap-2 py-2"
              data-testid="ctx-repo-row"
            >
              <span class="icon-[lucide--folder-git-2] text-muted-foreground shrink-0" />
              <div class="flex-1 min-w-0">
                <p class="text-sm text-foreground truncate">
                  {{ repo.repository_name }}
                </p>
                <p v-if="repo.reason" class="text-[11px] text-muted-foreground truncate" :title="repo.reason">
                  {{ repo.reason }}
                </p>
              </div>
              <template v-if="canManage">
                <Button
                  size="sm" variant="outline" class="h-6 px-2 text-xs"
                  :disabled="repoDecideMutation.isPending.value"
                  data-testid="ctx-repo-accept"
                  @click="repoDecideMutation.mutate({ repositoryId: repo.repository_id, action: 'accept' })"
                >
                  {{ t('projects.warroom.contextLinks.accept') }}
                </Button>
                <Button
                  size="sm" variant="ghost" class="h-6 px-2 text-xs text-muted-foreground"
                  :disabled="repoDecideMutation.isPending.value"
                  data-testid="ctx-repo-reject"
                  @click="repoDecideMutation.mutate({ repositoryId: repo.repository_id, action: 'reject' })"
                >
                  {{ t('projects.warroom.contextLinks.reject') }}
                </Button>
              </template>
            </li>

            <li
              v-for="link in proposedLinks"
              :key="link.id"
              class="flex items-center gap-2 py-2"
              data-testid="ctx-link-row"
            >
              <span :class="`${KIND_ICONS[link.target_kind]} text-muted-foreground shrink-0`" />
              <div class="flex-1 min-w-0">
                <a
                  v-if="link.url"
                  :href="link.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="text-sm text-foreground hover:text-primary truncate block"
                >{{ link.title || link.url }}</a>
                <p v-else class="text-sm text-foreground truncate">
                  {{ link.title }}
                </p>
                <p v-if="link.reason" class="text-[11px] text-muted-foreground truncate" :title="link.reason">
                  {{ link.reason }}
                </p>
              </div>
              <Badge variant="muted" class="shrink-0 text-[10px]">
                {{ t(`projects.warroom.contextLinks.kind.${link.target_kind}`) }}
              </Badge>
              <template v-if="canManage">
                <Button
                  size="sm" variant="outline" class="h-6 px-2 text-xs"
                  :disabled="decideMutation.isPending.value"
                  data-testid="ctx-link-accept"
                  @click="decideMutation.mutate({ linkId: link.id, action: 'accept' })"
                >
                  {{ t('projects.warroom.contextLinks.accept') }}
                </Button>
                <Button
                  size="sm" variant="ghost" class="h-6 px-2 text-xs text-muted-foreground"
                  :disabled="decideMutation.isPending.value"
                  data-testid="ctx-link-reject"
                  @click="decideMutation.mutate({ linkId: link.id, action: 'reject' })"
                >
                  {{ t('projects.warroom.contextLinks.reject') }}
                </Button>
              </template>
            </li>
          </ul>
        </div>

        <!-- 已关联 -->
        <div v-if="acceptedLinks.length > 0 || linkedRepos.length > 0" class="space-y-1.5">
          <h3 class="text-xs font-medium text-muted-foreground">
            {{ t('projects.warroom.contextLinks.acceptedTitle') }}
          </h3>
          <ul class="divide-y divide-border/40">
            <li
              v-for="repo in linkedRepos"
              :key="repo.repository_id"
              class="flex items-center gap-2 py-2"
              data-testid="ctx-linked-repo-row"
            >
              <span class="icon-[lucide--folder-git-2] text-muted-foreground shrink-0" />
              <p class="text-sm text-foreground truncate flex-1 min-w-0">
                {{ repo.repository_name }}
              </p>
              <Badge :variant="repoStatusVariant(repo.status)" class="shrink-0 text-[10px]">
                {{ t(`projects.warroom.contextLinks.repoStatus.${repo.status}`) }}
              </Badge>
            </li>
            <li
              v-for="link in acceptedLinks"
              :key="link.id"
              class="flex items-center gap-2 py-2"
              data-testid="ctx-accepted-row"
            >
              <span :class="`${KIND_ICONS[link.target_kind]} text-muted-foreground shrink-0`" />
              <div class="flex-1 min-w-0">
                <a
                  v-if="link.url"
                  :href="link.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="text-sm text-foreground hover:text-primary truncate block"
                >{{ link.title || link.url }}</a>
                <p v-else class="text-sm text-foreground truncate">
                  {{ link.title }}
                </p>
              </div>
              <Badge variant="muted" class="shrink-0 text-[10px]">
                {{ t(`projects.warroom.contextLinks.kind.${link.target_kind}`) }}
              </Badge>
              <Badge v-if="link.origin === 'manual'" variant="info" class="shrink-0 text-[10px]">
                {{ t('projects.warroom.contextLinks.manualBadge') }}
              </Badge>
              <button
                v-if="canManage"
                class="text-muted-foreground hover:text-destructive shrink-0"
                :aria-label="t('projects.warroom.contextLinks.remove')"
                data-testid="ctx-link-delete"
                @click="removeLink(link)"
              >
                <span class="icon-[lucide--trash-2] text-sm" />
              </button>
            </li>
          </ul>
        </div>
      </template>
    </div>
  </section>
</template>
