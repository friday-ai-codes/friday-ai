<script setup lang="ts">
import type { NodeExecution } from '~/stores/useExecutionsStore'
import { computed, ref } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
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

const props = defineProps<{
  nodeExecution: NodeExecution
}>()

const emit = defineEmits<{
  actionComplete: []
}>()

const store = useExecutionsStore()
const { handleError } = useErrorHandler()
const { success } = useToast()

const comment = ref('')
const rejectDialogOpen = ref(false)
const submitting = ref(false)

const approval = computed(() => props.nodeExecution.output_data || props.nodeExecution.approval_data || {})
const title = computed(() => approval.value.title || props.nodeExecution.node_name || '人工审批')
const description = computed(() => approval.value.description || '')
const displayData = computed(() => approval.value.display_data || {})
const hasDisplayData = computed(() => Object.keys(displayData.value).length > 0)
const isWaiting = computed(() => props.nodeExecution.status === 'waiting_approval')
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

    <div v-if="hasDisplayData" class="rounded-md bg-muted/60 p-3">
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
        <label class="text-xs font-medium text-muted-foreground">备注（可选）</label>
        <Textarea
          v-model="comment"
          placeholder="添加审批备注..."
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
          确认拒绝「{{ title }}」？
        </DialogDescription>
      </DialogHeader>
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
