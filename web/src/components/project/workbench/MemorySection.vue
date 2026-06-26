<script setup lang="ts">
import type { ProjectMemory, ProjectMemoryDraft } from '~/api/projectMemory'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { projectMemoryApi } from '~/api/projectMemory'
import MarkdownRenderer from '~/components/execution/MarkdownRenderer.vue'
import { Button } from '~/components/ui/button'
import { Textarea } from '~/components/ui/textarea'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

/**
 * MemorySection — 工作台「文件 → MEMORY」记忆条目 + LLM 草稿确认（WB-03）。
 *
 * 复用 `MemoryTab` 的条目式渲染 / 编辑 / LLM 草稿确认交互，正文改用
 * `MarkdownRenderer`（查看）渲染；编辑走 textarea 源码。采纳/拒绝草稿均经
 * `useConfirmDialog` 二次确认，分别调 `confirmDraft` / `rejectDraft`，避免共享
 * 记忆被未审阅的 LLM 提议污染（归因由后端记录）。
 */
const props = defineProps<{ projectId: string }>()

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { confirm } = useConfirmDialog()
const { success } = useToast()
const queryClient = useQueryClient()

const projectIdRef = toRef(props, 'projectId')

const memoriesQuery = useQuery({
  queryKey: ['project-memories', projectIdRef],
  queryFn: () => projectMemoryApi.list(props.projectId),
})
const draftsQuery = useQuery({
  queryKey: ['project-memory-drafts', projectIdRef],
  queryFn: () => projectMemoryApi.listDrafts(props.projectId),
})

const memories = computed<ProjectMemory[]>(() => memoriesQuery.data.value ?? [])
const pendingDrafts = computed<ProjectMemoryDraft[]>(() =>
  (draftsQuery.data.value ?? []).filter(d => d.status === 'pending'),
)

function invalidate() {
  queryClient.invalidateQueries({ queryKey: ['project-memories', projectIdRef] })
  queryClient.invalidateQueries({ queryKey: ['project-memory-drafts', projectIdRef] })
}

// ---- 新增记忆 ----
const newContent = ref('')
const creating = ref(false)
async function createMemory() {
  const content = newContent.value.trim()
  if (!content)
    return
  creating.value = true
  try {
    await projectMemoryApi.create(props.projectId, content)
    success(t('projects.memory.created'))
    newContent.value = ''
    invalidate()
  }
  catch (e: unknown) {
    handleError(e, t('projects.memory.createFailed'))
  }
  finally {
    creating.value = false
  }
}

// ---- 编辑记忆 ----
const editingId = ref('')
const editContent = ref('')
function startEdit(m: ProjectMemory) {
  editingId.value = m.id
  editContent.value = m.content
}
function cancelEdit() {
  editingId.value = ''
  editContent.value = ''
}
async function saveEdit(m: ProjectMemory) {
  try {
    await projectMemoryApi.edit(props.projectId, m.id, editContent.value)
    success(t('projects.memory.edited'))
    cancelEdit()
    invalidate()
  }
  catch (e: unknown) {
    handleError(e, t('projects.memory.editFailed'))
  }
}

async function supersede(m: ProjectMemory) {
  const ok = await confirm({
    title: t('projects.memory.deleteTitle'),
    description: t('projects.memory.deleteConfirm'),
    confirmText: t('projects.memory.deleteConfirmText'),
    variant: 'destructive',
  })
  if (!ok)
    return
  try {
    await projectMemoryApi.supersede(props.projectId, m.id)
    success(t('projects.memory.deleted'))
    invalidate()
  }
  catch (e: unknown) {
    handleError(e, t('projects.memory.deleteFailed'))
  }
}

// ---- 草稿确认（UI-03）----
const draftEditId = ref('')
const draftEditContent = ref('')
function startDraftEdit(d: ProjectMemoryDraft) {
  draftEditId.value = d.id
  draftEditContent.value = d.content
}
function cancelDraftEdit() {
  draftEditId.value = ''
  draftEditContent.value = ''
}

async function acceptDraft(d: ProjectMemoryDraft) {
  const ok = await confirm({
    title: t('projects.memory.draft.acceptTitle'),
    description: t('projects.memory.draft.acceptConfirm'),
    confirmText: t('projects.memory.draft.acceptConfirmText'),
  })
  if (!ok)
    return
  try {
    await projectMemoryApi.confirmDraft(props.projectId, d.id)
    success(t('projects.memory.draft.accepted'))
    invalidate()
  }
  catch (e: unknown) {
    handleError(e, t('projects.memory.draft.acceptFailed'))
  }
}

async function acceptEditedDraft(d: ProjectMemoryDraft) {
  // 编辑后入库：以编辑内容新增记忆（人工内容入库），再拒绝原草稿。
  const ok = await confirm({
    title: t('projects.memory.draft.acceptTitle'),
    description: t('projects.memory.draft.acceptEditedConfirm'),
    confirmText: t('projects.memory.draft.acceptConfirmText'),
  })
  if (!ok)
    return
  try {
    await projectMemoryApi.create(props.projectId, draftEditContent.value)
    await projectMemoryApi.rejectDraft(props.projectId, d.id)
    success(t('projects.memory.draft.accepted'))
    cancelDraftEdit()
    invalidate()
  }
  catch (e: unknown) {
    handleError(e, t('projects.memory.draft.acceptFailed'))
  }
}

async function rejectDraft(d: ProjectMemoryDraft) {
  const ok = await confirm({
    title: t('projects.memory.draft.rejectTitle'),
    description: t('projects.memory.draft.rejectConfirm'),
    confirmText: t('projects.memory.draft.rejectConfirmText'),
    variant: 'destructive',
  })
  if (!ok)
    return
  try {
    await projectMemoryApi.rejectDraft(props.projectId, d.id)
    success(t('projects.memory.draft.rejected'))
    invalidate()
  }
  catch (e: unknown) {
    handleError(e, t('projects.memory.draft.rejectFailed'))
  }
}
</script>

<template>
  <div class="space-y-6" data-testid="workbench-memory-section">
    <!-- LLM 提议草稿区（UI-03） -->
    <section v-if="pendingDrafts.length > 0" class="space-y-3" data-testid="draft-section">
      <h3 class="text-sm font-semibold text-foreground flex items-center gap-2">
        <span class="icon-[lucide--sparkles] text-primary" />
        {{ t('projects.memory.draft.title') }}
        <span class="px-1.5 py-0.5 rounded-full text-xs bg-primary/10 text-primary">{{ pendingDrafts.length }}</span>
      </h3>
      <ul class="space-y-3">
        <li
          v-for="d in pendingDrafts"
          :key="d.id"
          class="card p-4 border-l-2 border-primary/40 space-y-3"
          data-testid="draft-row"
        >
          <template v-if="draftEditId === d.id">
            <Textarea v-model="draftEditContent" rows="4" class="text-sm" />
            <div class="flex gap-2 justify-end">
              <Button size="sm" variant="ghost" @click="cancelDraftEdit">
                {{ t('projects.memory.draft.cancel') }}
              </Button>
              <Button size="sm" @click="acceptEditedDraft(d)">
                {{ t('projects.memory.draft.acceptEdited') }}
              </Button>
            </div>
          </template>
          <template v-else>
            <MarkdownRenderer :content="d.content" />
            <p class="text-xs text-muted-foreground">
              {{ t('projects.memory.draft.source') }}: {{ d.source_conversation_id || '—' }}
              · {{ new Date(d.created_at).toLocaleString() }}
            </p>
            <div class="flex gap-2 justify-end">
              <Button size="sm" variant="ghost" data-testid="draft-reject" @click="rejectDraft(d)">
                <span class="icon-[lucide--x] mr-1" />
                {{ t('projects.memory.draft.reject') }}
              </Button>
              <Button size="sm" variant="outline" @click="startDraftEdit(d)">
                <span class="icon-[lucide--pencil] mr-1" />
                {{ t('projects.memory.draft.edit') }}
              </Button>
              <Button size="sm" data-testid="draft-accept" @click="acceptDraft(d)">
                <span class="icon-[lucide--check] mr-1" />
                {{ t('projects.memory.draft.accept') }}
              </Button>
            </div>
          </template>
        </li>
      </ul>
    </section>

    <!-- 新增记忆 -->
    <section class="card p-4 space-y-2">
      <Textarea
        v-model="newContent"
        :placeholder="t('projects.memory.addPlaceholder')"
        rows="3"
        class="text-sm"
        data-testid="memory-input"
      />
      <div class="flex justify-end">
        <Button size="sm" :disabled="creating || !newContent.trim()" @click="createMemory">
          <span class="icon-[lucide--plus] mr-1.5" />
          {{ t('projects.memory.add') }}
        </Button>
      </div>
    </section>

    <!-- 记忆时间线 -->
    <section class="space-y-3">
      <h3 class="text-sm font-semibold text-foreground">
        {{ t('projects.memory.timeline') }}
      </h3>
      <div v-if="memoriesQuery.isLoading.value" class="text-sm text-muted-foreground py-6 text-center">
        {{ t('projects.loading') }}
      </div>
      <div v-else-if="memoriesQuery.isError.value" class="text-sm text-destructive py-6 text-center">
        {{ t('projects.memory.loadError') }}
      </div>
      <div v-else-if="memories.length === 0" class="text-sm text-muted-foreground py-6 text-center">
        {{ t('projects.memory.empty') }}
      </div>
      <ul v-else class="space-y-3">
        <li
          v-for="m in memories"
          :key="m.id"
          class="card p-4 space-y-2"
          data-testid="memory-row"
        >
          <template v-if="editingId === m.id">
            <Textarea v-model="editContent" rows="4" class="text-sm" />
            <div class="flex gap-2 justify-end">
              <Button size="sm" variant="ghost" @click="cancelEdit">
                {{ t('projects.memory.cancel') }}
              </Button>
              <Button size="sm" @click="saveEdit(m)">
                {{ t('projects.memory.save') }}
              </Button>
            </div>
          </template>
          <template v-else>
            <MarkdownRenderer :content="m.content" />
            <div class="flex items-center justify-between gap-2">
              <span class="text-xs text-muted-foreground">
                {{ new Date(m.updated_at).toLocaleString() }}
              </span>
              <div class="flex gap-2">
                <button class="text-xs text-muted-foreground hover:text-primary" @click="startEdit(m)">
                  <span class="icon-[lucide--pencil]" />
                </button>
                <button class="text-xs text-muted-foreground hover:text-destructive" @click="supersede(m)">
                  <span class="icon-[lucide--trash-2]" />
                </button>
              </div>
            </div>
          </template>
        </li>
      </ul>
    </section>
  </div>
</template>
