<script setup lang="ts">
import X6BaseNode from './X6BaseNode.vue'
/**
 * X6ConditionNode - Condition/branching node with amber gradient styling.
 *
 * Visual identity per CONTEXT.md:
 * - Amber gradient icon background (from-amber-500/20 to-orange-400/10)
 * - Horizontal layout (icon on left, text on right)
 * - GitBranch icon for conditional branching
 */
</script>
<template>
 <X6BaseNode v-slot="{ label, description, shortId }">
 <div class="flex items-center gap-3 px-4 py-3">
 <!-- Icon with amber gradient background -->
 <div class="shrink-0 .5 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-400/10">
 <span class="icon-[lucide--git-branch] text-lg text-amber-500" />
 </div>
 <!-- Title + description (vertical stack) -->
 <div class="flex-1 min-w-0">
 <div
 class="font-medium text-sm truncate":title="label"
 >
 {{ label }}
 </div>
 <div
 v-if="description"
 class="text-xs text-muted-foreground truncate mt-0.5":title="description"
 >
 {{ description }}
 </div>
 <!-- Node ID (short ID for display) -->
 <div class="text-[10px] text-muted-foreground/60 font-mono mt-0.5 truncate":title="shortId">
 {{ shortId }}
 </div>
 </div>
 </div>
 </X6BaseNode>
</template>
