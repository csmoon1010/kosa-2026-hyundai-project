// ESLint (flat config) — 포맷은 Prettier 가 맡는다.
import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'src/api/schema.d.ts'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    plugins: { 'react-hooks': reactHooks, 'react-refresh': reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // 컴포넌트에서 fetch 를 직접 쓰지 않는다 — src/api/ 를 거친다 (docs/react.md 8.1)
      'no-restricted-globals': ['error', { name: 'fetch', message: 'src/api/ 의 함수를 쓰세요' }],
    },
  },
  { files: ['src/api/**', 'src/test/**'], rules: { 'no-restricted-globals': 'off' } },
);
