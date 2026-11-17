// Catches what a missing build step would: undefined names (a forgotten import), assignments to
// imports (ES modules cannot reassign them: use the setters of state.js), unused variables.
import globals from 'globals';
export default [{
  files: ['**/*.js'],
  languageOptions: { ecmaVersion: 2023, sourceType: 'module', globals: { ...globals.browser, ...globals.serviceworker, Chart: 'readonly' } },
  rules: { 'no-undef': 'error', 'no-import-assign': 'error', 'no-unused-vars': ['warn', { args: 'none', caughtErrors: 'none' }],
    'no-redeclare': 'error', 'no-const-assign': 'error', 'no-dupe-keys': 'error', 'no-unreachable': 'error' },
}];
