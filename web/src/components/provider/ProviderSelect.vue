<script setup lang="ts">
import {
 Select,
 SelectContent,
 SelectGroup,
 SelectItem,
 SelectLabel,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import ProviderIcon from '~/components/provider/ProviderIcon.vue'
import ProviderBadge from '~/components/provider/ProviderBadge.vue'
import { PROVIDER_GROUPS } from '~/types/provider'
import type { ConfigSource, ProviderType } from '~/types/provider'
const props = withDefaults(defineProps<{
 modelValue?: ProviderType
 configSource?: ConfigSource
 disabled?: boolean
}>, {
 modelValue: undefined,
 configSource: undefined,
 disabled: false,
})
const emit = defineEmits<{
 (e: 'update:modelValue', value: ProviderType): void
}>
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onValueChange(value: any) {
 if (typeof value === 'string') {
 emit('update:modelValue', value as ProviderType)
 }
}
</script>
<template>
 <div class="flex items-center gap-2">
 <Select:model-value="modelValue":disabled="disabled"
 @update:model-value="onValueChange"
 >
 <SelectTrigger class="w-56 text-xs">
 <SelectValue placeholder="请选择 Provider" />
 </SelectTrigger>
 <SelectContent>
 <SelectGroup v-for="group in PROVIDER_GROUPS":key="group.label">
 <SelectLabel>{{ group.label }}</SelectLabel>
 <SelectItem
 v-for="provider in group.providers":key="provider.type":value="provider.type"
 >
 <div class="flex items-center gap-2">
 <ProviderIcon:provider="provider.type" size="sm" />
 <span>{{ provider.displayName }}</span>
 </div>
 </SelectItem>
 </SelectGroup>
 </SelectContent>
 </Select>
 <ProviderBadge v-if="configSource":source="configSource" />
 </div>
</template>
