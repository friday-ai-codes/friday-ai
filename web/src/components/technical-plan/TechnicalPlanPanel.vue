<script setup lang="ts">
import { ref } from 'vue'
import { Tabs, TabsList, TabsTrigger } from '~/components/ui/tabs'
import TechnicalPlanEditor from './TechnicalPlanEditor.vue'
import TechnicalPlanViewer from './TechnicalPlanViewer.vue'
defineProps<{
 plan: Record<string, unknown> | null
 markdown: string
 validationError?: string | null
}>
const emit = defineEmits<{
 'update:markdown': [value: string]
 'save':
}>
const activeTab = ref<'markdown' | 'json'>('markdown')
</script>
<template>
 <div class="rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50 overflow-hidden">
 <!-- Header with tabs -->
 <div class="flex items-center justify-between border-b border-border/50">
 <div class="flex items-center gap-3">
 <div class=" rounded-lg bg-gradient-to-br from-emerald-500/20 to-teal-500/10">
 <span class="icon-[lucide--file-code] text-xl text-emerald-500" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">
 技术方案
 </h2>
 <p class="text-sm text-muted-foreground">
 查看或编辑技术方案
 </p>
 </div>
 </div>
 <Tabs v-model="activeTab">
 <TabsList>
 <TabsTrigger value="markdown" class="gap-2">
 <span class="icon-[lucide--file-text]" />
 Markdown
 </TabsTrigger>
 <TabsTrigger value="json" class="gap-2">
 <span class="icon-[lucide--braces]" />
 JSON
 </TabsTrigger>
 </TabsList>
 </Tabs>
 </div>
 <!-- Content -->
 <div v-if="activeTab === 'json'">
 <TechnicalPlanViewer:plan="plan" />
 </div>
 <div v-else>
 <TechnicalPlanEditor:markdown="markdown":validation-error="validationError"
 @update:markdown="emit('update:markdown', $event)"
 @save="emit('save')"
 />
 </div>
 </div>
</template>
