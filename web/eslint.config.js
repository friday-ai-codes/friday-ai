import antfu from '@antfu/eslint-config'
export default antfu({
 formatters: true,
 vue: true,
 markdown: false,
 rules: {
 'no-console': 'warn',
 '@typescript-eslint/no-explicit-any': 'warn',
 },
})
