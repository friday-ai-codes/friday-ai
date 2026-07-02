<script setup lang="ts">
import type MarkdownIt from 'markdown-it'
import type {
  FeatureListDraft,
  FeatureListDraftModule,
  FeatureListDraftPhase,
  FeatureListDraftStatus,
  FeatureListModuleInput,
  FeatureNode,
} from '~/api/projectWorkspace'
import { computed, onMounted, reactive, ref, shallowRef } from 'vue'
import { VueFinalModal } from 'vue-final-modal'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Textarea } from '~/components/ui/textarea'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
import { useProjectEventSocket } from '~/composables/useProjectEventSocket'
import { useToast } from '~/composables/useToast'

// feature list 录入弹窗：模块 → 功能点 → 验收项。支持：加载已有 feature list 增删改、
// 拖动排序；粘贴任意文档（markdown/飞书/gitlab/typora）可预览可编辑；AI「分层渐进式」解析
// （先出模块，再逐模块填功能点）。
const props = defineProps<{ projectId: string }>()
const emit = defineEmits<{ confirm: [], cancel: [], closed: [] }>()

const { handleError } = useErrorHandler()
const { success } = useToast()

// ── 草稿模型（带稳定 key，供拖拽排序时正确复用 DOM）──────────────
let _seq = 0
function uid(): string {
  _seq += 1
  return `d${_seq}`
}
interface FeatureDraft { key: string, name: string, acceptanceText: string, source?: string }
interface ModuleDraft { key: string, module: string, summary?: string, features: FeatureDraft[], parsing?: boolean }
function newFeature(init: Partial<FeatureDraft> = {}): FeatureDraft {
  return { key: uid(), name: '', acceptanceText: '', ...init }
}
function newModule(init: Partial<ModuleDraft> = {}): ModuleDraft {
  return { key: uid(), module: '', features: [newFeature()], ...init }
}
const modules = reactive<ModuleDraft[]>([newModule()])

const totalFeatures = computed(() =>
  modules.reduce((n, m) => n + m.features.filter(f => f.name.trim()).length, 0),
)
function moduleFeatureCount(mod: ModuleDraft): number {
  return mod.features.filter(f => f.name.trim()).length
}
function acceptanceCount(feat: FeatureDraft): number {
  return feat.acceptanceText.split('\n').map(s => s.trim()).filter(Boolean).length
}

function addModule() {
  modules.push(newModule())
}
function removeModule(i: number) {
  modules.splice(i, 1)
  if (modules.length === 0)
    addModule()
}
function addFeature(mi: number) {
  modules[mi].features.push(newFeature())
}
function removeFeature(mi: number, fi: number) {
  modules[mi].features.splice(fi, 1)
  if (modules[mi].features.length === 0)
    modules[mi].features.push(newFeature())
}

// ── 拖拽排序：模块整体排序 + 功能点同模块内排序 ──────────────
const dragModule = ref<number | null>(null)
function onModuleDrop(to: number) {
  const from = dragModule.value
  dragModule.value = null
  if (from === null || from === to)
    return
  const [m] = modules.splice(from, 1)
  modules.splice(to, 0, m)
}
const dragFeat = ref<{ mi: number, fi: number } | null>(null)
function onFeatDrop(mi: number, to: number) {
  const d = dragFeat.value
  dragFeat.value = null
  if (!d || d.mi !== mi || d.fi === to)
    return
  const arr = modules[mi].features
  const [f] = arr.splice(d.fi, 1)
  arr.splice(to, 0, f)
}

// ── 加载已有 feature list（#4：可对已有列表增删改/排序/再解析追加）──────────────
const loadingExisting = ref(true)
async function loadExisting() {
  try {
    const d = await projectWorkspaceApi.getFeatureList(props.projectId) as
      | FeatureNode[]
      | { modules?: FeatureNode[] }
    const mods = Array.isArray(d) ? d : (d?.modules ?? [])
    const drafts = mods.map(m => newModule({
      module: m.name || '',
      summary: m.source || '',
      features: (m.children ?? [])
        .filter(c => c.kind === 'feature')
        .map(f => newFeature({
          name: f.name || '',
          acceptanceText: (f.children ?? [])
            .filter(c => c.kind === 'acceptance')
            .map(c => c.name)
            .join('\n'),
          source: f.source || '',
        })),
    }))
    drafts.forEach((m) => {
      if (!m.features.length)
        m.features.push(newFeature())
    })
    if (drafts.length)
      modules.splice(0, modules.length, ...drafts)
  }
  catch {
    // 新项目无 feature list / 取数失败 → 保持空白录入。
  }
  finally {
    loadingExisting.value = false
  }
}

// ── 粘贴文档（可编辑 / markdown 预览）──────────────
const pasteText = ref('')
const pasteView = ref<'edit' | 'preview'>('edit')
const mdRef = shallowRef<MarkdownIt | null>(null)
const previewHtml = computed(() =>
  mdRef.value ? mdRef.value.render(pasteText.value || '') : '',
)

// 单次粘贴最大字数：按解析模型上限（已扣 system prompt / 输出 / 安全余量）。
const maxInputChars = ref(60000)
const pasteLen = computed(() => pasteText.value.length)
const overLimit = computed(() => pasteLen.value > maxInputChars.value)

onMounted(() => {
  void loadInitial()
  void (async () => {
    try {
      const cfg = await projectWorkspaceApi.getFeatureListParseConfig(props.projectId)
      if (cfg?.max_input_chars && cfg.max_input_chars > 0)
        maxInputChars.value = cfg.max_input_chars
    }
    catch {}
  })()
  void (async () => {
    try {
      mdRef.value = await getMarkdownRenderer()
    }
    catch {}
  })()
})

// 优先加载草稿（异步解析进度 / 部分结果落库，刷新页面续看）；无草稿再加载已确认 feature list。
async function loadInitial() {
  try {
    const d = await projectWorkspaceApi.getFeatureListDraft(props.projectId)
    if (d.has_draft) {
      applyDraft(d)
      loadingExisting.value = false
      return
    }
  }
  catch {}
  await loadExisting()
}

// ── 异步解析（durable 后台任务 + WS 实时进度）──────────────
const draftStatus = ref<FeatureListDraftStatus>('idle')
const draftPhase = ref<FeatureListDraftPhase>('idle')
const progress = ref(0)
const draftError = ref('')
// 解析进行中：禁用编辑类操作、显示进度条（partial 表示部分模块已完成、仍在跑）。
const parsing = computed(() => draftStatus.value === 'parsing' || draftStatus.value === 'partial')

function mapDraftModule(m: FeatureListDraftModule): ModuleDraft {
  const feats = (m.features || []).map(f => newFeature({
    name: f.name || '',
    acceptanceText: (f.acceptance || []).join('\n'),
    source: f.source || '',
  }))
  return newModule({
    module: m.module || '',
    summary: m.summary || '',
    features: feats.length ? feats : [newFeature()],
    parsing: m.parse_state === 'pending' || m.parse_state === 'running',
  })
}

// 用草稿快照覆盖本地编辑器（进度 + 模块树）。解析中的快照为权威来源。
function applyDraft(d: FeatureListDraft) {
  draftStatus.value = d.status
  draftPhase.value = d.phase
  progress.value = d.progress ?? 0
  draftError.value = d.error || ''
  if (d.modules?.length)
    modules.splice(0, modules.length, ...d.modules.map(mapDraftModule))
}

// WS：后台每完成一个模块 / 阶段变更即推送草稿快照，实时回显进度与逐模块填充。
useProjectEventSocket(props.projectId, (evt) => {
  if (evt.event !== 'feature_list_draft')
    return
  applyDraft(evt.data as FeatureListDraft)
})

async function parseAndFill() {
  const text = pasteText.value
  if (!text.trim() || parsing.value || overLimit.value)
    return
  errorText.value = ''
  try {
    // 发起异步解析：写草稿 + defer 后台作业，立即返回；进度与结果经 WS 持续推送。
    const d = await projectWorkspaceApi.parseFeatureListDraft(props.projectId, text.trim())
    applyDraft(d)
    pasteText.value = ''
    pasteView.value = 'edit'
    success('已开始解析，进度将实时更新（可关闭弹窗，稍后回来查看）')
  }
  catch (e: unknown) {
    handleError(e, 'AI 解析文档失败')
  }
}

function buildManualPayload(): FeatureListModuleInput[] {
  return modules
    .map(m => ({
      module: m.module.trim() || '未分组',
      ...(m.summary?.trim() ? { summary: m.summary.trim() } : {}),
      features: m.features
        .map(f => ({
          name: f.name.trim(),
          acceptance: f.acceptanceText
            .split('\n')
            .map(s => s.trim())
            .filter(Boolean),
          ...(f.source?.trim() ? { source: f.source.trim() } : {}),
        }))
        .filter(f => f.name),
    }))
    .filter(m => m.features.length > 0)
}

const submitting = ref(false)
const savingDraft = ref(false)
const errorText = ref('')

// 存草稿：保存用户手工编辑到草稿（每项目一份，未确认；与异步解析共用同一草稿）。
async function saveDraft() {
  if (savingDraft.value || parsing.value)
    return
  errorText.value = ''
  savingDraft.value = true
  try {
    const payload = buildManualPayload()
    const d = await projectWorkspaceApi.saveFeatureListDraft(props.projectId, payload)
    applyDraft(d)
    success('草稿已保存')
  }
  catch (e: unknown) {
    handleError(e, '保存草稿')
  }
  finally {
    savingDraft.value = false
  }
}

// 确认保存：草稿 → 正式 feature list（落库后后端删除草稿）。
async function handleSubmit() {
  errorText.value = ''
  submitting.value = true
  try {
    const payload = buildManualPayload()
    if (payload.length === 0) {
      errorText.value = '请至少填写一个功能点'
      return
    }
    await projectWorkspaceApi.commitFeatureListDraft(props.projectId, payload)
    success('已保存 feature list')
    emit('confirm')
  }
  catch (e: unknown) {
    handleError(e, '保存 feature list')
  }
  finally {
    submitting.value = false
  }
}
</script>

<template>
  <VueFinalModal
    class="flex justify-center items-center"
    content-class="flex flex-col bg-card rounded-2xl shadow-2xl border border-border/50 max-w-4xl w-full mx-4 max-h-[90vh]"
    overlay-transition="vfm-fade"
    content-transition="vfm-zoom"
    @closed="emit('closed')"
  >
    <header class="flex items-center gap-3 px-6 py-4 border-b border-border/50">
      <span class="inline-flex size-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
        <span class="icon-[lucide--list-tree] text-lg" />
      </span>
      <div class="min-w-0 flex-1">
        <h2 class="text-sm font-semibold text-foreground">
          编辑 feature list
        </h2>
        <p class="text-xs text-muted-foreground">
          录入/编辑「模块 → 功能点 → 验收项」，可拖动排序；或粘贴文档让 AI 分层解析填入
        </p>
      </div>
      <div class="flex items-center gap-1.5 shrink-0">
        <span class="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
          <span class="icon-[lucide--folder] text-[11px]" />{{ modules.length }} 模块
        </span>
        <span class="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
          <span class="icon-[lucide--git-branch] text-[11px]" />{{ totalFeatures }} 功能点
        </span>
      </div>
    </header>

    <div class="flex-1 min-h-0 overflow-y-auto px-6 py-5 space-y-5">
      <!-- 粘贴文档 → AI 分层解析填入（可编辑 / markdown 预览） -->
      <div class="rounded-xl border border-dashed border-primary/30 bg-primary/[0.03] p-4 space-y-2.5" data-testid="fl-paste">
        <div class="flex items-center gap-2">
          <span class="icon-[lucide--sparkles] text-primary text-base" />
          <span class="text-sm font-semibold text-foreground">粘贴文档，AI 分层解析填入</span>
          <span class="text-xs text-muted-foreground hidden sm:inline">· markdown / 飞书 / gitlab 等均可，逐字保留原文</span>
          <div class="ml-auto inline-flex rounded-md border border-border/60 overflow-hidden text-xs">
            <button
              type="button"
              class="px-2 py-1"
              :class="pasteView === 'edit' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'"
              @click="pasteView = 'edit'"
            >
              编辑
            </button>
            <button
              type="button"
              class="px-2 py-1 border-l border-border/60"
              :class="pasteView === 'preview' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'"
              :disabled="!pasteText.trim()"
              @click="pasteView = 'preview'"
            >
              预览
            </button>
          </div>
        </div>

        <Textarea
          v-if="pasteView === 'edit'"
          v-model="pasteText"
          placeholder="把需求 / PRD / feature 文档整篇粘贴进来（markdown / 飞书 / gitlab / typora 等）。"
          :rows="6"
          class="text-sm font-mono leading-relaxed"
          :class="overLimit ? 'border-destructive focus-visible:border-destructive' : ''"
        />
        <!-- eslint-disable-next-line vue/no-v-html — markdown-it 以 html:false 渲染，无 XSS 风险 -->
        <div
          v-else
          class="rounded-lg border border-border/50 bg-background max-h-72 overflow-auto p-3 text-sm leading-relaxed [&_h1]:text-base [&_h1]:font-semibold [&_h1]:mb-1 [&_h2]:font-semibold [&_h2]:mt-2 [&_h3]:font-medium [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 [&_a]:text-primary [&_a]:underline [&_code]:bg-muted [&_code]:px-1 [&_code]:rounded [&_pre]:bg-muted [&_pre]:p-2 [&_pre]:rounded [&_pre]:overflow-x-auto [&_table]:w-full [&_th]:text-left [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground"
          v-html="previewHtml"
        />

        <div class="flex items-center justify-between gap-2">
          <span
            class="text-xs tabular-nums"
            :class="overLimit ? 'text-destructive font-medium' : 'text-muted-foreground'"
            data-testid="fl-paste-counter"
          >
            <template v-if="parsing">
              {{ draftPhase === 'modules' ? '解析模块中' : '逐功能点解析中' }} · {{ progress }}%
            </template>
            <template v-else>
              {{ pasteLen.toLocaleString() }} / {{ maxInputChars.toLocaleString() }} 字<template v-if="overLimit"> · 超出上限，请缩减或分段解析</template>
            </template>
          </span>
          <Button size="sm" :disabled="!pasteText.trim() || parsing || overLimit" data-testid="fl-parse-btn" @click="parseAndFill">
            <span class="icon-[lucide--wand-2] mr-1.5" :class="parsing ? 'animate-pulse' : ''" />
            {{ parsing ? 'AI 解析中…' : 'AI 解析填入' }}
          </Button>
        </div>

        <!-- 异步解析进度条（WS 实时；关闭弹窗后台继续，可稍后回来续看） -->
        <div v-if="parsing" class="space-y-1" data-testid="fl-parse-progress">
          <div class="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div
              class="h-full rounded-full bg-primary transition-all duration-500"
              :style="{ width: `${Math.max(3, progress)}%` }"
            />
          </div>
        </div>
        <p v-if="draftError" class="text-xs text-destructive" data-testid="fl-draft-error">
          {{ draftError }}
        </p>
      </div>

      <div v-if="loadingExisting" class="py-6 text-center text-sm text-muted-foreground">
        <span class="icon-[lucide--loader-2] animate-spin mr-1.5" />加载已有 feature list…
      </div>

      <!-- 模块 → 功能点 → 验收项（可拖动排序） -->
      <div v-else class="space-y-4" data-testid="fl-manual">
        <div
          v-for="(mod, mi) in modules"
          :key="mod.key"
          class="rounded-xl border border-border/60 bg-background/40 overflow-hidden"
          :class="dragModule === mi ? 'opacity-50' : ''"
          @dragover.prevent
          @drop="onModuleDrop(mi)"
        >
          <!-- 模块头 -->
          <div class="flex items-center gap-2.5 px-3.5 py-2.5 bg-muted/40 border-b border-border/50">
            <button
              type="button"
              class="cursor-grab active:cursor-grabbing text-muted-foreground/60 hover:text-muted-foreground shrink-0"
              draggable="true"
              :aria-label="`拖动模块 ${mi + 1}`"
              @dragstart="dragModule = mi"
              @dragend="dragModule = null"
            >
              <span class="icon-[lucide--grip-vertical] text-sm" />
            </button>
            <span class="inline-flex size-7 items-center justify-center rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400 shrink-0">
              <span class="icon-[lucide--folder] text-sm" />
            </span>
            <span class="text-[11px] font-mono text-muted-foreground shrink-0">M{{ mi + 1 }}</span>
            <Input
              v-model="mod.module"
              placeholder="模块名（如：用户中心）"
              class="h-8 flex-1 font-medium bg-transparent border-transparent focus-visible:border-border focus-visible:bg-background"
            />
            <span v-if="mod.parsing" class="text-[11px] text-primary shrink-0 inline-flex items-center gap-1">
              <span class="icon-[lucide--loader-2] animate-spin text-[11px]" />解析中
            </span>
            <span v-else class="text-xs text-muted-foreground shrink-0 tabular-nums">{{ moduleFeatureCount(mod) }} 功能点</span>
            <button
              type="button"
              class="size-7 inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/5 shrink-0"
              :aria-label="`删除模块 ${mi + 1}`"
              @click="removeModule(mi)"
            >
              <span class="icon-[lucide--trash-2] text-sm" />
            </button>
          </div>

          <!-- 功能点（带左侧层级轨，可拖动排序） -->
          <div class="pl-3.5 pr-3.5 py-3 space-y-2.5">
            <div v-if="mod.parsing && !mod.features.length" class="pl-5 text-xs text-muted-foreground">
              功能点解析中…
            </div>
            <div
              v-for="(feat, fi) in mod.features"
              :key="feat.key"
              class="relative pl-5 border-l-2 border-border/50"
              :class="dragFeat && dragFeat.mi === mi && dragFeat.fi === fi ? 'opacity-50' : ''"
              @dragover.prevent
              @drop="onFeatDrop(mi, fi)"
            >
              <span class="absolute -left-[5px] top-3 size-2 rounded-full bg-primary/60 ring-2 ring-card" />
              <div class="rounded-lg border border-border/40 bg-muted/20 p-2.5 space-y-2">
                <div class="flex items-center gap-2">
                  <button
                    type="button"
                    class="cursor-grab active:cursor-grabbing text-muted-foreground/50 hover:text-muted-foreground shrink-0"
                    draggable="true"
                    :aria-label="`拖动功能点 ${fi + 1}`"
                    @dragstart="dragFeat = { mi, fi }"
                    @dragend="dragFeat = null"
                  >
                    <span class="icon-[lucide--grip-vertical] text-xs" />
                  </button>
                  <span class="icon-[lucide--git-branch] text-primary/70 text-sm shrink-0" />
                  <Input
                    v-model="feat.name"
                    placeholder="功能点名称"
                    class="h-8 flex-1"
                  />
                  <span v-if="acceptanceCount(feat)" class="text-[11px] text-muted-foreground shrink-0 tabular-nums">{{ acceptanceCount(feat) }} 验收</span>
                  <button
                    type="button"
                    class="size-7 inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-destructive shrink-0"
                    :aria-label="`删除功能点 ${fi + 1}`"
                    @click="removeFeature(mi, fi)"
                  >
                    <span class="icon-[lucide--x] text-sm" />
                  </button>
                </div>
                <div class="flex items-start gap-2">
                  <span class="icon-[lucide--check-check] text-emerald-500/70 text-sm shrink-0 mt-1.5" />
                  <Textarea
                    v-model="feat.acceptanceText"
                    placeholder="验收项（每行一条，可留空）"
                    :rows="2"
                    class="text-sm leading-relaxed"
                  />
                </div>
              </div>
            </div>

            <button
              type="button"
              class="ml-5 text-xs text-primary inline-flex items-center gap-1 hover:underline"
              @click="addFeature(mi)"
            >
              <span class="icon-[lucide--plus] text-[11px]" /> 添加功能点
            </button>
          </div>
        </div>

        <button
          type="button"
          class="w-full rounded-xl border border-dashed border-border/70 py-2.5 text-sm text-muted-foreground hover:border-primary/40 hover:text-primary hover:bg-primary/[0.02] transition-colors"
          data-testid="fl-add-module"
          @click="addModule"
        >
          <span class="icon-[lucide--folder-plus] mr-1.5" /> 添加模块
        </button>
      </div>

      <p v-if="errorText" class="text-sm text-destructive" data-testid="fl-error">
        {{ errorText }}
      </p>
    </div>

    <footer class="flex items-center justify-between gap-2 px-6 py-4 border-t border-border/50">
      <span class="text-xs text-muted-foreground">
        共 {{ modules.length }} 模块 · {{ totalFeatures }} 功能点
      </span>
      <div class="flex items-center gap-2">
        <Button variant="ghost" :disabled="submitting" @click="emit('cancel')">
          取消
        </Button>
        <Button
          variant="outline"
          :disabled="submitting || savingDraft || parsing"
          data-testid="fl-save-draft"
          @click="saveDraft"
        >
          <span v-if="savingDraft" class="icon-[lucide--loader-2] mr-1.5 animate-spin" />
          <span v-else class="icon-[lucide--save] mr-1.5" />
          存草稿
        </Button>
        <Button :disabled="submitting || parsing" data-testid="fl-submit" @click="handleSubmit">
          <span v-if="submitting" class="icon-[lucide--loader-2] mr-1.5 animate-spin" />
          确认保存
        </Button>
      </div>
    </footer>
  </VueFinalModal>
</template>
