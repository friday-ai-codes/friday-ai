<script setup lang="ts">
import { ref } from 'vue'
import { VueFinalModal } from 'vue-final-modal'
import { Button } from '~/components/ui/button'

interface Props {
  title?: string
  size?: 'sm' | 'md' | 'lg' | 'xl'
  confirmText?: string
  cancelText?: string
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  title: '',
  size: 'md',
  confirmText: '保存',
  cancelText: '取消',
  loading: false,
})

const emit = defineEmits<{
  confirm: [data?: unknown]
  cancel: []
  closed: []
  submit: []
}>()

const isLoading = ref(props.loading)

const sizeClasses: Record<string, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
}

function handleSubmit() {
  emit('submit')
}

function handleCancel() {
  emit('cancel')
}
</script>

<template>
  <VueFinalModal
    class="flex justify-center items-center"
    :content-class="`flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 w-full mx-4 ${sizeClasses[size]}`"
    overlay-transition="vfm-fade"
    content-transition="vfm-zoom"
    @closed="emit('closed')"
  >
    <!-- Header -->
    <div class="flex items-center justify-between px-6 py-4 border-b border-border/30">
      <h3 class="text-lg font-semibold text-foreground">
        {{ title }}
      </h3>
      <button
        type="button"
        class="text-muted-foreground hover:text-foreground transition-colors"
        @click="handleCancel"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>

    <!-- Body (Form Content) -->
    <form class="flex-1 overflow-y-auto" @submit.prevent="handleSubmit">
      <div class="px-6 py-4">
        <slot />
      </div>

      <!-- Footer -->
      <div class="flex justify-end gap-3 px-6 py-4 border-t border-border/30">
        <Button type="button" variant="outline" :disabled="isLoading" @click="handleCancel">
          {{ cancelText }}
        </Button>
        <Button type="submit" :disabled="isLoading">
          <span v-if="isLoading" class="mr-2">
            <svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          </span>
          {{ confirmText }}
        </Button>
      </div>
    </form>
  </VueFinalModal>
</template>
