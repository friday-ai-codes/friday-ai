<script setup lang="ts">
import type { ArtifactView } from '~/api/artifacts'
import type { ArtifactTreeLeaf, ArtifactTreeProject, ArtifactTreeTypeGroup } from '~/api/knowledge'
import { useQuery } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { knowledgeApi } from '~/api'
import { artifactsApi } from '~/api/artifacts'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import MarkdownRenderer from '~/components/execution/MarkdownRenderer.vue'
import {
  Dialog,
  DialogDescription,
  DialogHeader,
  DialogScrollContent,
  DialogTitle,
} from '~/components/ui/dialog'
import { useErrorHandler } from '~/composables/useErrorHandler'

// 交付文档树（KDEP-04/05）：一次加载整棵可见树后做纯客户端搜索/展开/查看，前端零拼装。

const { t } = useI18n()
const { handleError } = useErrorHandler()

// 工件类型徽标配色令牌（与 index.vue Phase 96 令牌一致，视觉统一）。
const ARTIFACT_BADGE_CLASS = 'bg-amber-500/10 text-amber-700 border-amber-200 dark:text-amber-400'

// 载体图标映射：字面量完整 class 字符串，确保 Tailwind 源扫描命中、无需改 safelist。
const CARRIER_ICON: Record<string, string> = {
  feishu_doc: 'icon-[lucide--file-text]',
  feishu_bitable: 'icon-[lucide--table]',
  markdown: 'icon-[lucide--file-text]',
  repo_file: 'icon-[lucide--file-code]',
  external_link: 'icon-[lucide--external-link]',
}
function carrierIcon(carrier: string): string {
  return CARRIER_ICON[carrier] ?? 'icon-[lucide--file]'
}

const { data, isLoading, isError, isFetching, error, refetch } = useQuery({
  queryKey: ['knowledge', 'artifact-tree'],
  queryFn: () => knowledgeApi.fetchArtifactTree(),
  staleTime: 60_000,
})

watch(isError, (v) => {
  if (v)
    handleError(error.value, t('knowledge.tree.docs.loadFailed'))
})

// ── 树内即时搜索（纯客户端，不发请求）──
const searchQuery = ref('')
const normalizedQuery = computed(() => searchQuery.value.trim().toLowerCase())

const filteredProjects = computed<ArtifactTreeProject[]>(() => {
  const projects = data.value?.projects ?? []
  const q = normalizedQuery.value
  if (!q)
    return projects
  const out: ArtifactTreeProject[] = []
  for (const p of projects) {
    const types: ArtifactTreeTypeGroup[] = []
    for (const ty of p.types) {
      const arts = ty.artifacts.filter(a => a.title.toLowerCase().includes(q))
      if (arts.length)
        types.push({ ...ty, artifacts: arts })
    }
    if (types.length)
      out.push({ ...p, types })
  }
  return out
})

// 搜索无命中（区别于整树本就为空）。
const isSearchEmpty = computed(() => normalizedQuery.value.length > 0 && filteredProjects.value.length === 0)

// 命中标题分段高亮（禁用 v-html，纯文本分段渲染避免 XSS）。
interface HighlightSegment { text: string, hit: boolean }
function highlightTitle(title: string): HighlightSegment[] {
  const q = normalizedQuery.value
  if (!q)
    return [{ text: title, hit: false }]
  const segments: HighlightSegment[] = []
  const lower = title.toLowerCase()
  let cursor = 0
  while (cursor < title.length) {
    const idx = lower.indexOf(q, cursor)
    if (idx === -1) {
      segments.push({ text: title.slice(cursor), hit: false })
      break
    }
    if (idx > cursor)
      segments.push({ text: title.slice(cursor, idx), hit: false })
    segments.push({ text: title.slice(idx, idx + q.length), hit: true })
    cursor = idx + q.length
  }
  return segments
}

// ── 展开状态：默认全部展开；搜索时命中路径祖先自动展开 ──
const expandedProjects = ref(new Set<string>())
const expandedTypes = ref(new Set<string>())

function typeId(projectId: string, typeKey: string): string {
  return `${projectId}:${typeKey}`
}

watch(data, (tree) => {
  if (!tree)
    return
  const projs = new Set<string>()
  const types = new Set<string>()
  for (const p of tree.projects) {
    projs.add(p.project_id)
    for (const ty of p.types)
      types.add(typeId(p.project_id, ty.type_key))
  }
  expandedProjects.value = projs
  expandedTypes.value = types
}, { immediate: true })

function isProjectOpen(projectId: string): boolean {
  // 搜索时全展开命中路径；清空搜索恢复用户手动展开态。
  return normalizedQuery.value ? true : expandedProjects.value.has(projectId)
}

function isTypeOpen(projectId: string, typeKey: string): boolean {
  return normalizedQuery.value ? true : expandedTypes.value.has(typeId(projectId, typeKey))
}

function toggleProject(projectId: string): void {
  const next = new Set(expandedProjects.value)
  if (next.has(projectId))
    next.delete(projectId)
  else
    next.add(projectId)
  expandedProjects.value = next
}

function toggleType(projectId: string, typeKey: string): void {
  const key = typeId(projectId, typeKey)
  const next = new Set(expandedTypes.value)
  if (next.has(key))
    next.delete(key)
  else
    next.add(key)
  expandedTypes.value = next
}

function formatDate(updatedAt: string | null): string {
  if (!updatedAt)
    return ''
  return new Date(updatedAt).toLocaleDateString()
}

// ── 叶子查看（复用 Phase 96 范式：external_link 新标签，文字载体 markdown 弹窗）──
const viewOpen = ref(false)
const viewLoading = ref(false)
const viewData = ref<ArtifactView | null>(null)
const viewTitle = ref('')

async function openLeafView(projectId: string, leaf: ArtifactTreeLeaf): Promise<void> {
  viewTitle.value = leaf.title
  viewData.value = null
  viewOpen.value = true
  viewLoading.value = true
  try {
    viewData.value = await artifactsApi.view(projectId, leaf.artifact_id)
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
  <div data-testid="artifact-tree">
    <!-- 加载态 -->
    <div v-if="isLoading" class="flex items-center justify-center py-20 text-muted-foreground">
      <span class="icon-[lucide--loader-2] mr-2 h-5 w-5 animate-spin" />
      {{ t('knowledge.tree.docs.loading') }}
    </div>

    <!-- 错误态：后端 5xx / 网络异常时区别于空态，提供重试（避免误导「暂无文档」）。stale 缓存命中则继续渲染树。 -->
    <div v-else-if="isError && !data" class="flex min-h-[380px] items-center justify-center">
      <CompactEmptyState
        icon="lucide--triangle-alert"
        :title="t('knowledge.tree.docs.error.title')"
        :description="t('knowledge.tree.docs.error.body')"
      >
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-sm font-medium transition-colors hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="isFetching"
          data-testid="artifact-tree-retry"
          @click="refetch()"
        >
          <span
            class="h-3.5 w-3.5 shrink-0"
            :class="isFetching ? 'icon-[lucide--loader-2] animate-spin' : 'icon-[lucide--refresh-cw]'"
          />
          {{ t('knowledge.tree.docs.error.retry') }}
        </button>
      </CompactEmptyState>
    </div>

    <!-- 整树空态：指向作战室「外部依赖」维护入口 -->
    <div v-else-if="!data || data.total === 0 || data.projects.length === 0" class="flex min-h-[380px] items-center justify-center">
      <CompactEmptyState
        icon="lucide--folder-tree"
        :title="t('knowledge.tree.docs.empty.title')"
        :description="t('knowledge.tree.docs.empty.body')"
      />
    </div>

    <!-- 树内容 -->
    <div v-else class="space-y-2">
      <!-- 树内搜索框 -->
      <div class="relative max-w-md">
        <span class="icon-[lucide--search] absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          v-model="searchQuery"
          type="text"
          class="h-9 w-full rounded-lg border border-border bg-background pl-9 pr-3 text-sm outline-none focus:ring-2 focus:ring-primary/30"
          :placeholder="t('knowledge.tree.docs.searchPlaceholder')"
          data-testid="artifact-tree-search"
        >
      </div>

      <!-- 截断提示 -->
      <div
        v-if="data.truncated"
        class="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400"
      >
        <span class="icon-[lucide--info] h-3.5 w-3.5 shrink-0" />
        {{ t('knowledge.tree.docs.truncated') }}
      </div>

      <!-- 搜索无命中空态（区别于整树空态） -->
      <div v-if="isSearchEmpty" class="flex min-h-[320px] items-center justify-center">
        <CompactEmptyState
          icon="lucide--file-x"
          :title="t('knowledge.tree.docs.noMatch.title')"
          :description="t('knowledge.tree.docs.noMatch.body')"
        />
      </div>

      <div v-else class="max-h-[64vh] space-y-1 overflow-y-auto pr-1">
        <!-- 项目节点（顶层） -->
        <div v-for="project in filteredProjects" :key="project.project_id">
          <button
            type="button"
            class="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted/60"
            @click="toggleProject(project.project_id)"
          >
            <span
              class="h-3.5 w-3.5 shrink-0 text-muted-foreground"
              :class="isProjectOpen(project.project_id) ? 'icon-[lucide--chevron-down]' : 'icon-[lucide--chevron-right]'"
            />
            <span class="icon-[lucide--folder] h-4 w-4 shrink-0 text-muted-foreground" />
            <span class="flex-1 truncate text-sm font-medium">{{ project.project_name }}</span>
            <span class="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{{ project.count }}</span>
          </button>

          <!-- 类型节点（二层） -->
          <div v-if="isProjectOpen(project.project_id)" class="ml-4 space-y-1 border-l border-border/60 pl-2">
            <div v-for="typeGroup in project.types" :key="typeGroup.type_key">
              <button
                type="button"
                class="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left transition-colors hover:bg-muted/60"
                @click="toggleType(project.project_id, typeGroup.type_key)"
              >
                <span
                  class="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                  :class="isTypeOpen(project.project_id, typeGroup.type_key) ? 'icon-[lucide--chevron-down]' : 'icon-[lucide--chevron-right]'"
                />
                <span
                  class="inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-medium"
                  :class="ARTIFACT_BADGE_CLASS"
                >
                  {{ typeGroup.type_name }}
                </span>
                <span class="flex-1" />
                <span class="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{{ typeGroup.count }}</span>
              </button>

              <!-- 叶子（三层）：external_link 新标签打开；文字载体点击查看弹窗 -->
              <div v-if="isTypeOpen(project.project_id, typeGroup.type_key)" class="ml-4 space-y-0.5 border-l border-border/60 pl-2">
                <template v-for="leaf in typeGroup.artifacts" :key="leaf.artifact_id">
                  <a
                    v-if="leaf.carrier === 'external_link'"
                    :href="leaf.url"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="flex items-center gap-2 rounded-md px-2 py-1 text-sm transition-colors hover:bg-muted/60"
                    data-testid="artifact-leaf"
                  >
                    <span :class="carrierIcon(leaf.carrier)" class="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span class="flex-1 truncate text-primary hover:underline">
                      <template v-for="(seg, i) in highlightTitle(leaf.title)" :key="i">
                        <mark v-if="seg.hit" class="rounded bg-amber-500/20 px-0.5 text-foreground">{{ seg.text }}</mark>
                        <template v-else>{{ seg.text }}</template>
                      </template>
                    </span>
                    <span class="icon-[lucide--external-link] h-3 w-3 shrink-0 text-muted-foreground/70" />
                    <span v-if="leaf.updated_at" class="shrink-0 text-[11px] text-muted-foreground">{{ formatDate(leaf.updated_at) }}</span>
                  </a>
                  <button
                    v-else
                    type="button"
                    class="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-sm transition-colors hover:bg-muted/60"
                    data-testid="artifact-leaf"
                    @click="openLeafView(project.project_id, leaf)"
                  >
                    <span :class="carrierIcon(leaf.carrier)" class="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span class="flex-1 truncate">
                      <template v-for="(seg, i) in highlightTitle(leaf.title)" :key="i">
                        <mark v-if="seg.hit" class="rounded bg-amber-500/20 px-0.5 text-foreground">{{ seg.text }}</mark>
                        <template v-else>{{ seg.text }}</template>
                      </template>
                    </span>
                    <span v-if="leaf.updated_at" class="shrink-0 text-[11px] text-muted-foreground">{{ formatDate(leaf.updated_at) }}</span>
                  </button>
                </template>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 工件在线查看弹窗（复用 index.vue Phase 96 范式） -->
    <Dialog v-model:open="viewOpen">
      <DialogScrollContent class="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{{ viewTitle }}</DialogTitle>
          <DialogDescription>{{ t('projects.artifacts.viewDesc') }}</DialogDescription>
        </DialogHeader>
        <div class="mt-2">
          <div v-if="viewLoading" class="text-sm text-muted-foreground py-6 text-center">
            {{ t('knowledge.search.loading') }}
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
              class="max-h-[60vh] overflow-auto"
            >
              <MarkdownRenderer :content="viewData.content || ''" />
            </div>
            <pre
              v-else-if="viewData.render_type === 'text'"
              class="text-xs bg-muted/50 rounded-lg p-3 max-h-[60vh] overflow-auto whitespace-pre-wrap"
            >{{ viewData.content }}</pre>
            <div v-else-if="viewData.render_type === 'records'" class="text-xs space-y-1 max-h-[60vh] overflow-auto">
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
  </div>
</template>
