<script setup lang="ts">
import X6BaseNode from './X6BaseNode.vue'
/**
 * X6ConditionNode - Condition/branching node with amber gradient styling.
 *
 * Visual identity per CONTEXT.md:
 * - Amber gradient icon background (from-amber-500/20 to-orange-400/10)
 * - Vertical layout (icon on top, text below)
 * - GitBranch icon for conditional branching
 */
</script>
<template>
 <X6BaseNode v-slot="{ label, description }">
 <div class="flex flex-col items-center gap-2 ">
 <!-- Icon with amber gradient background -->
 <div class=" rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-400/10">
 <span class="icon-[lucide--git-branch] text-xl text-amber-500" />
 </div>
 <!-- Title + description (vertical stack) -->
 <div class="text-center">
 <div
 class="font-semibold text-sm truncate max-w-[200px]":title="label"
 >
 {{ label }}
 </div>
 <div
 v-if="description"
 class="text-xs text-muted-foreground truncate max-w-[200px]":title="description"
 >
 {{ description }}
 </div>
 </div>
 </div>
 </X6BaseNode>
</template>
