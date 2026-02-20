<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
import PageContainer from '~/components/layout/PageContainer.vue'
import RunnerGrid from '~/components/runners/RunnerGrid.vue'
import TokenTable from '~/components/runners/TokenTable.vue'
useHead({ title: 'Runner 管理 - Friday AI' })
const activeTab = ref('runners')
</script>
<template>
 <PageContainer>
 <div class="space-y-1">
 <div class="flex items-center gap-3">
 <div class=" rounded-xl bg-gradient-to-br from-violet-500/20 to-purple-500/10 flex items-center justify-center">
 <span class="icon-[lucide--server] text-2xl text-violet-500" />
 </div>
 <h1 class="text-2xl font-bold">Runner 管理</h1>
 </div>
 <p class="text-muted-foreground ml-12">管理和监控您的 Runner 实例</p>
 </div>
 <Tabs v-model="activeTab">
 <TabsList>
 <TabsTrigger value="runners">
 <span class="icon-[lucide--server] mr-1.5" />
 Runner 列表
 </TabsTrigger>
 <TabsTrigger value="tokens">
 <span class="icon-[lucide--key-round] mr-1.5" />
 注册令牌
 </TabsTrigger>
 </TabsList>
 <TabsContent value="runners">
 <RunnerGrid @switch-to-tokens="activeTab = 'tokens'" />
 </TabsContent>
 <TabsContent value="tokens">
 <TokenTable />
 </TabsContent>
 </Tabs>
 </PageContainer>
</template>
