<script setup lang="ts">
import { computed, ref } from 'vue'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
const _props = defineProps<{
 modelValue: { from: string, to: string }
}>
const emit = defineEmits<{
 'update:modelValue': [value: { from: string, to: string }]
}>
type PresetOption = '7' | '30' | 'custom'
// 计算当前选中的预设
const selectedPreset = ref<PresetOption>('7')
// 自定义日期输入
const customFrom = ref('')
const customTo = ref('')
const presetOptions = [
 { value: '7', label: '近 7 天' },
 { value: '30', label: '近 30 天' },
 { value: 'custom', label: '自定义范围' },
] as const
const showCustomInputs = computed( => selectedPreset.value === 'custom')
function getDateString(daysAgo: number): string {
 const d = new Date
 d.setDate(d.getDate - daysAgo)
 return d.toISOString.split('T')[0]
}
function onPresetChange(value: string | number | bigint | Record<string, any> | null) {
 if (typeof value !== 'string')
 return
 selectedPreset.value = value as PresetOption
 if (value === '7' || value === '30') {
 const days = Number.parseInt(value)
 emit('update:modelValue', {
 from: getDateString(days),
 to: getDateString(0),
 })
 }
}
function onCustomDateChange {
 if (customFrom.value && customTo.value) {
 emit('update:modelValue', {
 from: customFrom.value,
 to: customTo.value,
 })
 }
}
</script>
<template>
 <div class="flex items-center gap-3">
 <Select:model-value="selectedPreset" @update:model-value="onPresetChange">
 <SelectTrigger class="w-[140px] bg-card/80 backdrop-blur-sm border-border/50">
 <SelectValue placeholder="时间范围" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem v-for="opt in presetOptions":key="opt.value":value="opt.value">
 {{ opt.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 <template v-if="showCustomInputs">
 <input
 v-model="customFrom"
 type="date"
 class=" rounded-md border border-border/50 bg-card/80 backdrop-blur-sm px-3 text-sm"
 @change="onCustomDateChange"
 >
 <span class="text-muted-foreground text-sm">至</span>
 <input
 v-model="customTo"
 type="date"
 class=" rounded-md border border-border/50 bg-card/80 backdrop-blur-sm px-3 text-sm"
 @change="onCustomDateChange"
 >
 </template>
 </div>
</template>
