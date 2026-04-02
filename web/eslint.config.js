import antfu from '@antfu/eslint-config'
export default antfu({
 formatters: true,
 vue: true,
 markdown: false,
 rules: {
 'no-console': 'warn',
 '@typescript-eslint/no-explicit-any': 'warn',
 'no-restricted-imports': ['error', {
 paths: [{
 name: 'vue-sonner',
 importNames: ['toast'],
 message: '请使用 useErrorHandler 处理错误通知，或 useToast 处理非错误通知。禁止直接导入 vue-sonner。',
 }],
 }],
 },
}, {
 files: ['src/composables/useToast.ts'],
 rules: {
 'no-restricted-imports': 'off',
 },
})
