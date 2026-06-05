<script setup lang="ts">
import type { InteractionLog } from '~/api/workflow'
import { computed, ref, watch } from 'vue'

import { answerAgentSession, answerInteraction, getNodeInteractions } from '~/api/workflow'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Textarea } from '~/components/ui/textarea'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const props = defineProps<{
  nodeExecutionId: string
  outputData?: Record<string, any>
  nodeStatus?: string
}>()

const emit = defineEmits<{
  answered: []
}>()

const { handleError } = useErrorHandler()
const { success } = useToast()

// === InteractionLog 场景 (SubAgent 容器) ===
const interactions = ref<InteractionLog[]>([])
const loading = ref(false)

const pendingInteractions = computed(() =>
  interactions.value.filter(i => !i.answered_at),
)
const answeredInteractions = computed(() =>
  interactions.value.filter(i => i.answered_at),
)

async function fetchInteractions() {
  loading.value = true
  try {
    interactions.value = await getNodeInteractions(props.nodeExecutionId)
  }
  catch {
    // intentionally ignored
  }
  finally {
    loading.value = false
  }
}

// === AgentSession 场景 (AIAgentBaseNode) ===
const agentSessionId = computed(() => props.outputData?.session_id || '')
const agentQuestion = computed(() => {
  const partial = props.outputData?.partial_output
  if (Array.isArray(partial)) {
    const last = partial[partial.length - 1]
    if (last?.awaiting_response)
      return last.question || ''
  }
  return ''
})
const isAgentWaiting = computed(() =>
  !!agentQuestion.value && props.nodeStatus === 'waiting_event',
)

// === 共享状态 ===
const submitting = ref(false)
const customAnswer = ref('')
const answered = ref(false)

const hasContent = computed(() =>
  interactions.value.length > 0 || isAgentWaiting.value || answered.value,
)

async function submitInteractionAnswer(interaction: InteractionLog, answer: string, source: 'button' | 'text' = 'text') {
  if (!answer.trim())
    return
  submitting.value = true
  try {
    const updated = await answerInteraction(interaction.id, answer, source)
    const idx = interactions.value.findIndex(i => i.id === interaction.id)
    if (idx !== -1)
      interactions.value[idx] = updated
    customAnswer.value = ''
    success('回答已提交')
  }
  catch (e: unknown) {
    handleError(e, '提交')
  }
  finally {
    submitting.value = false
  }
}

async function submitAgentAnswer(answer: string) {
  if (!answer.trim() || !agentSessionId.value)
    return
  submitting.value = true
  try {
    await answerAgentSession(agentSessionId.value, answer)
    customAnswer.value = ''
    answered.value = true
    success('回答已提交')
    emit('answered')
  }
  catch (e: unknown) {
    handleError(e, '提交')
  }
  finally {
    submitting.value = false
  }
}

watch(() => props.nodeExecutionId, fetchInteractions, { immediate: true })
</script>

<template>
  <div v-if="hasContent || loading" class="space-y-3">
    <div class="flex items-center gap-2">
      <div class="bg-primary/10 rounded-lg p-1.5">
        <span class="icon-[lucide--message-circle-question] w-4 h-4 text-amber-500" />
      </div>
      <span class="text-sm font-medium">调试交互</span>
      <Badge v-if="pendingInteractions.length || isAgentWaiting" variant="destructive" class="text-xs">
        {{ pendingInteractions.length + (isAgentWaiting ? 1 : 0) }} 待回答
      </Badge>
      <Button variant="ghost" size="icon" class="ml-auto h-6 w-6" @click="fetchInteractions">
        <span class="icon-[lucide--refresh-cw] w-3 h-3" />
      </Button>
    </div>

    <div v-if="loading && !interactions.length && !isAgentWaiting" class="flex justify-center py-4">
      <span class="icon-[lucide--loader-2] w-5 h-5 animate-spin text-muted-foreground" />
    </div>

    <!-- AgentSession 提问 (waiting_event) -->
    <div
      v-if="isAgentWaiting && !answered"
      class="p-3 rounded-xl border border-amber-500/30 bg-amber-500/5 space-y-2"
    >
      <div class="text-sm font-medium">
        {{ agentQuestion }}
      </div>
      <div class="flex gap-2">
        <Textarea
          v-model="customAnswer"
          placeholder="输入回复..."
          class="min-h-[60px] text-sm"
        />
        <Button
          size="sm"
          class="shrink-0 self-end"
          :disabled="submitting || !customAnswer.trim()"
          @click="submitAgentAnswer(customAnswer)"
        >
          <span v-if="submitting" class="icon-[lucide--loader-2] w-3 h-3 animate-spin mr-1" />
          提交
        </Button>
      </div>
    </div>

    <!-- AgentSession 已回答 -->
    <div
      v-if="answered"
      class="p-3 rounded-xl border border-border/50 bg-muted/30 space-y-1 opacity-70"
    >
      <div class="text-sm">
        <span class="text-muted-foreground">Q:</span> {{ agentQuestion }}
      </div>
      <div class="text-sm text-muted-foreground italic">
        已提交回答，等待 Agent 继续执行...
      </div>
    </div>

    <!-- InteractionLog 待回答 -->
    <div
      v-for="item in pendingInteractions"
      :key="item.id"
      class="p-3 rounded-xl border border-amber-500/30 bg-amber-500/5 space-y-2"
    >
      <div v-if="item.question_context" class="text-xs text-muted-foreground italic">
        {{ item.question_context }}
      </div>
      <div class="text-sm font-medium">
        {{ item.question_text }}
      </div>
      <pre v-if="item.code_snippet" class="p-2 rounded-lg bg-muted text-xs overflow-auto max-h-32 font-mono">{{ item.code_snippet }}</pre>

      <div v-if="item.options?.length" class="flex flex-wrap gap-2">
        <Button
          v-for="opt in item.options"
          :key="opt"
          variant="outline"
          size="sm"
          :disabled="submitting"
          @click="submitInteractionAnswer(item, opt, 'button')"
        >
          {{ opt }}
        </Button>
      </div>

      <div class="flex gap-2">
        <Textarea
          v-model="customAnswer"
          placeholder="输入自定义回复..."
          class="min-h-[60px] text-sm"
        />
        <Button
          size="sm"
          class="shrink-0 self-end"
          :disabled="submitting || !customAnswer.trim()"
          @click="submitInteractionAnswer(item, customAnswer)"
        >
          <span v-if="submitting" class="icon-[lucide--loader-2] w-3 h-3 animate-spin mr-1" />
          提交
        </Button>
      </div>
    </div>

    <!-- InteractionLog 已回答 -->
    <div
      v-for="item in answeredInteractions"
      :key="item.id"
      class="p-3 rounded-xl border border-border/50 bg-muted/30 space-y-1 opacity-70"
    >
      <div class="text-sm">
        <span class="text-muted-foreground">Q:</span> {{ item.question_text }}
      </div>
      <div class="text-sm">
        <span class="text-muted-foreground">A:</span> {{ item.answer_text }}
        <Badge variant="secondary" class="ml-1 text-xs">
          {{ item.answer_source === 'button' ? '按钮' : '文本' }}
        </Badge>
      </div>
    </div>
  </div>
</template>
