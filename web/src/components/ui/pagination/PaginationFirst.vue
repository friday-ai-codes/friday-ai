<script setup lang="ts">
import { PaginationFirst as RekaFirst } from 'reka-ui'
import { Button } from '~/components/ui/button'
</script>

<template>
  <RekaFirst as-child>
    <Button variant="outline" size="icon" class="w-8 h-8">
      <span class="icon-[lucide--chevrons-left] w-4 h-4" />
    </Button>
  </RekaFirst>
</template>
