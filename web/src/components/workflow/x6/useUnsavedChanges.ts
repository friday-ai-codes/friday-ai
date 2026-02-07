import { onMounted, onUnmounted } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
/**
 * Protect against losing unsaved changes.
 *
 * Per CONTEXT.md decision:
 * - Show "unsaved" marker (handled by UI reading hasUnsavedChanges)
 * - Confirm before leaving page
 *
 * Handles two scenarios:
 * 1. Browser close/reload (beforeunload event)
 * 2. Vue Router navigation (onBeforeRouteLeave guard)
 */
export function useUnsavedChanges(isDirty: => boolean) {
 /**
 * Browser close/reload handler
 */
 function handleBeforeUnload(e: BeforeUnloadEvent) {
 if (isDirty) {
 // Standard way to trigger browser's "Leave site?" dialog
 e.preventDefault
 e.returnValue = '' // Required for Chrome
 }
 }
 onMounted( => {
 window.addEventListener('beforeunload', handleBeforeUnload)
 })
 onUnmounted( => {
 window.removeEventListener('beforeunload', handleBeforeUnload)
 })
 /**
 * Vue Router navigation handler
 * Shows confirm dialog if there are unsaved changes
 */
 onBeforeRouteLeave((_to, _from, next) => {
 if (isDirty) {
 const answer = window.confirm(
 '你有未保存的更改。确定要离开吗？\nYou have unsaved changes. Are you sure you want to leave?'
 )
 next(answer)
 } else {
 next
 }
 })
}
