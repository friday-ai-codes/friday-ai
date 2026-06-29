<script setup lang="ts">
import type {
  DocBlock,
  HumanBlockWrite,
  ProjectDoc,
  ProjectDocContent,
  ProjectDocType,
} from '~/api/projectWorkspace'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, reactive, ref, toRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiError } from '~/api/client'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import MarkdownRenderer from '~/components/execution/MarkdownRenderer.vue'
import MarkdownSourceEditor from '~/components/project/workbench/MarkdownSourceEditor.vue'
import MemorySection from '~/components/project/workbench/MemorySection.vue'
import { Button } from '~/components/ui/button'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

/**
 * DocsSection — 工作区 5 文件查看/编辑（WB-03）。
 *
 * 左侧 5 文件切换（memory/state/milestones/research/preflight，带 sync_status 灯）；
 * 右侧默认查看态用 `MarkdownRenderer` 渲染 `getDocContent` 的 rendered_markdown，
 * 进「编辑源码」态按 block `section` 渲染：system 区只读、human 区可编辑；保存调
 * `updateHumanBlocks`（触发 Phase 83 同步引擎 block 级回灌，前端不直写飞书），成功后
 * 失效查询并按 sync_status 轮询。MEMORY 路由到 `MemorySection`（条目 + 草稿确认）。
 */
const props = defineProps<{ projectId: string }>()

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { success } = useToast()
const queryClient = useQueryClient()

const projectIdRef = toRef(props, 'projectId')

const DOC_TYPES: ProjectDocType[] = ['memory', 'state', 'milestones', 'research', 'preflight']

// #3：5 文件改为竖向可展开子项（accordion），展开项即 activeDocType（单活，复用单内容查询）。
// 默认展开首个（MEMORY.md），进入即可见首个文件内容。
const expanded = ref<ProjectDocType | null>('memory')
const activeDocType = ref<ProjectDocType>('memory')
const mode = ref<'view' | 'edit'>('view')
const isMemory = computed(() => activeDocType.value === 'memory')

// 文件原名（与 i18n 同步，作兜底/可读）。
const DOC_FILENAME: Record<ProjectDocType, string> = {
  memory: 'MEMORY.md',
  state: 'STATE.md',
  milestones: 'MILESTONES.md',
  research: 'RESEARCH.md',
  preflight: 'PREFLIGHT.md',
}

// ── 文件列表元数据（sync_status badge）─────────────────────────
const docsQuery = useQuery({
  queryKey: ['project-docs', projectIdRef],
  queryFn: () => projectWorkspaceApi.listDocs(props.projectId),
})
const docs = computed<ProjectDoc[]>(() => docsQuery.data.value ?? [])
function docSyncStatus(dt: ProjectDocType): string {
  return docs.value.find(d => d.doc_type === dt)?.sync_status ?? 'idle'
}

// ── 单文档内容 + block 分区（非 memory）──────────────────────────
const docContentQuery = useQuery({
  queryKey: ['project-doc', projectIdRef, activeDocType],
  queryFn: () => projectWorkspaceApi.getDocContent(props.projectId, activeDocType.value),
  enabled: computed(() => !isMemory.value),
  // 派发→轮询：保存后 sync_status=syncing 持续轮询，回 synced/idle 停止。
  refetchInterval: query => (query.state.data?.sync_status === 'syncing' ? 2000 : false),
})
const content = computed<ProjectDocContent | undefined>(() => docContentQuery.data.value)
const blocks = computed<DocBlock[]>(() => content.value?.blocks ?? [])
const hasSystemBlock = computed(() => blocks.value.some(b => b.section === 'system'))
const hasHumanBlock = computed(() => blocks.value.some(b => b.section === 'human' && b.editable))

// ── 人工区编辑草稿（block_id → text）──────────────────────────
const humanDrafts = reactive<Record<string, string>>({})
function resetDrafts() {
  for (const k of Object.keys(humanDrafts))
    delete humanDrafts[k]
  for (const b of blocks.value) {
    if (b.section === 'human' && b.editable)
      humanDrafts[b.block_id] = b.text
  }
}

// 切到查看态或换文件时清编辑态（避免脏草稿跨文件残留）。
watch(activeDocType, () => {
  mode.value = 'view'
})

function toggleDoc(dt: ProjectDocType) {
  if (expanded.value === dt) {
    expanded.value = null
    return
  }
  expanded.value = dt
  activeDocType.value = dt
  mode.value = 'view'
}

function enterEdit() {
  resetDrafts()
  mode.value = 'edit'
}
function cancelEdit() {
  mode.value = 'view'
}

// ── 保存（人工区写回 → 同步引擎回灌）────────────────────────────
const saveMutation = useMutation({
  mutationFn: () => {
    const payload: HumanBlockWrite[] = blocks.value
      .filter(b => b.section === 'human' && b.editable)
      .map(b => ({ block_id: b.block_id, text: humanDrafts[b.block_id] ?? b.text }))
    return projectWorkspaceApi.updateHumanBlocks(props.projectId, activeDocType.value, payload)
  },
  onSuccess: () => {
    success(t('projects.workbench.docs.saved'))
    queryClient.invalidateQueries({ queryKey: ['project-doc', projectIdRef, activeDocType] })
    mode.value = 'view'
  },
  onError: (e: unknown) => {
    // 飞书侧已有更新（保存冲突 409/422）：保留改动、停留编辑态，提示重新编辑。
    if (e instanceof ApiError && (e.status === 409 || e.status === 422)) {
      handleError(e, t('projects.workbench.docs.saveConflict'))
      return
    }
    handleError(e, t('projects.workbench.docs.saveFailed'))
  },
})
const isSaving = computed(() => saveMutation.isPending.value)

function syncDotClass(status: string): string {
  switch (status) {
    case 'syncing':
      return 'bg-amber-500 animate-pulse'
    case 'error':
      return 'bg-destructive'
    case 'synced':
      return 'bg-emerald-500'
    default:
      return 'bg-muted-foreground/40'
  }
}
</script>

<template>
  <section class="card" data-testid="workbench-docs-section">
    <header class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2.5">
      <span class="section-chip"><span class="icon-[lucide--files]" /></span>
      <h2 class="text-sm font-semibold text-foreground">
        {{ t('projects.workbench.docs.title') }}
      </h2>
    </header>

    <!-- #3：5 文件竖向平铺为可展开子项，展示原名（MEMORY.md 等），展开后在线查看/编辑/新增 -->
    <div class="p-5 space-y-2" :aria-label="t('projects.workbench.docs.fileNavLabel')">
      <div
        v-for="dt in DOC_TYPES"
        :key="dt"
        class="rounded-lg border border-border/40 overflow-hidden"
      >
        <!-- 子项头：文件名 + 同步灯 + 展开箭头 -->
        <button
          type="button"
          class="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left hover:bg-muted/40 transition-colors"
          :aria-expanded="expanded === dt"
          :data-testid="`doc-file-${dt}`"
          @click="toggleDoc(dt)"
        >
          <span
            class="icon-[lucide--chevron-right] text-xs text-muted-foreground transition-transform shrink-0"
            :class="expanded === dt ? 'rotate-90' : ''"
          />
          <span class="icon-[lucide--file-text] text-muted-foreground shrink-0" />
          <code class="text-sm font-mono text-foreground">{{ DOC_FILENAME[dt] }}</code>
          <span class="size-2 rounded-full shrink-0 ml-auto" :class="syncDotClass(docSyncStatus(dt))" />
        </button>

        <!-- 展开内容 -->
        <div v-if="expanded === dt" class="border-t border-border/40 p-3.5">
          <!-- MEMORY：条目 + 草稿确认（已带贡献者归因） -->
          <MemorySection v-if="dt === 'memory'" :project-id="projectId" />

          <!-- 其余 4 文件：查看（渲染）/编辑（源码） -->
          <template v-else>
            <div v-if="docContentQuery.isLoading.value" class="text-sm text-muted-foreground py-6 text-center">
              {{ t('projects.loading') }}
            </div>
            <div v-else-if="docContentQuery.isError.value" class="py-6 text-center space-y-2">
              <p class="text-sm text-destructive">
                {{ t('projects.workbench.docs.loadError') }}
              </p>
              <button class="text-sm text-primary underline" @click="() => docContentQuery.refetch()">
                {{ t('projects.retry') }}
              </button>
            </div>

            <template v-else>
              <!-- 操作条：查看/编辑切换 + 保存 -->
              <div class="flex items-center justify-between gap-2 mb-3">
                <span class="text-xs text-muted-foreground inline-flex items-center gap-1.5">
                  <span class="size-2 rounded-full" :class="syncDotClass(content?.sync_status ?? 'idle')" />
                  <template v-if="content?.sync_status === 'syncing'">{{ t('projects.workbench.overview.syncing') }}</template>
                  <template v-else-if="content?.sync_status === 'error'">{{ t('projects.workbench.overview.syncError') }}</template>
                  <template v-else-if="content?.sync_status === 'synced'">{{ t('projects.workbench.overview.synced') }}</template>
                  <template v-else>{{ t('projects.workbench.overview.syncIdle') }}</template>
                </span>
                <div class="flex items-center gap-2">
                  <Button
                    v-if="mode === 'view'"
                    size="sm"
                    variant="outline"
                    data-testid="doc-edit-toggle"
                    @click="enterEdit"
                  >
                    <span class="icon-[lucide--pencil] mr-1.5" />
                    {{ t('projects.workbench.docs.edit') }}
                  </Button>
                  <template v-else>
                    <Button size="sm" variant="ghost" :disabled="isSaving" data-testid="doc-cancel-btn" @click="cancelEdit">
                      {{ t('projects.workbench.docs.cancel') }}
                    </Button>
                    <Button
                      size="sm"
                      :disabled="isSaving || !hasHumanBlock"
                      data-testid="doc-save-btn"
                      @click="() => saveMutation.mutate()"
                    >
                      <span class="icon-[lucide--cloud-upload] mr-1.5" :class="isSaving ? 'animate-spin' : ''" />
                      {{ isSaving ? t('projects.workbench.docs.saving') : t('projects.workbench.docs.save') }}
                    </Button>
                  </template>
                </div>
              </div>

              <!-- 查看态：markdown 实时渲染 -->
              <div v-if="mode === 'view'" data-testid="doc-view">
                <div v-if="!content?.rendered_markdown" class="text-sm text-muted-foreground py-6 text-center">
                  {{ t('projects.workbench.docs.empty') }}
                </div>
                <MarkdownRenderer v-else :content="content.rendered_markdown" />
              </div>

              <!-- 编辑态：CodeMirror 源码，系统区只读 / 人工区可编辑 -->
              <div v-else class="space-y-4" data-testid="doc-edit">
                <div
                  v-if="hasSystemBlock"
                  class="flex items-start gap-2 text-xs text-muted-foreground bg-muted/40 border border-border/50 rounded-lg px-3 py-2.5"
                  data-testid="doc-system-hint"
                >
                  <span class="icon-[lucide--lock] mt-0.5 shrink-0" />
                  <span>{{ t('projects.workbench.docs.systemReadonly') }}</span>
                </div>

                <p v-if="!hasHumanBlock" class="text-xs text-muted-foreground" data-testid="doc-no-human">
                  {{ t('projects.workbench.docs.noHumanArea') }}
                </p>

                <div
                  v-for="block in blocks"
                  :key="block.block_id"
                  class="space-y-1.5"
                  :data-testid="`doc-block-${block.section}`"
                >
                  <p
                    v-if="block.section === 'human' && block.editable"
                    class="text-xs font-medium text-foreground"
                  >
                    {{ t('projects.workbench.docs.humanArea') }}
                  </p>
                  <MarkdownSourceEditor
                    v-if="block.section === 'system' || !block.editable"
                    :model-value="block.text"
                    :readonly="true"
                  />
                  <MarkdownSourceEditor
                    v-else
                    :model-value="humanDrafts[block.block_id] ?? block.text"
                    :readonly="false"
                    @update:model-value="(v: string) => { humanDrafts[block.block_id] = v }"
                  />
                </div>
              </div>
            </template>
          </template>
        </div>
      </div>
    </div>
  </section>
</template>
