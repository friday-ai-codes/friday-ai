<script setup lang="ts">
import { PaginationPrev as RekaPrev } from 'reka-ui'
import { Button } from '~/components/ui/button'
</script>
<template>
 <RekaPrev as-child>
 <Button variant="outline" size="icon" class="w-8 ">
 <span class="icon-[lucide--chevron-left] w-4 " />
 </Button>
 </RekaPrev>
</template>
