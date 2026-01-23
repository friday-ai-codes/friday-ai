<script setup lang="ts">
import { GitBranch, Play, Plus } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from '~/components/ui/card'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
const router = useRouter
const store = useWorkflowsStore
const { workflows, loading } = storeToRefs(store)
onMounted( => {
 store.fetchWorkflows
})
function navigateToEditor(id: string) {
 router.push(`/workflows/${id}`)
}
</script>
<template>
 <div class="container py-6 space-y-6">
 <div class="flex items-center justify-between">
 <div>
 <h1 class="text-3xl font-bold tracking-tight">
 Workflows
 </h1>
 <p class="text-muted-foreground mt-2">
 Manage and automate your development processes.
 </p>
 </div>
 <Button>
 <Plus class="w-4 mr-2" />
 New Workflow
 </Button>
 </div>
 <div v-if="loading" class="flex justify-center py-12">
 <div class="animate-spin rounded-full w-8 border-b-2 border-primary" />
 </div>
 <div v-else-if="workflows.length === 0" class="text-center py-12 border rounded-lg bg-muted/10">
 <GitBranch class="w-12 mx-auto text-muted-foreground mb-4" />
 <h3 class="text-lg font-medium">
 No workflows found
 </h3>
 <p class="text-muted-foreground mb-4">
 Create your first workflow to start automating.
 </p>
 <Button>Create Workflow</Button>
 </div>
 <div v-else class="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
 <Card v-for="workflow in workflows":key="workflow.id" class="hover:border-primary/50 transition-colors cursor-pointer" @click="navigateToEditor(workflow.id)">
 <CardHeader>
 <div class="flex items-center justify-between">
 <Badge variant="outline" class="capitalize">
 {{ workflow.trigger_type }}
 </Badge>
 <div class="flex space-x-2">
 <Button variant="ghost" size="icon" @click.stop>
 <Play class="w-4 " />
 </Button>
 </div>
 </div>
 <CardTitle class="mt-4">
 {{ workflow.name }}
 </CardTitle>
 <CardDescription class="line-clamp-2">
 {{ workflow.description || 'No description' }}
 </CardDescription>
 </CardHeader>
 <CardFooter class="text-xs text-muted-foreground">
 Updated {{ new Date(workflow.updated_at).toLocaleDateString }}
 </CardFooter>
 </Card>
 </div>
 </div>
</template>
