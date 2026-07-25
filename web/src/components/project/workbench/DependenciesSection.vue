<script setup lang="ts">
import type { Artifact, ArtifactView } from '~/api/artifacts'
import type { MergeRequest } from '~/api/mergeRequests'
import type { ProjectBranch, ProjectGraphNode, ProjectRepoLink } from '~/api/projects'
import type { SpaceRepositoryLink } from '~/types'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, reactive, ref, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { artifactsApi } from '~/api/artifacts'
import { mergeRequestsApi } from '~/api/mergeRequests'
import { projectsApi } from '~/api/projects'
import { getSpaceRepositories } from '~/api/spaces'
import MarkdownRenderer from '~/components/execution/MarkdownRenderer.vue'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogDescription,
  DialogHeader,
  DialogScrollContent,
  DialogTitle,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { useErrorHandler } from '~/composables/useErrorHandler'

// WB-04：外部工件（原型/Spec/缺陷/UI 稿/评审/复盘，复用 Artifact）+ 关联（分支/仓库/知识/项目/PR）。
// 复用既有端点，不杜撰；ProjectBranch 多绑定为 Phase 85，分支位仅占位标注。
const props = defineProps<{ projectId: string }>()

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { success } = useToast()
const queryClient = useQueryClient()
const projectIdRef = toRef(props, 'projectId')

// ── 外部工件 ──────────────────────────────────────────────
const artifactsQuery = useQuery({
  queryKey: ['project-deps-artifacts', projectIdRef],
  queryFn: () => artifactsApi.list(props.projectId),
})
const artifacts = computed<Artifact[]>(() => artifactsQuery.data.value ?? [])
const artifactGroups = computed(() => {
  const map = new Map<string, Artifact[]>()
  for (const a of artifacts.value) {
    const key = a.type_name || a.type_key
    if (!map.has(key))
      map.set(key, [])
    map.get(key)!.push(a)
  }
  return Array.from(map, ([name, list]) => ({ name, list }))
})

// ── 关联仓库（#4：项目级——业务关联 ∪ 分支绑定，空项目为空，不再显示整个空间的仓库池）──
const reposQuery = useQuery({
  queryKey: ['project-deps-repos', projectIdRef],
  queryFn: () => projectsApi.repositories(props.projectId),
})
const repos = computed<ProjectRepoLink[]>(() => reposQuery.data.value ?? [])

// ── 知识 / 关联项目（知识图谱）─────────────────────────────
const graphQuery = useQuery({
  queryKey: ['project-deps-graph', projectIdRef],
  queryFn: () => projectsApi.graph(props.projectId, { direction: 'both', maxHops: 1 }),
})
const graphNodes = computed<ProjectGraphNode[]>(() => graphQuery.data.value?.nodes ?? [])
const knowledgeNodes = computed(() => graphNodes.value.filter(n => n.kind !== 'project'))
const projectNodes = computed(() => graphNodes.value.filter(n => n.kind === 'project'))

// ── 关联 PR / MR ─────────────────────────────────────────
const mrQuery = useQuery({
  queryKey: ['project-deps-mrs', projectIdRef],
  queryFn: () => mergeRequestsApi.list(props.projectId),
})
const mrs = computed<MergeRequest[]>(() => mrQuery.data.value ?? [])

// ── 关联分支（#3 严格按分支名：ProjectBranch 绑定，不再从 MR 归集；空项目亦可绑定）──
const branchesQuery = useQuery({
  queryKey: ['project-branches', projectIdRef],
  queryFn: () => projectsApi.listBranches(props.projectId),
})
const branches = computed<ProjectBranch[]>(() => branchesQuery.data.value ?? [])

// 取项目所属空间的仓库池，供「绑定分支」选择仓库（分支绑定模型要求 repository_id）。
const projectQuery = useQuery({
  queryKey: ['project', projectIdRef],
  queryFn: () => projectsApi.get(props.projectId),
})
const spaceId = computed(() => projectQuery.data.value?.space_id)
const spaceReposQuery = useQuery({
  queryKey: ['project-space-repos', spaceId],
  queryFn: () => getSpaceRepositories(spaceId.value as string),
  enabled: computed(() => !!spaceId.value),
})
const spaceRepos = computed<SpaceRepositoryLink[]>(() => spaceReposQuery.data.value ?? [])

const showAddBranch = ref(false)
const newBranch = reactive({ repository_id: '', branch_name: '' })

const bindMutation = useMutation({
  mutationFn: () => projectsApi.bindBranch(props.projectId, {
    repository_id: newBranch.repository_id,
    branch_name: newBranch.branch_name.trim(),
  }),
  onSuccess: () => {
    success(t('projects.workbench.deps.branchBound'))
    newBranch.repository_id = ''
    newBranch.branch_name = ''
    showAddBranch.value = false
    queryClient.invalidateQueries({ queryKey: ['project-branches', projectIdRef] })
    // 绑定分支会让该仓库出现在「关联仓库」，一并失效。
    queryClient.invalidateQueries({ queryKey: ['project-deps-repos', projectIdRef] })
  },
  onError: (e: unknown) => handleError(e, t('projects.workbench.deps.branchBindFailed')),
})

const unbindMutation = useMutation({
  mutationFn: (branchId: string) => projectsApi.unbindBranch(props.projectId, branchId),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['project-branches', projectIdRef] })
    queryClient.invalidateQueries({ queryKey: ['project-deps-repos', projectIdRef] })
  },
  onError: (e: unknown) => handleError(e, t('projects.workbench.deps.branchUnbindFailed')),
})

const canSubmitBranch = computed(() =>
  !!newBranch.repository_id && !!newBranch.branch_name.trim() && !bindMutation.isPending.value,
)

function mrStatusClass(status: string): string {
  switch (status) {
    case 'merged':
      return 'bg-violet-500/10 text-violet-600 dark:text-violet-400'
    case 'open':
      return 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
    default:
      return 'bg-muted text-muted-foreground'
  }
}

// ── 工件在线查看（弹窗模式，取代已删除的 ArtifactsTab）────────────────
const CARRIER_ICON: Record<string, string> = {
  feishu_doc: 'lucide--file-text',
  feishu_bitable: 'lucide--table',
  external_link: 'lucide--external-link',
  markdown: 'lucide--file-code',
  repo_file: 'lucide--file',
}

const viewOpen = ref(false)
const viewLoading = ref(false)
const viewData = ref<ArtifactView | null>(null)
const viewTitle = ref('')

async function openView(artifact: Artifact) {
  viewTitle.value = artifact.title
  viewData.value = null
  viewOpen.value = true
  viewLoading.value = true
  try {
    viewData.value = await artifactsApi.view(props.projectId, artifact.id)
  }
  catch (e: unknown) {
    handleError(e, t('projects.artifacts.viewFailed'))
    viewOpen.value = false
  }
  finally {
    viewLoading.value = false
  }
}
</script>

<template>
  <section class="card" data-testid="workbench-deps-section">
    <header class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2.5">
      <span class="section-chip"><span class="icon-[lucide--network]" /></span>
      <h2 class="text-sm font-semibold text-foreground">
        {{ t('projects.workbench.deps.title') }}
      </h2>
    </header>

    <div class="p-5 space-y-6">
      <!-- 外部工件 -->
      <section class="space-y-3" data-testid="deps-artifacts">
        <div class="space-y-0.5">
          <h3 class="text-sm font-semibold text-foreground flex items-center gap-2">
            <span class="icon-[lucide--package] text-primary" />
            {{ t('projects.workbench.deps.artifactsTitle') }}
          </h3>
          <p class="text-xs text-muted-foreground">
            {{ t('projects.workbench.deps.artifactsHint') }}
          </p>
        </div>
        <div v-if="artifactsQuery.isLoading.value" class="text-sm text-muted-foreground py-4 text-center">
          {{ t('projects.loading') }}
        </div>
        <div v-else-if="artifactsQuery.isError.value" class="py-4 text-center space-y-2">
          <p class="text-sm text-destructive">
            {{ t('projects.workbench.deps.artifactsLoadError') }}
          </p>
          <button class="text-sm text-primary underline" @click="() => artifactsQuery.refetch()">
            {{ t('projects.retry') }}
          </button>
        </div>
        <div v-else-if="artifacts.length === 0" class="text-sm text-muted-foreground py-4 text-center">
          {{ t('projects.workbench.deps.artifactsEmpty') }}
        </div>
        <div v-else class="space-y-4">
          <div v-for="group in artifactGroups" :key="group.name" class="space-y-2">
            <h4 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              {{ group.name }}
            </h4>
            <ul class="divide-y divide-border/40 rounded-lg border border-border/40 bg-card">
              <li
                v-for="a in group.list"
                :key="a.id"
                class="flex items-center justify-between gap-3 px-4 py-3"
                data-testid="deps-artifact-row"
              >
                <div class="min-w-0 flex items-center gap-3">
                  <span :class="`icon-[${CARRIER_ICON[a.carrier] || 'lucide--file'}] text-muted-foreground`" />
                  <div class="min-w-0">
                    <p class="text-sm font-medium text-foreground truncate">
                      {{ a.title }}
                    </p>
                    <p class="text-xs text-muted-foreground">
                      {{ t(`projects.artifacts.carrier.${a.carrier}`) }} · v{{ a.version }}
                    </p>
                  </div>
                </div>
                <div class="flex items-center gap-1.5 shrink-0">
                  <button
                    class="inline-flex items-center gap-1 rounded-md border border-border/60 px-2 h-7 text-xs text-foreground hover:border-primary/40 hover:text-primary transition-colors"
                    data-testid="deps-view-artifact-btn"
                    :title="t('projects.artifacts.view')"
                    @click="openView(a)"
                  >
                    <span class="icon-[lucide--maximize-2] text-[11px]" />
                    {{ t('projects.artifacts.view') }}
                  </button>
                  <RouterLink
                    v-if="a.entity_id"
                    :to="`/knowledge/entities/${a.entity_id}`"
                    class="inline-flex items-center gap-1 rounded-md border border-border/60 px-2 h-7 text-xs text-muted-foreground hover:border-primary/40 hover:text-primary transition-colors"
                    data-testid="deps-view-knowledge-btn"
                    :title="t('projects.workbench.deps.viewKnowledge')"
                  >
                    <span class="icon-[lucide--brain] text-[11px]" />
                  </RouterLink>
                  <a
                    v-if="a.url"
                    :href="a.url"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="inline-flex items-center gap-1 rounded-md border border-border/60 px-2 h-7 text-xs text-muted-foreground hover:border-primary/40 hover:text-primary transition-colors"
                    :title="t('projects.artifacts.openExternal')"
                    data-testid="deps-open-external-btn"
                  >
                    <span class="icon-[lucide--external-link] text-[11px]" />
                    {{ a.carrier === 'feishu_doc' || a.carrier === 'feishu_bitable' ? t('projects.artifacts.openFeishu') : t('projects.artifacts.openLink') }}
                  </a>
                </div>
              </li>
            </ul>
          </div>
        </div>
      </section>

      <!-- 关联分支（#3 严格按分支名：ProjectBranch 绑定，空项目亦可配置，配合 skills 分支→项目反查） -->
      <section class="space-y-2" data-testid="deps-branches">
        <div class="flex items-center gap-2">
          <h3 class="text-sm font-semibold text-foreground flex items-center gap-2">
            <span class="icon-[lucide--git-branch] text-primary" />
            {{ t('projects.workbench.deps.branchesTitle') }}
          </h3>
          <button
            class="ml-auto text-xs text-primary hover:underline inline-flex items-center gap-1"
            data-testid="deps-add-branch-btn"
            @click="showAddBranch = !showAddBranch"
          >
            <span class="icon-[lucide--plus] text-[11px]" />
            {{ t('projects.workbench.deps.branchAdd') }}
          </button>
        </div>

        <!-- 绑定分支表单：选仓库 + 填分支名 -->
        <div v-if="showAddBranch" class="rounded-lg border border-border/50 p-3 space-y-2" data-testid="deps-branch-form">
          <Select v-model="newBranch.repository_id">
            <SelectTrigger class="h-8 text-sm" data-testid="deps-branch-repo">
              <SelectValue :placeholder="t('projects.workbench.deps.branchRepoPlaceholder')" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="r in spaceRepos" :key="r.repository_id" :value="r.repository_id">
                {{ r.repository_name }}
              </SelectItem>
            </SelectContent>
          </Select>
          <div class="flex items-center gap-2">
            <Input
              v-model="newBranch.branch_name"
              :placeholder="t('projects.workbench.deps.branchNamePlaceholder')"
              class="h-8 flex-1 font-mono text-sm"
              data-testid="deps-branch-name"
            />
            <Button size="sm" :disabled="!canSubmitBranch" data-testid="deps-branch-submit" @click="() => bindMutation.mutate()">
              {{ t('projects.workbench.deps.branchBind') }}
            </Button>
          </div>
          <p v-if="spaceRepos.length === 0" class="text-xs text-muted-foreground">
            {{ t('projects.workbench.deps.branchNoRepo') }}
          </p>
        </div>

        <p v-if="branches.length === 0 && !showAddBranch" class="text-sm text-muted-foreground py-4 text-center">
          {{ t('projects.workbench.deps.branchesEmpty') }}
        </p>
        <ul v-else-if="branches.length > 0" class="divide-y divide-border/40 rounded-lg border border-border/40 bg-card">
          <li
            v-for="b in branches"
            :key="b.id"
            class="flex items-center gap-3 px-4 py-3"
            data-testid="deps-branch-row"
          >
            <span class="icon-[lucide--git-branch] text-muted-foreground shrink-0" />
            <code class="text-sm text-foreground truncate font-mono">{{ b.branch_name }}</code>
            <span class="text-xs text-muted-foreground truncate hidden sm:inline">· {{ b.repository_name }}</span>
            <button
              class="ml-auto shrink-0 text-muted-foreground hover:text-destructive transition-colors"
              :disabled="unbindMutation.isPending.value"
              :title="t('projects.workbench.deps.branchUnbind')"
              data-testid="deps-branch-unbind"
              @click="() => unbindMutation.mutate(b.id)"
            >
              <span class="icon-[lucide--x] text-sm" />
            </button>
          </li>
        </ul>
      </section>

      <!-- 关联仓库 -->
      <section class="space-y-3" data-testid="deps-repos">
        <h3 class="text-sm font-semibold text-foreground flex items-center gap-2">
          <span class="icon-[lucide--folder-git-2] text-primary" />
          {{ t('projects.workbench.deps.repositoriesTitle') }}
        </h3>
        <div v-if="reposQuery.isLoading.value" class="text-sm text-muted-foreground py-4 text-center">
          {{ t('projects.loading') }}
        </div>
        <div v-else-if="reposQuery.isError.value" class="py-4 text-center space-y-2">
          <p class="text-sm text-destructive">
            {{ t('projects.workbench.deps.repositoriesLoadError') }}
          </p>
          <button class="text-sm text-primary underline" @click="() => reposQuery.refetch()">
            {{ t('projects.retry') }}
          </button>
        </div>
        <div v-else-if="repos.length === 0" class="text-sm text-muted-foreground py-4 text-center">
          {{ t('projects.workbench.deps.repositoriesEmpty') }}
        </div>
        <ul v-else class="divide-y divide-border/40 rounded-lg border border-border/40 bg-card">
          <RouterLink
            v-for="repo in repos"
            :key="repo.id"
            :to="`/repositories/${repo.repository_id}`"
            class="group flex items-center gap-3 px-4 py-3 hover:bg-muted/40 transition-colors"
            data-testid="deps-repo-row"
          >
            <span class="icon-[lucide--git-fork] text-muted-foreground shrink-0" />
            <span class="text-sm text-foreground truncate group-hover:text-primary transition-colors">{{ repo.repository_name }}</span>
            <span class="icon-[lucide--chevron-right] ml-auto shrink-0 text-muted-foreground/50 group-hover:text-primary transition-colors" />
          </RouterLink>
        </ul>
      </section>

      <!-- 知识关联 -->
      <section class="space-y-3" data-testid="deps-knowledge">
        <h3 class="text-sm font-semibold text-foreground flex items-center gap-2">
          <span class="icon-[lucide--brain] text-primary" />
          {{ t('projects.workbench.deps.knowledgeTitle') }}
        </h3>
        <div v-if="graphQuery.isLoading.value" class="text-sm text-muted-foreground py-4 text-center">
          {{ t('projects.loading') }}
        </div>
        <div v-else-if="graphQuery.isError.value" class="py-4 text-center space-y-2">
          <p class="text-sm text-destructive">
            {{ t('projects.workbench.deps.knowledgeLoadError') }}
          </p>
          <button class="text-sm text-primary underline" @click="() => graphQuery.refetch()">
            {{ t('projects.retry') }}
          </button>
        </div>
        <div v-else-if="knowledgeNodes.length === 0" class="text-sm text-muted-foreground py-4 text-center">
          {{ t('projects.workbench.deps.knowledgeEmpty') }}
        </div>
        <ul v-else class="divide-y divide-border/40 rounded-lg border border-border/40 bg-card">
          <li
            v-for="(node, idx) in knowledgeNodes"
            :key="node.entity_id || idx"
            class="flex items-center justify-between gap-3 px-4 py-3"
            data-testid="deps-knowledge-row"
          >
            <div class="min-w-0">
              <p class="text-sm font-medium text-foreground truncate">
                {{ node.title || node.name || node.entity_id || '—' }}
              </p>
              <p class="text-xs text-muted-foreground">
                {{ node.kind }}<span v-if="node.relation"> · {{ node.relation }}</span>
              </p>
            </div>
          </li>
        </ul>
      </section>

      <!-- 关联项目 -->
      <section class="space-y-3" data-testid="deps-projects">
        <h3 class="text-sm font-semibold text-foreground flex items-center gap-2">
          <span class="icon-[lucide--folder-tree] text-primary" />
          {{ t('projects.workbench.deps.projectsTitle') }}
        </h3>
        <div v-if="projectNodes.length === 0" class="text-sm text-muted-foreground py-4 text-center">
          {{ t('projects.workbench.deps.projectsEmpty') }}
        </div>
        <ul v-else class="divide-y divide-border/40 rounded-lg border border-border/40 bg-card">
          <li
            v-for="(node, idx) in projectNodes"
            :key="node.entity_id || idx"
            class="flex items-center gap-3 px-4 py-3"
            data-testid="deps-project-row"
          >
            <span class="icon-[lucide--folder] text-muted-foreground" />
            <span class="text-sm text-foreground truncate">{{ node.title || node.name || node.entity_id || '—' }}</span>
          </li>
        </ul>
      </section>

      <!-- 关联 PR / MR -->
      <section class="space-y-3" data-testid="deps-mrs">
        <h3 class="text-sm font-semibold text-foreground flex items-center gap-2">
          <span class="icon-[lucide--git-pull-request] text-primary" />
          {{ t('projects.workbench.deps.mergeRequestsTitle') }}
        </h3>
        <div v-if="mrQuery.isLoading.value" class="text-sm text-muted-foreground py-4 text-center">
          {{ t('projects.loading') }}
        </div>
        <div v-else-if="mrQuery.isError.value" class="py-4 text-center space-y-2">
          <p class="text-sm text-destructive">
            {{ t('projects.workbench.deps.mrLoadError') }}
          </p>
          <button class="text-sm text-primary underline" @click="() => mrQuery.refetch()">
            {{ t('projects.retry') }}
          </button>
        </div>
        <div v-else-if="mrs.length === 0" class="text-sm text-muted-foreground py-4 text-center">
          {{ t('projects.workbench.deps.mrEmpty') }}
        </div>
        <ul v-else class="divide-y divide-border/40 rounded-lg border border-border/40 bg-card">
          <li v-for="mr in mrs" :key="mr.id" class="px-4 py-3 space-y-1" data-testid="deps-mr-row">
            <div class="flex items-center justify-between gap-2">
              <a
                :href="mr.url"
                target="_blank"
                rel="noopener noreferrer"
                class="text-sm font-medium text-primary hover:underline truncate"
              >
                {{ mr.title || `#${mr.external_id}` }}
              </a>
              <span class="px-2 py-0.5 rounded-full text-xs font-medium shrink-0" :class="mrStatusClass(mr.status)">
                {{ t(`projects.links.mrStatus.${mr.status}`) }}
              </span>
            </div>
            <p class="text-xs text-muted-foreground">
              {{ mr.platform }} · {{ mr.source_branch }} → {{ mr.target_branch }}
            </p>
          </li>
        </ul>
      </section>
    </div>

    <!-- 工件在线查看 -->
    <Dialog v-model:open="viewOpen">
      <DialogScrollContent class="w-[92vw] max-w-5xl">
        <DialogHeader>
          <DialogTitle>{{ viewTitle }}</DialogTitle>
          <DialogDescription>{{ t('projects.artifacts.viewDesc') }}</DialogDescription>
        </DialogHeader>
        <div class="mt-2">
          <div v-if="viewLoading" class="text-sm text-muted-foreground py-6 text-center">
            {{ t('projects.loading') }}
          </div>
          <template v-else-if="viewData">
            <p v-if="viewData.error" class="text-sm text-destructive">
              {{ viewData.error }}
            </p>
            <a
              v-else-if="viewData.render_type === 'link'"
              :href="viewData.url"
              target="_blank"
              rel="noopener noreferrer"
              class="text-sm text-primary underline break-all"
            >
              {{ viewData.url }}
            </a>
            <div
              v-else-if="viewData.render_type === 'markdown'"
              class="max-h-[72vh] overflow-auto"
            >
              <MarkdownRenderer :content="viewData.content || ''" />
            </div>
            <pre
              v-else-if="viewData.render_type === 'text'"
              class="text-xs bg-muted/50 rounded-lg p-3 max-h-[72vh] overflow-auto whitespace-pre-wrap"
            >{{ viewData.content }}</pre>
            <div v-else-if="viewData.render_type === 'records'" class="text-xs space-y-1 max-h-[72vh] overflow-auto">
              <p class="text-muted-foreground">
                {{ t('projects.artifacts.recordCount', { n: viewData.records?.length ?? 0 }) }}
              </p>
              <pre class="bg-muted/50 rounded-lg p-3 overflow-auto">{{ JSON.stringify(viewData.records, null, 2) }}</pre>
            </div>
            <p v-else class="text-sm text-muted-foreground">
              {{ t('projects.artifacts.unsupported') }}
            </p>
          </template>
        </div>
      </DialogScrollContent>
    </Dialog>
  </section>
</template>
