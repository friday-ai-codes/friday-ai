<script setup lang="ts">
/**
 * 仓库章程详情分区：读取 / AI 起草 / 手动填写 / 人工确认。
 * 卡片壳对齐 AISummarySection；写路径显式抛错以便 toast，不回显上游原始响应体。
 */
import type {
  RepoCharter,
  RepoCharterBoundary,
  RepoCharterEvolution,
  RepoCharterFields,
  RepoCharterOwnedDomain,
  RepoCharterPlacementPreference,
} from '~/api/repositoryChunks'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiError } from '~/api/client'
import {
  confirmRepositoryCharter,
  draftRepositoryCharter,
  fetchRepositoryCharter,
} from '~/api/repositoryChunks'
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
import { Skeleton } from '~/components/ui/skeleton'
import { Textarea } from '~/components/ui/textarea'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const props = defineProps<{
  repositoryId: string
}>()

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { success: toastSuccess, warning: toastWarning } = useToast()
const { confirm } = useConfirmDialog()

const loading = ref(true)
const submitting = ref(false)
const drafting = ref(false)
const editing = ref(false)
const charter = ref<RepoCharter | null>(null)

const form = reactive<{
  positioning: string
  audience: string
  form: string
  evolution: RepoCharterEvolution
  owned_domains: RepoCharterOwnedDomain[]
  boundaries: RepoCharterBoundary[]
  placement_preferences: RepoCharterPlacementPreference[]
}>({
  positioning: '',
  audience: '',
  form: '',
  evolution: 'active',
  owned_domains: [],
  boundaries: [],
  placement_preferences: [],
})

const hasPendingDraft = computed(() => {
  const draft = charter.value?.draft_content
  if (!draft || typeof draft !== 'object')
    return false
  return Object.keys(draft).length > 0
})

const sourceLabel = computed(() => {
  const source = charter.value?.source
  if (source === 'human_confirmed')
    return t('repositories.charter.sourceHumanConfirmed')
  if (source === 'ai_draft')
    return t('repositories.charter.sourceAiDraft')
  return source || '—'
})

const evolutionLabel = computed(() => evolutionText(charter.value?.evolution))

function evolutionText(value: unknown): string {
  switch (value) {
    case 'maintenance_only':
      return t('repositories.charter.evolutionMaintenance')
    case 'deprecated':
      return t('repositories.charter.evolutionDeprecated')
    case 'active':
      return t('repositories.charter.evolutionActive')
    default:
      return typeof value === 'string' && value ? value : '—'
  }
}

function emptyForm() {
  form.positioning = ''
  form.audience = ''
  form.form = ''
  form.evolution = 'active'
  form.owned_domains = []
  form.boundaries = []
  form.placement_preferences = []
}

function asDomainList(value: unknown): RepoCharterOwnedDomain[] {
  if (!Array.isArray(value))
    return []
  return value
    .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
    .map(item => ({
      domain: String(item.domain ?? ''),
      status: (item.status === 'planned' ? 'planned' : 'implemented') as 'implemented' | 'planned',
      note: String(item.note ?? ''),
      citations: Array.isArray(item.citations) ? item.citations.map(String) : [],
    }))
}

function asBoundaryList(value: unknown): RepoCharterBoundary[] {
  if (!Array.isArray(value))
    return []
  return value
    .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
    .map(item => ({
      rule: String(item.rule ?? ''),
      decided_by: String(item.decided_by ?? ''),
      citations: Array.isArray(item.citations) ? item.citations.map(String) : [],
    }))
}

function asPlacementList(value: unknown): RepoCharterPlacementPreference[] {
  if (!Array.isArray(value))
    return []
  return value
    .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
    .map(item => ({
      kind: String(item.kind ?? ''),
      target: String(item.target ?? ''),
      note: String(item.note ?? ''),
    }))
}

function applyCharterToForm(data: RepoCharter | null, preferDraft = false) {
  if (!data) {
    emptyForm()
    return
  }
  const draft = preferDraft && hasPendingDraft.value
    ? (data.draft_content as Partial<RepoCharterFields>)
    : null
  const src = draft || data
  form.positioning = String(src.positioning ?? data.positioning ?? '')
  form.audience = String(src.audience ?? data.audience ?? '')
  form.form = String(src.form ?? data.form ?? '')
  const evo = String(src.evolution ?? data.evolution ?? 'active')
  form.evolution = (['active', 'maintenance_only', 'deprecated'].includes(evo)
    ? evo
    : 'active') as RepoCharterEvolution
  form.owned_domains = asDomainList(src.owned_domains ?? data.owned_domains)
  form.boundaries = asBoundaryList(src.boundaries ?? data.boundaries)
  form.placement_preferences = asPlacementList(
    src.placement_preferences ?? data.placement_preferences,
  )
}

function buildEdits(): Partial<RepoCharterFields> {
  return {
    positioning: form.positioning.trim(),
    audience: form.audience.trim(),
    form: form.form.trim(),
    evolution: form.evolution,
    owned_domains: form.owned_domains
      .map(row => ({
        domain: row.domain.trim(),
        status: row.status === 'planned' ? 'planned' : 'implemented',
        note: (row.note || '').trim(),
        citations: row.citations || [],
      }))
      .filter(row => row.domain),
    boundaries: form.boundaries
      .map(row => ({
        rule: row.rule.trim(),
        decided_by: (row.decided_by || '').trim(),
        citations: row.citations || [],
      }))
      .filter(row => row.rule),
    placement_preferences: form.placement_preferences
      .map(row => ({
        kind: row.kind.trim(),
        target: row.target.trim(),
        note: (row.note || '').trim(),
      }))
      .filter(row => row.kind || row.target),
  }
}

async function loadCharter() {
  loading.value = true
  try {
    charter.value = await fetchRepositoryCharter(props.repositoryId)
    if (!editing.value)
      applyCharterToForm(charter.value, hasPendingDraft.value)
  }
  catch (e: unknown) {
    handleError(e, t('repositories.charter.loadFailed'))
  }
  finally {
    loading.value = false
  }
}

function startManualEdit() {
  applyCharterToForm(charter.value, hasPendingDraft.value)
  editing.value = true
}

function cancelEdit() {
  editing.value = false
  applyCharterToForm(charter.value, false)
}

async function handleAiDraft() {
  drafting.value = true
  try {
    charter.value = await draftRepositoryCharter(props.repositoryId)
    applyCharterToForm(charter.value, hasPendingDraft.value)
    editing.value = true
    toastSuccess(t('repositories.charter.draftSuccess'))
  }
  catch (e: unknown) {
    if (e instanceof ApiError && e.status === 503) {
      toastWarning(t('repositories.charter.draftUnavailable'))
      return
    }
    handleError(e, t('repositories.charter.draftFailed'))
  }
  finally {
    drafting.value = false
  }
}

async function handleSaveConfirm() {
  const ok = await confirm({
    title: t('repositories.charter.confirmTitle'),
    description: t('repositories.charter.confirmDescription'),
    confirmText: t('repositories.charter.confirmAction'),
  })
  if (!ok)
    return

  submitting.value = true
  try {
    const edits = buildEdits()
    charter.value = await confirmRepositoryCharter(props.repositoryId, edits)
    editing.value = false
    applyCharterToForm(charter.value, false)
    toastSuccess(t('repositories.charter.confirmSuccess'))
  }
  catch (e: unknown) {
    handleError(e, t('repositories.charter.confirmFailed'))
  }
  finally {
    submitting.value = false
  }
}

function addDomain() {
  form.owned_domains.push({ domain: '', status: 'implemented', note: '' })
}
function addBoundary() {
  form.boundaries.push({ rule: '', decided_by: '' })
}
function addPlacement() {
  form.placement_preferences.push({ kind: '', target: '', note: '' })
}

onMounted(loadCharter)
watch(() => props.repositoryId, () => {
  editing.value = false
  loadCharter()
})
</script>

<template>
  <div class="card overflow-hidden" data-testid="repo-charter-section">
    <div class="flex items-center justify-between px-5 py-3.5 border-b border-border/50 gap-3">
      <div class="flex items-center gap-2 min-w-0">
        <div class="p-1.5 rounded-lg bg-primary/10 shrink-0">
          <span class="icon-[lucide--scroll-text] text-primary" />
        </div>
        <div class="min-w-0">
          <h3 class="text-sm font-semibold text-foreground">
            {{ t('repositories.charter.title') }}
          </h3>
          <p class="text-xs text-muted-foreground truncate">
            {{ t('repositories.charter.subtitle') }}
          </p>
        </div>
      </div>
      <div v-if="charter && !editing" class="flex items-center gap-2 shrink-0">
        <Badge variant="secondary">
          {{ sourceLabel }} · v{{ charter.version }}
        </Badge>
        <Button
          variant="ghost"
          size="sm"
          :disabled="loading || drafting || submitting"
          @click="startManualEdit"
        >
          <span class="icon-[lucide--pencil] mr-1.5" />
          {{ t('repositories.charter.edit') }}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          :disabled="loading || drafting || submitting"
          @click="handleAiDraft"
        >
          <span class="icon-[lucide--sparkles] mr-1.5" />
          {{ t('repositories.charter.aiDraft') }}
        </Button>
      </div>
    </div>

    <div class="p-5">
      <div v-if="loading" class="space-y-3" data-testid="repo-charter-loading">
        <Skeleton class="h-4 w-1/3" />
        <Skeleton class="h-20 w-full" />
        <Skeleton class="h-4 w-1/2" />
      </div>

      <!-- 空态 -->
      <div
        v-else-if="!charter && !editing"
        class="flex flex-col items-center justify-center py-6 space-y-3"
        data-testid="repo-charter-empty"
      >
        <span class="icon-[lucide--scroll-text] text-2xl text-muted-foreground/40" />
        <p class="text-sm font-semibold text-foreground">
          {{ t('repositories.charter.emptyTitle') }}
        </p>
        <p class="text-xs text-muted-foreground text-center max-w-sm">
          {{ t('repositories.charter.emptyDescription') }}
        </p>
        <div class="flex items-center gap-2">
          <Button
            variant="default"
            size="sm"
            :disabled="drafting || submitting"
            data-testid="repo-charter-ai-draft"
            @click="handleAiDraft"
          >
            <span class="icon-[lucide--sparkles] mr-1.5" />
            {{ t('repositories.charter.aiDraft') }}
          </Button>
          <Button
            variant="outline"
            size="sm"
            :disabled="drafting || submitting"
            data-testid="repo-charter-manual-fill"
            @click="startManualEdit"
          >
            <span class="icon-[lucide--pencil] mr-1.5" />
            {{ t('repositories.charter.manualFill') }}
          </Button>
        </div>
      </div>

      <!-- 编辑态 -->
      <div v-else-if="editing" class="space-y-5" data-testid="repo-charter-editor">
        <div class="space-y-2">
          <label class="text-xs text-muted-foreground">{{ t('repositories.charter.positioning') }}</label>
          <Textarea
            v-model="form.positioning"
            rows="3"
            :placeholder="t('repositories.charter.placeholderPositioning')"
          />
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div class="space-y-2">
            <label class="text-xs text-muted-foreground">{{ t('repositories.charter.audience') }}</label>
            <Input v-model="form.audience" :placeholder="t('repositories.charter.placeholderAudience')" />
          </div>
          <div class="space-y-2">
            <label class="text-xs text-muted-foreground">{{ t('repositories.charter.form') }}</label>
            <Input v-model="form.form" :placeholder="t('repositories.charter.placeholderForm')" />
          </div>
          <div class="space-y-2">
            <label class="text-xs text-muted-foreground">{{ t('repositories.charter.evolution') }}</label>
            <Select v-model="form.evolution">
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="active">
                  {{ t('repositories.charter.evolutionActive') }}
                </SelectItem>
                <SelectItem value="maintenance_only">
                  {{ t('repositories.charter.evolutionMaintenance') }}
                </SelectItem>
                <SelectItem value="deprecated">
                  {{ t('repositories.charter.evolutionDeprecated') }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <!-- owned_domains -->
        <div class="space-y-2">
          <div class="flex items-center justify-between">
            <label class="text-xs text-muted-foreground">{{ t('repositories.charter.ownedDomains') }}</label>
            <Button variant="ghost" size="sm" class="h-7 text-xs" @click="addDomain">
              {{ t('repositories.charter.addRow') }}
            </Button>
          </div>
          <div
            v-for="(row, idx) in form.owned_domains"
            :key="`domain-${idx}`"
            class="grid grid-cols-1 sm:grid-cols-[1fr_140px_1fr_auto] gap-2"
          >
            <Input v-model="row.domain" :placeholder="t('repositories.charter.domain')" />
            <Select v-model="row.status">
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="implemented">
                  {{ t('repositories.charter.statusImplemented') }}
                </SelectItem>
                <SelectItem value="planned">
                  {{ t('repositories.charter.statusPlanned') }}
                </SelectItem>
              </SelectContent>
            </Select>
            <Input v-model="row.note" :placeholder="t('repositories.charter.note')" />
            <Button variant="ghost" size="sm" class="h-9 px-2" @click="form.owned_domains.splice(idx, 1)">
              {{ t('repositories.charter.removeRow') }}
            </Button>
          </div>
        </div>

        <!-- boundaries -->
        <div class="space-y-2">
          <div class="flex items-center justify-between">
            <label class="text-xs text-muted-foreground">{{ t('repositories.charter.boundaries') }}</label>
            <Button variant="ghost" size="sm" class="h-7 text-xs" @click="addBoundary">
              {{ t('repositories.charter.addRow') }}
            </Button>
          </div>
          <div
            v-for="(row, idx) in form.boundaries"
            :key="`boundary-${idx}`"
            class="grid grid-cols-1 sm:grid-cols-[1fr_160px_auto] gap-2"
          >
            <Input v-model="row.rule" :placeholder="t('repositories.charter.rule')" />
            <Input v-model="row.decided_by" :placeholder="t('repositories.charter.decidedBy')" />
            <Button variant="ghost" size="sm" class="h-9 px-2" @click="form.boundaries.splice(idx, 1)">
              {{ t('repositories.charter.removeRow') }}
            </Button>
          </div>
        </div>

        <!-- placement -->
        <div class="space-y-2">
          <div class="flex items-center justify-between">
            <label class="text-xs text-muted-foreground">{{ t('repositories.charter.placement') }}</label>
            <Button variant="ghost" size="sm" class="h-7 text-xs" @click="addPlacement">
              {{ t('repositories.charter.addRow') }}
            </Button>
          </div>
          <div
            v-for="(row, idx) in form.placement_preferences"
            :key="`placement-${idx}`"
            class="grid grid-cols-1 sm:grid-cols-[1fr_1fr_1fr_auto] gap-2"
          >
            <Input v-model="row.kind" :placeholder="t('repositories.charter.kind')" />
            <Input v-model="row.target" :placeholder="t('repositories.charter.target')" />
            <Input v-model="row.note" :placeholder="t('repositories.charter.note')" />
            <Button
              variant="ghost"
              size="sm"
              class="h-9 px-2"
              @click="form.placement_preferences.splice(idx, 1)"
            >
              {{ t('repositories.charter.removeRow') }}
            </Button>
          </div>
        </div>

        <div class="flex items-center justify-end gap-2 pt-2">
          <Button
            variant="ghost"
            size="sm"
            :disabled="submitting || drafting"
            @click="cancelEdit"
          >
            {{ t('repositories.charter.cancel') }}
          </Button>
          <Button
            variant="default"
            size="sm"
            :disabled="submitting || drafting"
            data-testid="repo-charter-save-confirm"
            @click="handleSaveConfirm"
          >
            <span v-if="submitting" class="icon-[lucide--loader-2] mr-1.5 animate-spin" />
            {{ t('repositories.charter.saveConfirm') }}
          </Button>
        </div>
      </div>

      <!-- 只读展示 -->
      <div v-else-if="charter" class="space-y-4" data-testid="repo-charter-readonly">
        <div
          v-if="hasPendingDraft"
          class="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 space-y-1"
          data-testid="repo-charter-pending-draft"
        >
          <p class="text-sm font-medium text-foreground">
            {{ t('repositories.charter.pendingDraft') }}
          </p>
          <p class="text-xs text-muted-foreground">
            {{ t('repositories.charter.pendingDraftHint') }}
          </p>
          <pre class="text-xs font-mono whitespace-pre-wrap wrap-break-word text-muted-foreground mt-2">{{ JSON.stringify(charter.draft_content, null, 2) }}</pre>
        </div>

        <div class="space-y-1">
          <label class="text-xs text-muted-foreground">{{ t('repositories.charter.positioning') }}</label>
          <p class="text-sm text-foreground whitespace-pre-wrap">
            {{ charter.positioning || '—' }}
          </p>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div>
            <label class="text-xs text-muted-foreground">{{ t('repositories.charter.audience') }}</label>
            <p class="text-sm mt-1">
              {{ charter.audience || '—' }}
            </p>
          </div>
          <div>
            <label class="text-xs text-muted-foreground">{{ t('repositories.charter.form') }}</label>
            <p class="text-sm mt-1">
              {{ charter.form || '—' }}
            </p>
          </div>
          <div>
            <label class="text-xs text-muted-foreground">{{ t('repositories.charter.evolution') }}</label>
            <p class="text-sm mt-1">
              {{ evolutionLabel }}
            </p>
          </div>
        </div>

        <div>
          <label class="text-xs text-muted-foreground">{{ t('repositories.charter.ownedDomains') }}</label>
          <ul v-if="asDomainList(charter.owned_domains).length" class="mt-1 space-y-1">
            <li
              v-for="(row, idx) in asDomainList(charter.owned_domains)"
              :key="`ro-domain-${idx}`"
              class="text-sm"
            >
              <span class="font-medium">{{ row.domain }}</span>
              <span class="text-muted-foreground"> · {{ row.status }}</span>
              <span v-if="row.note" class="text-muted-foreground"> — {{ row.note }}</span>
            </li>
          </ul>
          <p v-else class="text-sm mt-1 text-muted-foreground">
            —
          </p>
        </div>

        <div>
          <label class="text-xs text-muted-foreground">{{ t('repositories.charter.boundaries') }}</label>
          <ul v-if="asBoundaryList(charter.boundaries).length" class="mt-1 space-y-1">
            <li
              v-for="(row, idx) in asBoundaryList(charter.boundaries)"
              :key="`ro-boundary-${idx}`"
              class="text-sm"
            >
              {{ row.rule }}
              <span v-if="row.decided_by" class="text-muted-foreground">（{{ row.decided_by }}）</span>
            </li>
          </ul>
          <p v-else class="text-sm mt-1 text-muted-foreground">
            —
          </p>
        </div>

        <div>
          <label class="text-xs text-muted-foreground">{{ t('repositories.charter.placement') }}</label>
          <ul v-if="asPlacementList(charter.placement_preferences).length" class="mt-1 space-y-1">
            <li
              v-for="(row, idx) in asPlacementList(charter.placement_preferences)"
              :key="`ro-place-${idx}`"
              class="text-sm"
            >
              <span class="font-medium">{{ row.kind || '—' }}</span>
              → {{ row.target || '—' }}
              <span v-if="row.note" class="text-muted-foreground"> — {{ row.note }}</span>
            </li>
          </ul>
          <p v-else class="text-sm mt-1 text-muted-foreground">
            —
          </p>
        </div>

        <div class="flex flex-wrap gap-4 text-xs text-muted-foreground pt-1 border-t border-border/40">
          <span>{{ t('repositories.charter.source') }}：{{ sourceLabel }}</span>
          <span>{{ t('repositories.charter.version') }}：{{ charter.version }}</span>
          <span>{{ t('repositories.charter.confirmedBy') }}：{{ charter.confirmed_by || '—' }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
