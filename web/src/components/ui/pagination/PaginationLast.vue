<script setup lang="ts">
import { PaginationLast as RekaLast } from 'reka-ui'
import { Button } from '~/components/ui/button'
</script>

<template>
  <RekaLast as-child>
    <Button variant="outline" size="icon" class="w-8 h-8">
      <span class="icon-[lucide--chevrons-right] w-4 h-4" />
    </Button>
  </RekaLast>
</template>
