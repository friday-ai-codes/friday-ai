<script setup lang="ts">
import { Button } from '~/components/ui/button'

const error = ref<Error | null>(null)
const info = ref<string>('')

onErrorCaptured((err, _instance, infoMsg) => {
  error.value = err instanceof Error ? err : new Error(String(err))
  info.value = infoMsg

  // 阻止错误继续传播
  return false
})

function reset() {
  error.value = null
  info.value = ''
}
</script>

<template>
  <div v-if="error" class="min-h-[400px] flex items-center justify-center p-6">
    <div class="max-w-md w-full text-center space-y-4">
      <div class="text-6xl mb-4">
        💥
      </div>
      <h2 class="text-2xl font-bold text-red-600">
        出错了
      </h2>
      <p class="text-muted-foreground break-words">
        {{ error.message }}
      </p>

      <div v-if="info" class="text-xs text-left bg-muted p-4 rounded overflow-auto max-h-40">
        {{ info }}
      </div>

      <div class="pt-4 flex justify-center gap-4">
        <Button variant="default" @click="reset">
          重试
        </Button>
        <Button variant="outline" @click="$router.push('/')">
          返回首页
        </Button>
      </div>
    </div>
  </div>
  <slot v-else />
</template>
