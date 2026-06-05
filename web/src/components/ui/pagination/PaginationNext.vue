<script setup lang="ts">
import { PaginationNext as RekaNext } from 'reka-ui'
import { Button } from '~/components/ui/button'
</script>

<template>
  <RekaNext as-child>
    <Button variant="outline" size="icon" class="w-8 h-8">
      <span class="icon-[lucide--chevron-right] w-4 h-4" />
    </Button>
  </RekaNext>
</template>
