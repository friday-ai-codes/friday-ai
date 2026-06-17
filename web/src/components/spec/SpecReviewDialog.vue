<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { Textarea } from '~/components/ui/textarea'

const props = defineProps<{
  open: boolean
  mode: 'approve' | 'reject'
}>()

const emit = defineEmits<{
  confirm: [comment: string]
  cancel: []
}>()

const { t } = useI18n()
const comment = ref('')

// 每次打开清空输入，避免上次残留。
watch(
  () => props.open,
  (open) => {
    if (open)
      comment.value = ''
  },
)

const isReject = computed(() => props.mode === 'reject')
const title = computed(() =>
  isReject.value ? t('specs.reviewDialog.rejectTitle') : t('specs.reviewDialog.approveTitle'),
)
const description = computed(() =>
  isReject.value
    ? t('specs.reviewDialog.rejectDescription')
    : t('specs.reviewDialog.approveDescription'),
)
const placeholder = computed(() =>
  isReject.value
    ? t('specs.reviewDialog.commentRequired')
    : t('specs.reviewDialog.commentOptional'),
)
// reject 的 comment 必填：空则禁用确认（前端校验，后端二次拦截）。
const confirmDisabled = computed(() => isReject.value && comment.value.trim().length === 0)

function onConfirm() {
  if (confirmDisabled.value)
    return
  emit('confirm', comment.value.trim())
}

function onOpenChange(value: boolean) {
  if (!value)
    emit('cancel')
}
</script>

<template>
  <Dialog :open="open" @update:open="onOpenChange">
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{{ title }}</DialogTitle>
        <DialogDescription>{{ description }}</DialogDescription>
      </DialogHeader>
      <div class="space-y-1.5">
        <label class="text-sm font-medium">{{ t('specs.reviewDialog.commentLabel') }}</label>
        <Textarea v-model="comment" :placeholder="placeholder" />
      </div>
      <DialogFooter>
        <Button variant="outline" @click="emit('cancel')">
          {{ t('specs.reviewDialog.cancel') }}
        </Button>
        <Button
          :variant="isReject ? 'destructive' : 'default'"
          :disabled="confirmDisabled"
          @click="onConfirm"
        >
          {{ t('specs.reviewDialog.confirm') }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
