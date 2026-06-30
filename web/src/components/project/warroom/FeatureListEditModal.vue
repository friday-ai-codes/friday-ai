<script setup lang="ts">
import type { FeatureListModuleInput } from '~/api/projectWorkspace'
import { computed, onMounted, reactive, ref } from 'vue'
import { VueFinalModal } from 'vue-final-modal'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Textarea } from '~/components/ui/textarea'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

// feature list 录入弹窗：单一「手动录入」结构（模块 → 功能点 → 验收项）。
// 可粘贴整篇文档，点「AI 解析填入」由 agent 拆解为结构化行自动填入编辑器，再人工确认保存。
const props = defineProps<{ projectId: string }>()
const emit = defineEmits<{ confirm: [], cancel: [], closed: [] }>()

const { handleError } = useErrorHandler()
const { success } = useToast()

// source/summary：解析得来的整段原文（功能点）/ 模块概述，随保存留存，供详情按需结构化。
interface FeatureDraft { name: string, acceptanceText: string, source?: string }
interface ModuleDraft { module: string, summary?: string, features: FeatureDraft[] }
const modules = reactive<ModuleDraft[]>([
  { module: '', features: [{ name: '', acceptanceText: '' }] },
])

// 头部计数（只统计已填名称的功能点）。
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
  modules.push({ module: '', features: [{ name: '', acceptanceText: '' }] })
}
function removeModule(i: number) {
  modules.splice(i, 1)
  if (modules.length === 0)
    addModule()
}
function addFeature(mi: number) {
  modules[mi].features.push({ name: '', acceptanceText: '' })
}
function removeFeature(mi: number, fi: number) {
  modules[mi].features.splice(fi, 1)
  if (modules[mi].features.length === 0)
    modules[mi].features.push({ name: '', acceptanceText: '' })
}

// 判断当前编辑器是否仍是初始空白（只有一个空模块空功能点）——用于解析后决定覆盖还是追加。
function isPristine(): boolean {
  if (modules.length !== 1)
    return false
  const m = modules[0]
  return !m.module.trim() && m.features.length === 1 && !m.features[0].name.trim()
}

// ── 粘贴文档 → AI 解析 → 填入结构化行 ──────────────────────────
const pasteText = ref('')
const parsing = ref(false)

// 单次粘贴最大字数：按解析模型上限（已扣 system prompt / 输出 / 安全余量）；
// 加载前给保守兜底，避免未取到配置时无限制粘贴撑爆上下文。
const maxInputChars = ref(60000)
onMounted(async () => {
  try {
    const cfg = await projectWorkspaceApi.getFeatureListParseConfig(props.projectId)
    if (cfg?.max_input_chars && cfg.max_input_chars > 0)
      maxInputChars.value = cfg.max_input_chars
  }
  catch {
    // best-effort：取不到配置就用兜底字数，不打断录入。
  }
})
const pasteLen = computed(() => pasteText.value.length)
const overLimit = computed(() => pasteLen.value > maxInputChars.value)

async function parseAndFill() {
  const text = pasteText.value.trim()
  if (!text || parsing.value || overLimit.value)
    return
  parsing.value = true
  try {
    const { modules: parsed } = await projectWorkspaceApi.parseFeatureList(props.projectId, text)
    const drafts: ModuleDraft[] = (parsed || []).map(m => ({
      module: m.module || '',
      summary: m.summary || '',
      features: (m.features || []).map(f => ({
        name: f.name || '',
        acceptanceText: (f.acceptance || []).join('\n'),
        source: f.source || '',
      })),
    })).filter(m => m.features.length > 0)
    if (drafts.length === 0) {
      errorText.value = 'AI 未从文档解析出功能点，请检查文档内容'
      return
    }
    // 初始空白 → 覆盖；已有内容 → 追加（支持粘贴多篇文档累积）。
    if (isPristine())
      modules.splice(0, modules.length, ...drafts)
    else
      modules.push(...drafts)
    pasteText.value = ''
    success(`已解析填入 ${drafts.reduce((n, m) => n + m.features.length, 0)} 个功能点`)
  }
  catch (e: unknown) {
    handleError(e, 'AI 解析文档失败')
  }
  finally {
    parsing.value = false
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
const errorText = ref('')

async function handleSubmit() {
  errorText.value = ''
  submitting.value = true
  try {
    const payload = buildManualPayload()
    if (payload.length === 0) {
      errorText.value = '请至少填写一个功能点'
      return
    }
    await projectWorkspaceApi.setFeatureList(props.projectId, { mode: 'manual', modules: payload })
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
          补充 feature list
        </h2>
        <p class="text-xs text-muted-foreground">
          手动录入「模块 → 功能点 → 验收项」，或粘贴文档让 AI 解析后自动填入
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
      <!-- 粘贴文档 → AI 解析填入 -->
      <div class="rounded-xl border border-dashed border-primary/30 bg-primary/[0.03] p-4 space-y-2.5" data-testid="fl-paste">
        <div class="flex items-center gap-2">
          <span class="icon-[lucide--sparkles] text-primary text-base" />
          <span class="text-sm font-semibold text-foreground">粘贴文档，AI 解析填入</span>
          <span class="text-xs text-muted-foreground">· 仅解析结构，功能点 / 验收项逐字保留原文</span>
        </div>
        <Textarea
          v-model="pasteText"
          placeholder="把需求 / PRD / feature 文档整篇粘贴进来（可粘贴多篇，多次解析累积）。"
          :rows="5"
          class="text-sm font-mono leading-relaxed"
          :class="overLimit ? 'border-destructive focus-visible:border-destructive' : ''"
        />
        <div class="flex items-center justify-between gap-2">
          <span
            class="text-xs tabular-nums"
            :class="overLimit ? 'text-destructive font-medium' : 'text-muted-foreground'"
            data-testid="fl-paste-counter"
          >
            {{ pasteLen.toLocaleString() }} / {{ maxInputChars.toLocaleString() }} 字<template v-if="overLimit"> · 超出上限，请缩减或分段解析</template>
          </span>
          <Button size="sm" :disabled="!pasteText.trim() || parsing || overLimit" data-testid="fl-parse-btn" @click="parseAndFill">
            <span class="icon-[lucide--wand-2] mr-1.5" :class="parsing ? 'animate-pulse' : ''" />
            {{ parsing ? 'AI 解析中…' : 'AI 解析填入' }}
          </Button>
        </div>
      </div>

      <!-- 手动录入结构：模块 → 功能点 → 验收项 -->
      <div class="space-y-4" data-testid="fl-manual">
        <div
          v-for="(mod, mi) in modules"
          :key="mi"
          class="rounded-xl border border-border/60 bg-background/40 overflow-hidden"
        >
          <!-- 模块头 -->
          <div class="flex items-center gap-2.5 px-3.5 py-2.5 bg-muted/40 border-b border-border/50">
            <span class="inline-flex size-7 items-center justify-center rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400 shrink-0">
              <span class="icon-[lucide--folder] text-sm" />
            </span>
            <span class="text-[11px] font-mono text-muted-foreground shrink-0">M{{ mi + 1 }}</span>
            <Input
              v-model="mod.module"
              placeholder="模块名（如：用户中心）"
              class="h-8 flex-1 font-medium bg-transparent border-transparent focus-visible:border-border focus-visible:bg-background"
            />
            <span class="text-xs text-muted-foreground shrink-0 tabular-nums">{{ moduleFeatureCount(mod) }} 功能点</span>
            <button
              type="button"
              class="size-7 inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/5 shrink-0"
              :aria-label="`删除模块 ${mi + 1}`"
              @click="removeModule(mi)"
            >
              <span class="icon-[lucide--trash-2] text-sm" />
            </button>
          </div>

          <!-- 功能点（带左侧层级轨） -->
          <div class="pl-3.5 pr-3.5 py-3 space-y-2.5">
            <div
              v-for="(feat, fi) in mod.features"
              :key="fi"
              class="relative pl-5 border-l-2 border-border/50"
            >
              <span class="absolute -left-[5px] top-3 size-2 rounded-full bg-primary/60 ring-2 ring-card" />
              <div class="rounded-lg border border-border/40 bg-muted/20 p-2.5 space-y-2">
                <div class="flex items-center gap-2">
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
        <Button :disabled="submitting" data-testid="fl-submit" @click="handleSubmit">
          <span v-if="submitting" class="icon-[lucide--loader-2] mr-1.5 animate-spin" />
          保存
        </Button>
      </div>
    </footer>
  </VueFinalModal>
</template>
