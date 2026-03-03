<script setup lang="ts">
import type { DialogTitleProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { DialogTitle } from 'reka-ui'
import { cn } from '~/lib/utils'
const props = defineProps<DialogTitleProps & { class?: HTMLAttributes['class'] }>
</script>
<template>
 <DialogTitle:class="cn('text-lg font-semibold text-foreground', props.class)">
 <slot />
 </DialogTitle>
</template>
