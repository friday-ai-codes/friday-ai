<script setup lang="ts">
import { computed } from 'vue'
import BaseModal from '~/components/modal/BaseModal.vue'
import { Button } from '~/components/ui/button'

const props = withDefaults(defineProps<{
  open: boolean
  title?: string
  description?: string
  confirmText?: string
  cancelText?: string
  variant?: 'default' | 'destructive'
  loading?: boolean
}>(), {
  title: '确认操作',
  description: '确定要执行此操作吗？',
  confirmText: '确认',
  cancelText: '取消',
  variant: 'default',
  loading: false,
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  'confirm': []
  'cancel': []
}>()

const isOpen = computed({
  get: () => props.open,
  set: value => emit('update:open', value),
})

function handleConfirm() {
  emit('confirm')
}

function handleCancel() {
  emit('cancel')
  emit('update:open', false)
}
</script>

<template>
  <BaseModal
    v-model="isOpen"
    :title="title"
    size="sm"
    :show-close="false"
  >
    <div class="text-sm text-muted-foreground">
      {{ description }}
    </div>

    <template #footer>
      <div class="flex justify-end gap-3 w-full">
        <Button variant="outline" :disabled="loading" @click="handleCancel">
          {{ cancelText }}
        </Button>
        <Button
          :variant="variant"
          :disabled="loading"
          @click="handleConfirm"
        >
          <span v-if="loading" class="icon-[lucide--loader-circle] animate-spin mr-2" />
          {{ confirmText }}
        </Button>
      </div>
    </template>
  </BaseModal>
</template>
