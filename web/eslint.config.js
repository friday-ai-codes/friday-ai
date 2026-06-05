import antfu from '@antfu/eslint-config'

export default antfu({
  formatters: true,
  vue: true,
  markdown: false,
  rules: {
    'no-console': 'off',
    'no-restricted-imports': 'off',
    'no-unsafe-finally': 'off',
    '@typescript-eslint/no-explicit-any': 'off',
    'jsdoc/check-param-names': 'off',
    'node/prefer-global/process': 'off',
    'pnpm/yaml-no-unused-catalog-item': 'off',
    'regexp/no-unused-capturing-group': 'off',
    'style/max-statements-per-line': 'off',
    'test/prefer-hooks-in-order': 'off',
    'ts/no-use-before-define': 'off',
    'unused-imports/no-unused-vars': 'off',
    'vue/custom-event-name-casing': 'off',
  },
}, {
  files: ['src/composables/useToast.ts'],
  rules: {
    'no-restricted-imports': 'off',
  },
})
