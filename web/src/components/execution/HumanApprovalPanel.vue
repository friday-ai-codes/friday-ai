<script setup lang="ts">
import type { NodeExecution } from '~/stores/useExecutionsStore'
import { computed, ref } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '~/components/ui/collapsible'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { Separator } from '~/components/ui/separator'
import { Textarea } from '~/components/ui/textarea'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import { useExecutionsStore } from '~/stores/useExecutionsStore'

/**
 * HumanApprovalPanel — 人工审批面板（C2 合并方案审批）。
 *
 * 同时承载：
 * - 通用控制台审批（mode=generic）：标题/说明/展示数据 + 通过/拒绝。
 * - 方案+飞书卡片审批（mode=plan_feishu，吸收原 PlanApprovalPanel）：方案摘要/任务/风险/
 *   假设折叠展示 + 文档链接。
 *
 * 兼容 waiting_approval（统一审批通道）与存量 waiting_event（C2 合并前在途执行）。
 */

const props = defineProps<{
  nodeExecution: NodeExecution
}>()

const emit = defineEmits<{
  actionComplete: []
}>()

const store = useExecutionsStore()
const { handleError } = useErrorHandler()
const { success, error: showError } = useToast()

const comment = ref('')
const rejectDialogOpen = ref(false)
const submitting = ref(false)

// 折叠面板状态（方案审批）
const tasksOpen = ref(false)
const risksOpen = ref(false)
const assumptionsOpen = ref(false)

// 数据源合并：waiting 态数据落 approval_data，completed 态合并到 output_data。
// 二者合并保证两阶段都能取到（output_data 优先覆盖 approval_data）。
const data = computed<Record<string, any>>(() => ({
  ...(props.nodeExecution.approval_data || {}),
  ...(props.nodeExecution.output_data || {}),
}))

const title = computed(() => data.value.title || props.nodeExecution.node_name || '人工审批')
const description = computed(() => data.value.description || '')
const displayData = computed(() => data.value.display_data || {})
const hasDisplayData = computed(() => Object.keys(displayData.value).length > 0)

// 方案数据（mode=plan_feishu 时存在）
const planData = computed<Record<string, any> | null>(() => {
  const plan = data.value.plan
  return plan && typeof plan === 'object' ? plan : null
})
const hasPlan = computed(() => planData.value !== null)
const planSummary = computed(() => planData.value?.summary || '')
const planTasks = computed((): Record<string, any>[] =>
  planData.value?.tasks || planData.value?.execution_plan || [],
)
const planRisks = computed((): (string | Record<string, any>)[] => planData.value?.risks || [])
const planAssumptions = computed((): (string | Record<string, any>)[] => planData.value?.assumptions || [])
const documentUrl = computed(() => data.value.document_url || '')

const isWaiting = computed(() =>
  ['waiting_approval', 'waiting_event'].includes(props.nodeExecution.status),
)
const isCompleted = computed(() => props.nodeExecution.status === 'completed')
const approvalResult = computed(() => props.nodeExecution.output_data?._next_handle)
const rejectReason = computed(() => props.nodeExecution.output_data?.reject_reason || '')

async function approve() {
  submitting.value = true
  try {
    await store.approveNode(props.nodeExecution.id, comment.value)
    comment.value = ''
    success('审批已通过')
    emit('actionComplete')
  }
  catch (e: unknown) {
    handleError(e, '审批')
  }
  finally {
    submitting.value = false
  }
}

async function reject() {
  if (!comment.value.trim()) {
    showError('请输入拒绝理由')
    return
  }
  submitting.value = true
  try {
    await store.rejectNode(props.nodeExecution.id, comment.value)
    rejectDialogOpen.value = false
    comment.value = ''
    success('审批已拒绝')
    emit('actionComplete')
  }
  catch (e: unknown) {
    handleError(e, '拒绝审批')
  }
  finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="rounded-lg border border-border/60 bg-card p-4 space-y-4">
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0 space-y-1">
        <div class="flex items-center gap-2">
          <span class="icon-[lucide--user-check] w-4 h-4 text-amber-600" />
          <h3 class="text-sm font-semibold truncate">
            {{ title }}
          </h3>
        </div>
        <p v-if="description" class="text-xs text-muted-foreground leading-relaxed">
          {{ description }}
        </p>
        <a
          v-if="documentUrl"
          :href="documentUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="text-xs text-primary hover:underline flex items-center gap-1"
        >
          <span class="icon-[lucide--external-link] w-3 h-3" />
          查看完整文档
        </a>
      </div>

      <Badge v-if="isWaiting" class="bg-amber-500/10 text-amber-700 border-amber-500/20">
        待审批
      </Badge>
      <Badge
        v-else-if="isCompleted && approvalResult === 'approved'"
        class="bg-emerald-500/10 text-emerald-700 border-emerald-500/20"
      >
        已通过
      </Badge>
      <Badge
        v-else-if="isCompleted && approvalResult === 'rejected'"
        class="bg-red-500/10 text-red-700 border-red-500/20"
      >
        已拒绝
      </Badge>
    </div>

    <!-- 方案摘要（mode=plan_feishu） -->
    <div v-if="planSummary" class="space-y-1.5">
      <div class="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
        <span class="icon-[lucide--align-left] w-3.5 h-3.5" />
        方案摘要
      </div>
      <p class="text-sm leading-relaxed whitespace-pre-wrap">
        {{ planSummary }}
      </p>
    </div>

    <!-- 任务列表（折叠） -->
    <Collapsible v-if="planTasks.length > 0" v-model:open="tasksOpen">
      <CollapsibleTrigger class="flex items-center justify-between w-full py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors">
        <span class="flex items-center gap-2">
          <span class="icon-[lucide--list-checks] w-4 h-4 text-violet-500" />
          任务列表
          <Badge variant="secondary" class="text-[10px] px-1.5 py-0">
            {{ planTasks.length }}
          </Badge>
        </span>
        <span
          class="icon-[lucide--chevron-down] w-4 h-4 transition-transform duration-200"
          :class="{ 'rotate-180': tasksOpen }"
        />
      </CollapsibleTrigger>
      <CollapsibleContent class="space-y-2 pt-2">
        <div
          v-for="(task, index) in planTasks"
          :key="index"
          class="rounded-xl border border-border/40 p-3"
        >
          <div class="flex items-start gap-2">
            <span class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-violet-500/10 text-violet-600 text-[10px] font-bold">
              {{ index + 1 }}
            </span>
            <div class="space-y-1 flex-1 min-w-0">
              <div class="text-sm font-medium">
                {{ task.name || task.title || `Task ${index + 1}` }}
              </div>
              <p v-if="task.description" class="text-xs text-muted-foreground leading-relaxed">
                {{ task.description }}
              </p>
              <div v-if="task.repository" class="flex items-center gap-1 text-[10px] text-muted-foreground">
                <span class="icon-[lucide--git-branch] w-3 h-3" />
                {{ task.repository }}
              </div>
            </div>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>

    <!-- 风险（折叠） -->
    <Collapsible v-if="planRisks.length > 0" v-model:open="risksOpen">
      <CollapsibleTrigger class="flex items-center justify-between w-full py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors">
        <span class="flex items-center gap-2">
          <span class="icon-[lucide--alert-triangle] w-4 h-4 text-amber-500" />
          风险
          <Badge variant="secondary" class="text-[10px] px-1.5 py-0">
            {{ planRisks.length }}
          </Badge>
        </span>
        <span
          class="icon-[lucide--chevron-down] w-4 h-4 transition-transform duration-200"
          :class="{ 'rotate-180': risksOpen }"
        />
      </CollapsibleTrigger>
      <CollapsibleContent class="space-y-1.5 pt-2">
        <div
          v-for="(risk, index) in planRisks"
          :key="index"
          class="flex items-start gap-2 text-sm p-2 rounded-lg bg-amber-500/5 border border-amber-500/10"
        >
          <span class="icon-[lucide--alert-triangle] w-3.5 h-3.5 text-amber-500 mt-0.5 shrink-0" />
          <span>{{ typeof risk === 'string' ? risk : risk.description || risk.name || JSON.stringify(risk) }}</span>
        </div>
      </CollapsibleContent>
    </Collapsible>

    <!-- 假设（折叠） -->
    <Collapsible v-if="planAssumptions.length > 0" v-model:open="assumptionsOpen">
      <CollapsibleTrigger class="flex items-center justify-between w-full py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors">
        <span class="flex items-center gap-2">
          <span class="icon-[lucide--lightbulb] w-4 h-4 text-primary" />
          假设
          <Badge variant="secondary" class="text-[10px] px-1.5 py-0">
            {{ planAssumptions.length }}
          </Badge>
        </span>
        <span
          class="icon-[lucide--chevron-down] w-4 h-4 transition-transform duration-200"
          :class="{ 'rotate-180': assumptionsOpen }"
        />
      </CollapsibleTrigger>
      <CollapsibleContent class="space-y-1.5 pt-2">
        <div
          v-for="(assumption, index) in planAssumptions"
          :key="index"
          class="flex items-start gap-2 text-sm p-2 rounded-lg bg-primary/5 border border-primary/10"
        >
          <span class="icon-[lucide--lightbulb] w-3.5 h-3.5 text-primary mt-0.5 shrink-0" />
          <span>{{ typeof assumption === 'string' ? assumption : assumption.description || assumption.name || JSON.stringify(assumption) }}</span>
        </div>
      </CollapsibleContent>
    </Collapsible>

    <!-- 通用审批展示数据（mode=generic） -->
    <div v-if="!hasPlan && hasDisplayData" class="rounded-md bg-muted/60 p-3">
      <div class="mb-2 text-xs font-medium text-muted-foreground">
        审批数据
      </div>
      <pre class="max-h-48 overflow-auto text-xs leading-relaxed">{{ JSON.stringify(displayData, null, 2) }}</pre>
    </div>

    <div v-if="isCompleted && approvalResult === 'rejected' && rejectReason" class="rounded-md border border-red-500/20 bg-red-500/5 p-3">
      <div class="mb-1 text-xs font-medium text-red-700">
        拒绝原因
      </div>
      <p class="text-sm text-red-700/90">
        {{ rejectReason }}
      </p>
    </div>

    <template v-if="isWaiting">
      <Separator />
      <div class="space-y-2">
        <label class="text-xs font-medium text-muted-foreground">备注 / 拒绝理由</label>
        <Textarea
          v-model="comment"
          placeholder="通过可留空；拒绝时请填写理由..."
          class="min-h-20"
        />
      </div>
      <div class="flex gap-2">
        <Button
          variant="destructive"
          class="flex-1"
          :disabled="submitting"
          @click="rejectDialogOpen = true"
        >
          <span class="icon-[lucide--x-circle] w-4 h-4 mr-2" />
          拒绝
        </Button>
        <Button
          class="flex-1"
          :disabled="submitting"
          @click="approve"
        >
          <span class="icon-[lucide--check-circle] w-4 h-4 mr-2" />
          通过
        </Button>
      </div>
    </template>
  </div>

  <Dialog v-model:open="rejectDialogOpen">
    <DialogContent>
      <DialogHeader>
        <DialogTitle>拒绝审批</DialogTitle>
        <DialogDescription>
          确认拒绝「{{ title }}」？拒绝理由将通过飞书通知方案作者。
        </DialogDescription>
      </DialogHeader>
      <div class="space-y-3">
        <Textarea
          v-model="comment"
          placeholder="请输入拒绝理由..."
          class="min-h-24"
        />
      </div>
      <DialogFooter>
        <Button variant="outline" @click="rejectDialogOpen = false">
          取消
        </Button>
        <Button variant="destructive" :disabled="submitting" @click="reject">
          确认拒绝
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
