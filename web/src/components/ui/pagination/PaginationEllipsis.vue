<script setup lang="ts">
import type { PaginationEllipsisProps } from 'reka-ui'
import { PaginationEllipsis } from 'reka-ui'

defineProps<PaginationEllipsisProps>()
</script>

<template>
  <PaginationEllipsis v-bind="$props">
    <span class="icon-[lucide--ellipsis] w-4 h-4" />
  </PaginationEllipsis>
</template>
