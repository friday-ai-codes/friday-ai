<script setup lang="ts">
import { computed } from 'vue'
import { getProviderMeta } from '~/types/provider'
import type { ProviderType } from '~/types/provider'
const props = withDefaults(defineProps<{
 provider: ProviderType
 size?: 'sm' | 'md' | 'lg'
}>, {
 size: 'md',
})
const meta = computed( => getProviderMeta(props.provider))
const sizeClass = computed( => {
 switch (props.size) {
 case 'sm': return 'w-3.5 .5'
 case 'lg': return 'w-5 '
 default: return 'w-4 '
 }
})
</script>
<template>
 <span v-if="meta":class="[`icon-[${meta.icon}]`, sizeClass]" />
</template>
