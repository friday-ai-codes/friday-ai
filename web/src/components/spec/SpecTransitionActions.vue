<script setup lang="ts">
import type { SddSpecDetail, SpecTransitionAction } from '~/api/specs'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { specsApi } from '~/api/specs'
import SpecReviewDialog from '~/components/spec/SpecReviewDialog.vue'
import { Button } from '~/components/ui/button'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { usePermission } from '~/composables/usePermission'
import { useToast } from '~/composables/useToast'

const props = defineProps<{
  spec: SddSpecDetail
}>()

const { t } = useI18n()
const { isSystemAdmin } = usePermission()
const { confirm } = useConfirmDialog()
const { handleError } = useErrorHandler()
const { success } = useToast()
const queryClient = useQueryClient()

const status = computed(() => props.spec.status)
const isAdmin = computed(() => isSystemAdmin.value)

// State × Action × 权限矩阵（50-UI-SPEC）。非 superuser 进入 in_review 仅见提示。
const canSubmit = computed(() => status.value === 'draft')
const canApprove = computed(() => status.value === 'in_review' && isAdmin.value)
const canReject = computed(() => status.value === 'in_review' && isAdmin.value)
const canMarkImplemented = computed(() => status.value === 'approved' && isAdmin.value)
const canArchive = computed(() => status.value !== 'archived' && isAdmin.value)
const showAwaiting = computed(() => status.value === 'in_review' && !isAdmin.value)

const transitionMutation = useMutation({
  mutationFn: (body: { action: SpecTransitionAction, comment?: string }) =>
    specsApi.transition(props.spec.id, body),
})
const isPending = computed(() => transitionMutation.isPending.value)

async function runTransition(
  action: SpecTransitionAction,
  toastKey: string,
  comment?: string,
) {
  try {
    await transitionMutation.mutateAsync({ action, comment })
    queryClient.invalidateQueries({ queryKey: ['specs'] })
    queryClient.invalidateQueries({ queryKey: ['spec', props.spec.id] })
    success(t(toastKey))
  }
  catch (e) {
    handleError(e, t('specs.error.transition'))
  }
}

// ---- 评审对话框（批准 / 驳回，带 comment）----
const dialogOpen = ref(false)
const dialogMode = ref<'approve' | 'reject'>('approve')

function openReview(mode: 'approve' | 'reject') {
  dialogMode.value = mode
  dialogOpen.value = true
}

async function onReviewConfirm(comment: string) {
  dialogOpen.value = false
  const action = dialogMode.value
  const toastKey = action === 'approve' ? 'specs.toast.approved' : 'specs.toast.rejected'
  await runTransition(action, toastKey, comment)
}

function onReviewCancel() {
  dialogOpen.value = false
}

// ---- 提交评审（无 comment）----
async function onSubmit() {
  await runTransition('submit_for_review', 'specs.toast.submitted')
}

// ---- 归档 / 标记已实现（无输入二次确认）----
async function onArchive() {
  const ok = await confirm({
    title: t('specs.confirm.archiveTitle'),
    description: t('specs.confirm.archiveDescription'),
    confirmText: t('specs.confirm.archiveConfirmText'),
    variant: 'destructive',
  })
  if (!ok)
    return
  await runTransition('archive', 'specs.toast.archived')
}

async function onMarkImplemented() {
  const ok = await confirm({
    title: t('specs.confirm.implementTitle'),
    description: t('specs.confirm.implementDescription'),
  })
  if (!ok)
    return
  await runTransition('mark_implemented', 'specs.toast.implemented')
}
</script>

<template>
  <div data-testid="spec-transition-actions">
    <p v-if="showAwaiting" class="text-sm text-muted-foreground">
      <span class="icon-[lucide--clock] mr-1.5 align-text-bottom" aria-hidden="true" />
      {{ t('specs.actions.awaitingReview') }}
    </p>
    <div v-else class="flex flex-wrap gap-2">
      <Button v-if="canSubmit" :disabled="isPending" @click="onSubmit">
        <span
          class="mr-1.5"
          :class="isPending ? 'icon-[lucide--loader-circle] animate-spin' : 'icon-[lucide--send]'"
          aria-hidden="true"
        />
        {{ t('specs.actions.submit') }}
      </Button>
      <Button v-if="canApprove" :disabled="isPending" @click="openReview('approve')">
        <span class="icon-[lucide--check] mr-1.5" aria-hidden="true" />
        {{ t('specs.actions.approve') }}
      </Button>
      <Button
        v-if="canReject"
        variant="destructive"
        :disabled="isPending"
        @click="openReview('reject')"
      >
        <span class="icon-[lucide--x] mr-1.5" aria-hidden="true" />
        {{ t('specs.actions.reject') }}
      </Button>
      <Button
        v-if="canMarkImplemented"
        :disabled="isPending"
        @click="onMarkImplemented"
      >
        <span class="icon-[lucide--check-check] mr-1.5" aria-hidden="true" />
        {{ t('specs.actions.markImplemented') }}
      </Button>
      <Button
        v-if="canArchive"
        variant="outline"
        :disabled="isPending"
        @click="onArchive"
      >
        <span class="icon-[lucide--archive] mr-1.5" aria-hidden="true" />
        {{ t('specs.actions.archive') }}
      </Button>
    </div>

    <SpecReviewDialog
      :open="dialogOpen"
      :mode="dialogMode"
      @confirm="onReviewConfirm"
      @cancel="onReviewCancel"
    />
  </div>
</template>
