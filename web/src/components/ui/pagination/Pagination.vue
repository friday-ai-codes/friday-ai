<script setup lang="ts">
import type { PaginationRootEmits, PaginationRootProps } from 'reka-ui'
import { PaginationList, PaginationRoot } from 'reka-ui'
import { cn } from '~/lib/utils'
import PaginationEllipsis from './PaginationEllipsis.vue'
import PaginationFirst from './PaginationFirst.vue'
import PaginationLast from './PaginationLast.vue'
import PaginationNext from './PaginationNext.vue'
import PaginationPrev from './PaginationPrev.vue'
import { Button } from '~/components/ui/button'
const props = withDefaults(defineProps<PaginationRootProps & { class?: string }>, {
 showEdges: true,
 defaultPage: 1,
})
const emit = defineEmits<PaginationRootEmits>
</script>
<template>
 <PaginationRoot
 v-slot="{ page }"
 v-bind="props":class="cn('mx-auto flex w-full justify-center', props.class)"
 @update:page="emit('update:page', $event)"
 >
 <PaginationList v-slot="{ items }" class="flex items-center gap-1">
 <PaginationFirst />
 <PaginationPrev />
 <template v-for="(item, index) in items">
 <PaginationEllipsis
 v-if="item.type === 'ellipsis'":key="`ellipsis-${index}`":index="index"
 />
 <Button
 v-else:key="`page-${item.value}`":variant="item.value === page ? 'default': 'outline'"
 size="icon"
 class="w-8 "
 @click="emit('update:page', item.value)"
 >
 {{ item.value }}
 </Button>
 </template>
 <PaginationNext />
 <PaginationLast />
 </PaginationList>
 </PaginationRoot>
</template>
