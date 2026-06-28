<script setup lang="ts">
import type { HumanTaskType, HumanTaskView } from '~/api/humanTasks'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, reactive } from 'vue'
import {
  answerClarification,
  listHumanTasks,
  resolveHumanTask,
  skipHumanTask,
} from '~/api/humanTasks'

/**
 * HumanTaskInbox —— 统一人类待办收件箱（Chassis v2 · P8 Human Task Center）。
 *
 * "一处看全待办，可处理并回流"：
 *  - 待答澄清（clarification）：内联渲染待答问题，按题作答 → 经后端 ClarificationService 回流。
 *  - 待审批（approval）/ 失败反应重试（reaction_retry）：跨 workflows 域，本处只呈现（带上下文），
 *    在各自执行页处理（least-invasive，不越界驱动 workflows）。
 *  - 风险确认（risk_ack）/ 可接管（takeover）等物化待办：可直接处理 / 跳过。
 *
 * 文案内联中文（不改 i18n 资源）。挂在项目工作台资料面板。
 */
const props = defineProps<{
  /** 仅看指派给当前用户的物化待办（投影类待办恒纳入）。 */
  mine?: boolean
}>()

const queryClient = useQueryClient()

const inboxQuery = useQuery({
  queryKey: ['human-tasks', computed(() => props.mine ?? false)],
  queryFn: () => listHumanTasks({ mine: props.mine }),
})
const tasks = computed<HumanTaskView[]>(() => inboxQuery.data.value ?? [])

const TYPE_META: Record<HumanTaskType, { label: string, icon: string, cls: string }> = {
  clarification: { label: '待答澄清', icon: 'icon-[lucide--message-circle-question]', cls: 'bg-amber-500/12 text-amber-600' },
  approval: { label: '待审批', icon: 'icon-[lucide--shield-check]', cls: 'bg-violet-500/12 text-violet-600' },
  risk_ack: { label: '风险确认', icon: 'icon-[lucide--alert-triangle]', cls: 'bg-rose-500/12 text-rose-600' },
  takeover: { label: '可接管', icon: 'icon-[lucide--hand]', cls: 'bg-sky-500/12 text-sky-600' },
  reaction_retry: { label: '失败反应', icon: 'icon-[lucide--zap-off]', cls: 'bg-orange-500/12 text-orange-600' },
}

function meta(type: HumanTaskType) {
  return TYPE_META[type] ?? { label: type, icon: 'icon-[lucide--inbox]', cls: 'bg-muted text-muted-foreground' }
}

function refresh() {
  queryClient.invalidateQueries({ queryKey: ['human-tasks'] })
}

// ── 物化待办：处理 / 跳过 ──────────────────────────────────────────────────
const resolveMutation = useMutation({
  mutationFn: (taskId: string) => resolveHumanTask(taskId, { via: 'inbox' }),
  onSuccess: refresh,
})
const skipMutation = useMutation({
  mutationFn: (taskId: string) => skipHumanTask(taskId, '收件箱跳过'),
  onSuccess: refresh,
})

// ── 澄清：按题作答草稿（task.id → question_id → 答案） ──────────────────────
interface AnswerDraft { selected: string | string[], freeform: string }
const drafts = reactive<Record<string, Record<string, AnswerDraft>>>({})

function ensureDraft(taskId: string, questionId: string, qtype: string): AnswerDraft {
  drafts[taskId] ??= {}
  drafts[taskId][questionId] ??= { selected: qtype === 'multi' ? [] : '', freeform: '' }
  return drafts[taskId][questionId]
}

function toggleMulti(taskId: string, questionId: string, option: string) {
  const d = ensureDraft(taskId, questionId, 'multi')
  const arr = Array.isArray(d.selected) ? d.selected : []
  d.selected = arr.includes(option) ? arr.filter(o => o !== option) : [...arr, option]
}

const answerMutation = useMutation({
  mutationFn: (task: HumanTaskView) => {
    const clarificationId = String(task.detail.clarification_id)
    const questions = (task.detail.questions ?? []) as Array<{ id: string, qtype: string }>
    const answers = questions.map((q) => {
      const d = ensureDraft(task.id, q.id, q.qtype)
      return { question_id: q.id, selected: d.selected, freeform_text: d.freeform }
    })
    return answerClarification(clarificationId, answers)
  },
  onSuccess: refresh,
})

const acting = computed(() =>
  resolveMutation.isPending.value
  || skipMutation.isPending.value
  || answerMutation.isPending.value,
)
</script>

<template>
  <section class="card" data-testid="human-task-inbox">
    <header class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2.5">
      <span class="section-chip"><span class="icon-[lucide--inbox]" /></span>
      <h2 class="text-sm font-semibold text-foreground">
        待办收件箱
      </h2>
      <span
        v-if="tasks.length"
        class="ml-1 rounded-full bg-primary/10 text-primary text-xs px-2 py-0.5"
        data-testid="human-task-count"
      >{{ tasks.length }}</span>
      <button
        class="ml-auto text-xs text-muted-foreground hover:text-foreground"
        data-testid="human-task-refresh"
        @click="refresh"
      >
        刷新
      </button>
    </header>

    <div class="p-5 space-y-3">
      <div
        v-if="inboxQuery.isLoading.value"
        class="text-sm text-muted-foreground py-6 text-center"
        data-testid="human-task-loading"
      >
        加载中…
      </div>
      <div
        v-else-if="inboxQuery.isError.value"
        class="py-6 text-center space-y-2"
        data-testid="human-task-error"
      >
        <p class="text-sm text-destructive">
          加载待办失败
        </p>
        <button class="text-sm text-primary underline" @click="() => inboxQuery.refetch()">
          重试
        </button>
      </div>
      <div
        v-else-if="tasks.length === 0"
        class="text-sm text-muted-foreground py-6 text-center"
        data-testid="human-task-empty"
      >
        暂无待办，一切都处理完了
      </div>

      <template v-else>
        <article
          v-for="task in tasks"
          :key="task.id"
          class="rounded-lg border border-border/50 px-3.5 py-3 space-y-2.5"
          :data-testid="`human-task-${task.task_type}`"
        >
          <div class="flex items-center gap-2">
            <span
              class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
              :class="meta(task.task_type).cls"
            >
              <span :class="meta(task.task_type).icon" /> {{ meta(task.task_type).label }}
            </span>
            <span class="text-sm font-medium text-foreground truncate">{{ task.title || task.subject_id }}</span>
          </div>

          <!-- 澄清：内联按题作答 -->
          <div v-if="task.task_type === 'clarification'" class="space-y-3" data-testid="clarification-form">
            <div
              v-for="q in (task.detail.questions ?? [])"
              :key="q.id"
              class="space-y-1.5"
            >
              <p class="text-sm text-foreground/90">
                {{ q.question }}
              </p>
              <!-- 单选 -->
              <div v-if="q.qtype !== 'multi'" class="flex flex-wrap gap-2">
                <label
                  v-for="opt in (q.options ?? [])"
                  :key="opt"
                  class="inline-flex items-center gap-1.5 text-sm cursor-pointer rounded-md border border-border/50 px-2.5 py-1"
                >
                  <input
                    type="radio"
                    :name="`${task.id}-${q.id}`"
                    :value="opt"
                    :checked="ensureDraft(task.id, q.id, q.qtype).selected === opt"
                    @change="ensureDraft(task.id, q.id, q.qtype).selected = opt"
                  >
                  {{ opt }}
                </label>
              </div>
              <!-- 多选 -->
              <div v-else class="flex flex-wrap gap-2">
                <label
                  v-for="opt in (q.options ?? [])"
                  :key="opt"
                  class="inline-flex items-center gap-1.5 text-sm cursor-pointer rounded-md border border-border/50 px-2.5 py-1"
                >
                  <input
                    type="checkbox"
                    :value="opt"
                    :checked="(ensureDraft(task.id, q.id, q.qtype).selected as string[]).includes(opt)"
                    @change="toggleMulti(task.id, q.id, opt)"
                  >
                  {{ opt }}
                </label>
              </div>
              <input
                v-model="ensureDraft(task.id, q.id, q.qtype).freeform"
                type="text"
                placeholder="补充说明（可选）"
                class="w-full text-sm rounded-md border border-border/50 px-2.5 py-1 bg-background"
              >
            </div>
            <button
              class="inline-flex items-center gap-1.5 rounded-lg bg-primary text-primary-foreground text-sm px-3 py-1.5 disabled:opacity-50"
              :disabled="acting"
              data-testid="clarification-submit"
              @click="answerMutation.mutate(task)"
            >
              <span class="icon-[lucide--send]" /> 提交回答
            </button>
          </div>

          <!-- 审批 / 失败反应：呈现上下文 + 去处理提示（不越界驱动 workflows） -->
          <div
            v-else-if="task.task_type === 'approval' || task.task_type === 'reaction_retry'"
            class="text-xs text-muted-foreground space-y-1"
            data-testid="task-context"
          >
            <p v-if="task.detail.workflow_name">
              工作流：{{ task.detail.workflow_name }}
            </p>
            <p v-if="task.detail.last_error" class="text-destructive/80 break-words">
              错误：{{ task.detail.last_error }}
            </p>
            <p class="text-muted-foreground/80">
              {{ task.task_type === 'approval' ? '请到工作流执行页完成审批' : '请到工作流执行页重试该反应' }}
            </p>
          </div>

          <!-- 物化待办（风险确认 / 接管等）：处理 / 跳过 -->
          <div v-else class="flex items-center gap-2" data-testid="materialized-actions">
            <button
              class="inline-flex items-center gap-1.5 rounded-lg bg-primary text-primary-foreground text-sm px-3 py-1.5 disabled:opacity-50"
              :disabled="acting"
              data-testid="task-resolve"
              @click="resolveMutation.mutate(task.id)"
            >
              <span class="icon-[lucide--check]" /> 处理
            </button>
            <button
              class="inline-flex items-center gap-1.5 rounded-lg border border-border/50 text-sm px-3 py-1.5 text-muted-foreground hover:text-foreground disabled:opacity-50"
              :disabled="acting"
              data-testid="task-skip"
              @click="skipMutation.mutate(task.id)"
            >
              跳过
            </button>
          </div>
        </article>
      </template>
    </div>
  </section>
</template>
