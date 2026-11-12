/// <reference types="vitest/config" />
// 개발: Vite(5173) — /api 는 FastAPI(기본 8765) 로 넘긴다. CORS 를 열지 않는다 (docs/react.md 6절).
// 다른 포트의 서버를 쓰려면: API_URL=http://127.0.0.1:8766 npm run dev
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const api = process.env.API_URL ?? 'http://127.0.0.1:8765';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: api, changeOrigin: false } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: { modules: { classNameStrategy: 'non-scoped' } },
    restoreMocks: true,
  },
});
