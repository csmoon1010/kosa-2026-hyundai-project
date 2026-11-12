// 화면 끝까지 테스트 — 실제 FastAPI 서버(가짜 LLM · 임시 data)와 Vite 개발 서버를 띄워 브라우저로 (docs/react.md 8.3).
//   npm run test:e2e
// 처음 한 번: npx playwright install chromium  (WSL 에서 라이브러리가 없다면 sudo npx playwright install-deps chromium)
import { defineConfig, devices } from '@playwright/test';

const API_PORT = 8799;
const WEB_PORT = 5199;

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  // 실제 서버 — 화면 데이터 API 가 요청마다 데이터를 새로 만들고, 가짜 IR 생성도 자료를 읽는다. 5초 기본값은 빠듯하다
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `../.venv/bin/python -m tap.cli serve --fake-llm --temp-data --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/common/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      env: { API_URL: `http://127.0.0.1:${API_PORT}` },
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
