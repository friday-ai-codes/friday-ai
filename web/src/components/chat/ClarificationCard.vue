<script setup lang="ts">
/**
 * ：协商卡片。
 *
 * 两条物理隔离的渲染路径，按 payload 形态分支（CONTEXT 锁定「扩展现有组件」）：
 *
 * 1) chat 单题澄清（ClarificationPayload）：渲染 ask_clarification 工具暴露的
 *    「问题 + ABCD 选项 + 自由输入」单选 UI；提交调
 *    `POST /api/chat/clarifications/{id}/answer/`，成功 → 切「已回复」态。
 *
 * 2) plan 结构化澄清（PlanClarificationPayload，含 `questions[]`，91-05）：渲染
 *    多题轮——每题按 qtype 单选(button)/多选(Checkbox)，⭐推荐默认选中 + 每题可选
 *    自由输入；提交聚合 `answers:[{question_id,selected,freeform_text}]` 打
 *    `POST /api/chat/conversations/{id}/plan-clarification/answer/`（91-04 专路由），
 *    成功 → 切「已回复」态。
 *
 * 后端 endpoint 已落 trace + Message + 后台续推 —— 前端**不再 emit 新 user message**，
 * 答复内容由后端单独写 Message 完成（防双发）。两条路径互不串渲染。
 */
import type MarkdownIt from 'markdown-it'
import type { ClarificationPayload, PlanClarificationPayload, PlanClarificationQuestion } from '~/types/clarification'
import { useI18n } from 'vue-i18n'
import { postClarificationAnswer, postPlanClarificationAnswer } from '~/api/chat'
import InlineMarkdown from '~/components/common/InlineMarkdown.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Checkbox } from '~/components/ui/checkbox'
import { Textarea } from '~/components/ui/textarea'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
import { useChatStore } from '~/stores/chat'

const props = defineProps<{
  payload: ClarificationPayload | PlanClarificationPayload
}>()

const { t } = useI18n()
const chatStore = useChatStore()

/** payload 形态判别：含 questions[] → plan 多题轮；否则 → chat 单题。 */
const isPlan = computed(
  (): boolean => Array.isArray((props.payload as PlanClarificationPayload).questions),
)
const planPayload = computed(() => props.payload as PlanClarificationPayload)
const singlePayload = computed(() => props.payload as ClarificationPayload)

const isAnswered = computed(() => props.payload.status === 'answered')

const submitting = ref(false)
const errorMessage = ref<string>('')

// 问题正文块级 markdown 渲染（LLM 产出常含 **加粗**/列表；markdown-it html:false 防 XSS）。
// 渲染器就绪前降级纯文本，避免闪烁。
const mdRef = shallowRef<MarkdownIt | null>(null)
onMounted(async () => {
  try {
    mdRef.value = await getMarkdownRenderer()
  }
  catch {}
})
function renderMd(text: string): string {
  return mdRef.value ? mdRef.value.render(text || '') : ''
}
// 问题正文的 markdown 排版样式（与 FeatureDetailModal 同款约定）。
const MD_BLOCK_CLASS = 'md-block leading-relaxed wrap-break-word space-y-2 [&_h1]:text-base [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-medium [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 [&_a]:text-primary [&_a]:underline [&_strong]:font-semibold [&_code]:bg-muted [&_code]:px-1 [&_code]:rounded [&_pre]:bg-muted [&_pre]:p-2 [&_pre]:rounded [&_pre]:overflow-x-auto [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground'

// ---------------------------------------------------------------------------
// chat 单题路径（零回归保留）
// ---------------------------------------------------------------------------
// 推荐选项（至多一个）默认选中，降低用户决策成本；已答卡片不回填，避免误导。
const recommendedSingleId = computed(
  () => (isPlan.value ? '' : (singlePayload.value.options.find(o => o.recommended)?.id ?? '')),
)
const selectedId = ref<string>(
  props.payload.status === 'answered' ? '' : recommendedSingleId.value,
)
const freeformText = ref<string>('')
const skipping = ref(false)

const canSubmitSingle = computed(() => {
  if (isAnswered.value || submitting.value)
    return false
  return Boolean(selectedId.value || freeformText.value.trim())
})

const resolvedAnswerLabel = computed(() => {
  const ans = singlePayload.value.answer
  if (!ans)
    return ''
  if (ans.freeform_text)
    return ans.freeform_text
  if (ans.selected_option_id) {
    const opt = singlePayload.value.options.find(o => o.id === ans.selected_option_id)
    return opt?.label || ans.selected_option_id
  }
  return ''
})

function formatAnsweredAt(iso?: string): string {
  if (!iso)
    return ''
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { hour12: false })
  }
  catch {
    return iso
  }
}

async function submitSingle() {
  if (!canSubmitSingle.value)
    return
  submitting.value = true
  errorMessage.value = ''
  try {
    const resp = await postClarificationAnswer(singlePayload.value.clarification_id, {
      selected_option_id: selectedId.value || undefined,
      freeform_text: freeformText.value.trim() || undefined,
    })
    chatStore.markClarificationAnswered(singlePayload.value.clarification_id, {
      selected_option_id: resp.selected_option_id,
      freeform_text: resp.freeform_text,
      answered_at: resp.answered_at,
    })
  }
  catch (err: unknown) {
    const e = err as { response?: { data?: { detail?: string } }, message?: string }
    errorMessage.value = e?.response?.data?.detail || e?.message || t('chat.clarification.submitError')
  }
  finally {
    submitting.value = false
  }
}

/**
 * 跳过本次澄清：不提交答复，让后端基于现有信息直接作答。
 * 走 conversation 维度的 skip endpoint（store action 已封装乐观更新 + 轮询）。
 */
async function skip() {
  if (submitting.value || skipping.value)
    return
  skipping.value = true
  errorMessage.value = ''
  try {
    await chatStore.skipClarification()
  }
  catch (err: unknown) {
    const e = err as { message?: string }
    errorMessage.value = e?.message || '跳过失败，请重试'
  }
  finally {
    skipping.value = false
  }
}

// ---------------------------------------------------------------------------
// plan 多题多选路径（91-05）
// ---------------------------------------------------------------------------

/** 推荐项归一化为数组（runtime 可能给 str 或 str[]）。 */
function recommendedOf(q: PlanClarificationQuestion): string[] {
  const r = q.recommended
  if (Array.isArray(r))
    return r
  if (typeof r === 'string' && r)
    return [r]
  return []
}

/** 已回填选择归一化（已答轮回显）。 */
function selectedOf(q: PlanClarificationQuestion): string[] {
  const s = q.selected
  if (Array.isArray(s))
    return s
  if (typeof s === 'string' && s)
    return [s]
  return []
}

// 每题选择态：single → string，multi → string[]（Set 语义）。
const singleSel = reactive<Record<string, string>>({})
const multiSel = reactive<Record<string, string[]>>({})
const planFreeform = reactive<Record<string, string>>({})

function initPlanState() {
  if (!isPlan.value)
    return
  for (const q of planPayload.value.questions) {
    const preset = selectedOf(q)
    const defaults = preset.length > 0 ? preset : recommendedOf(q)
    if (q.qtype === 'single')
      singleSel[q.question_id] = defaults[0] ?? ''
    else
      multiSel[q.question_id] = [...defaults]
    planFreeform[q.question_id] = q.freeform_text ?? ''
  }
}

initPlanState()
watch(() => props.payload, initPlanState)

function isChecked(q: PlanClarificationQuestion, value: string): boolean {
  if (q.qtype === 'single')
    return singleSel[q.question_id] === value
  return (multiSel[q.question_id] ?? []).includes(value)
}

function toggleOption(q: PlanClarificationQuestion, value: string) {
  if (isAnswered.value || submitting.value)
    return
  if (q.qtype === 'single') {
    singleSel[q.question_id] = value
    return
  }
  const cur = multiSel[q.question_id] ?? []
  multiSel[q.question_id] = cur.includes(value)
    ? cur.filter(v => v !== value)
    : [...cur, value]
}

const planConversationId = computed(
  () => planPayload.value.conversation_id || chatStore.currentConversationId || '',
)

const canSubmitPlan = computed(() => !isAnswered.value && !submitting.value)

async function submitPlan() {
  if (!canSubmitPlan.value)
    return
  const convId = planConversationId.value
  if (!convId) {
    errorMessage.value = t('chat.clarification.submitError')
    return
  }
  submitting.value = true
  errorMessage.value = ''
  try {
    const answers = planPayload.value.questions.map((q) => {
      const selected = q.qtype === 'single'
        ? (singleSel[q.question_id] ?? '')
        : [...(multiSel[q.question_id] ?? [])]
      const freeform = (planFreeform[q.question_id] ?? '').trim()
      return {
        question_id: q.question_id,
        selected,
        freeform_text: freeform || undefined,
      }
    })
    await postPlanClarificationAnswer(convId, { answers })
    chatStore.markPlanClarificationAnswered(planPayload.value.clarification_id)
  }
  catch (err: unknown) {
    const e = err as { response?: { data?: { detail?: string } }, message?: string }
    errorMessage.value = e?.response?.data?.detail || e?.message || t('chat.clarification.submitError')
  }
  finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="card mt-2 animate-fade-in">
    <!-- 头部 -->
    <div class="px-4 py-3 border-b border-border/50 flex items-center gap-2">
      <span class="icon-[lucide--help-circle] text-primary" />
      <span class="text-sm font-semibold">{{ t('chat.clarification.title') }}</span>
      <Badge :variant="isAnswered ? 'default' : 'info'" class="ml-auto">
        {{ isAnswered ? t('chat.clarification.statusAnswered') : t('chat.clarification.statusPending') }}
      </Badge>
    </div>

    <!-- plan 多题多选路径（91-05） -->
    <div v-if="isPlan" class="p-4 space-y-5">
      <div
        v-for="q in planPayload.questions"
        :key="q.question_id"
        :data-question-id="q.question_id"
        class="space-y-2"
      >
        <div class="flex items-start gap-2">
          <p class="text-sm font-medium text-foreground">
            <InlineMarkdown :text="q.question" />
          </p>
          <span v-if="q.qtype === 'multi'" class="text-xs text-muted-foreground shrink-0">
            {{ t('chat.clarification.multiHint') }}
          </span>
        </div>

        <div :role="q.qtype === 'single' ? 'radiogroup' : 'group'" class="space-y-2">
          <button
            v-for="opt in q.options"
            :key="opt"
            type="button"
            data-option
            :data-value="opt"
            :role="q.qtype === 'single' ? 'radio' : 'checkbox'"
            :aria-checked="isChecked(q, opt)"
            :disabled="isAnswered || submitting"
            class="w-full text-left rounded-lg border px-3 py-2 transition-colors disabled:cursor-not-allowed disabled:opacity-60"
            :class="[
              isChecked(q, opt)
                ? 'border-primary bg-primary/5'
                : 'border-border hover:border-primary/50 hover:bg-muted/30',
            ]"
            @click="toggleOption(q, opt)"
          >
            <div class="flex items-start gap-2">
              <!-- 单选：圆形指示；多选：Checkbox 组件（只读视觉，点击走整行 button） -->
              <span
                v-if="q.qtype === 'single'"
                class="mt-0.5 size-4 shrink-0 rounded-full border-2 transition-colors"
                :class="[isChecked(q, opt) ? 'border-primary bg-primary' : 'border-border']"
              />
              <Checkbox
                v-else
                :model-value="isChecked(q, opt)"
                tabindex="-1"
                class="mt-0.5 shrink-0 pointer-events-none"
              />
              <div class="min-w-0 flex-1">
                <div class="text-sm font-medium flex items-center gap-1.5">
                  <span><InlineMarkdown :text="opt" /></span>
                  <!-- 推荐选项：Friday 品牌标识 +（推荐） -->
                  <span
                    v-if="recommendedOf(q).includes(opt)"
                    class="inline-flex items-center gap-1 text-xs text-primary shrink-0"
                    data-testid="clarification-recommended"
                  >
                    <img src="/logo-mark.svg" alt="" aria-hidden="true" class="size-3.5">
                    {{ t('chat.clarification.recommended') }}
                  </span>
                </div>
              </div>
            </div>
          </button>
        </div>

        <!-- 每题可选自由输入 -->
        <div v-if="!isAnswered">
          <Textarea
            v-model="planFreeform[q.question_id]"
            :disabled="submitting"
            rows="2"
            :placeholder="t('chat.clarification.freeformPlaceholder')"
            class="text-sm"
          />
        </div>
      </div>

      <p v-if="errorMessage" class="text-destructive text-xs">
        {{ errorMessage }}
      </p>
    </div>

    <!-- chat 单题路径（零回归） -->
    <div v-else class="p-4 space-y-3">
      <p v-if="!mdRef" class="text-sm text-foreground whitespace-pre-wrap">
        {{ singlePayload.question }}
      </p>
      <!-- eslint-disable-next-line vue/no-v-html — markdown-it 以 html:false 渲染，无 XSS 风险 -->
      <div
        v-else
        class="text-sm text-foreground"
        :class="MD_BLOCK_CLASS"
        v-html="renderMd(singlePayload.question)"
      />

      <!-- 选项列表（用 button 实现单选；shadcn-vue 项目无 RadioGroup） -->
      <div role="radiogroup" :aria-disabled="isAnswered" class="space-y-2">
        <button
          v-for="opt in singlePayload.options"
          :key="opt.id"
          type="button"
          role="radio"
          :aria-checked="selectedId === opt.id"
          :disabled="isAnswered || submitting"
          class="w-full text-left rounded-lg border px-3 py-2 transition-colors disabled:cursor-not-allowed disabled:opacity-60"
          :class="[
            selectedId === opt.id
              ? 'border-primary bg-primary/5'
              : 'border-border hover:border-primary/50 hover:bg-muted/30',
          ]"
          @click="selectedId = opt.id"
        >
          <div class="flex items-start gap-2">
            <span
              class="mt-0.5 size-4 shrink-0 rounded-full border-2 transition-colors"
              :class="[
                selectedId === opt.id
                  ? 'border-primary bg-primary'
                  : 'border-border',
              ]"
            />
            <div class="min-w-0 flex-1">
              <div class="text-sm font-medium flex items-center gap-1.5">
                <span><InlineMarkdown :text="opt.label" /></span>
                <!-- 推荐选项：Friday 品牌标识 +（推荐） -->
                <span
                  v-if="opt.recommended"
                  class="inline-flex items-center gap-1 text-xs text-primary shrink-0"
                  data-testid="clarification-recommended"
                >
                  <img src="/logo-mark.svg" alt="" aria-hidden="true" class="size-3.5">
                  {{ t('chat.clarification.recommended') }}
                </span>
              </div>
              <div v-if="opt.hint" class="text-xs text-muted-foreground mt-0.5">
                <InlineMarkdown :text="opt.hint" />
              </div>
            </div>
          </div>
        </button>
      </div>

      <!-- 自由输入兜底（allow_freeform=false 时不渲染） -->
      <div v-if="singlePayload.allow_freeform && !isAnswered">
        <label class="text-xs text-muted-foreground font-medium">
          {{ t('chat.clarification.freeformLabel') }}
        </label>
        <Textarea
          v-model="freeformText"
          :disabled="submitting"
          rows="2"
          :placeholder="t('chat.clarification.freeformPlaceholder')"
          class="mt-1 text-sm"
        />
      </div>

      <!-- 已回复态摘要 -->
      <div v-if="isAnswered && singlePayload.answer" class="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2">
        <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span class="icon-[lucide--check-circle-2] text-emerald-500" />
          <span>{{ t('chat.clarification.answeredAt', { time: formatAnsweredAt(singlePayload.answer.answered_at) }) }}</span>
        </div>
        <div v-if="resolvedAnswerLabel" class="mt-1 text-sm">
          选择：<InlineMarkdown :text="resolvedAnswerLabel" />
        </div>
      </div>

      <p v-if="errorMessage" class="text-destructive text-xs">
        {{ errorMessage }}
      </p>
    </div>

    <!-- 底部操作区 -->
    <div v-if="!isAnswered" class="px-4 pb-4 pt-2 flex items-center gap-2">
      <Button
        v-if="!isPlan"
        variant="ghost"
        class="shrink-0 text-muted-foreground"
        :disabled="submitting || skipping"
        @click="skip"
      >
        <span v-if="skipping" class="icon-[lucide--loader-2] animate-spin mr-2" />
        跳过
      </Button>
      <Button
        v-if="isPlan"
        class="flex-1"
        data-testid="plan-clarification-submit"
        :disabled="!canSubmitPlan"
        @click="submitPlan"
      >
        <span v-if="submitting" class="icon-[lucide--loader-2] animate-spin mr-2" />
        {{ t('chat.clarification.submit') }}
      </Button>
      <Button
        v-else
        class="flex-1"
        :disabled="!canSubmitSingle"
        @click="submitSingle"
      >
        <span v-if="submitting" class="icon-[lucide--loader-2] animate-spin mr-2" />
        {{ t('chat.clarification.submit') }}
      </Button>
    </div>
  </div>
</template>
