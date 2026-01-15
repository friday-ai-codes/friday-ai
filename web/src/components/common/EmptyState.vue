<script setup lang="ts">
import { Button } from '~/components/ui/button'
withDefaults(defineProps<{
 icon?: string
 title?: string
 description?: string
 actionLabel?: string
}>, {
 icon: 'lucide--inbox',
 title: '暂无数据',
 description: '这里还没有任何内容',
})
const emit = defineEmits<{
 action:
}>
</script>
<template>
 <div class="flex flex-col items-center justify-center py-12 text-center">
 <span class="text-5xl text-muted-foreground mb-4":class="[`icon-[${icon}]`]" />
 <h3 class="text-lg font-medium text-foreground mb-2">
 {{ title }}
 </h3>
 <p class="text-muted-foreground mb-6 max-w-sm">
 {{ description }}
 </p>
 <Button v-if="actionLabel" @click="emit('action')">
 {{ actionLabel }}
 </Button>
 </div>
</template>
