<script setup lang="ts">
import { computed, onMounted } from 'vue'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { useSpacesStore } from '~/stores/spaces'
const props = defineProps<{
 modelValue: string | null
}>
const emit = defineEmits<{
 (e: 'update:modelValue', value: string | null): void
}>
const ALL_VALUE = '__all__'
const spacesStore = useSpacesStore
const spaces = computed( => spacesStore.spaces)
const loading = computed( => spacesStore.loading)
const selectValue = computed<string>({
 get: => props.modelValue ?? ALL_VALUE,
 set: (val) => {
 emit('update:modelValue', val === ALL_VALUE ? null: val)
 },
})
onMounted(async => {
 if (spacesStore.spaces.length === 0)
 await spacesStore.fetchSpaces
})
</script>
<template>
 <Select v-model="selectValue":disabled="loading">
 <SelectTrigger class="min-w-[180px] glass-card border-white/15 text-white text-sm ">
 <SelectValue placeholder="全部空间" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem:value="ALL_VALUE">
 全部空间
 </SelectItem>
 <SelectItem
 v-for="space in spaces":key="space.id":value="space.id"
 >
 {{ space.name }}
 </SelectItem>
 </SelectContent>
 </Select>
</template>
