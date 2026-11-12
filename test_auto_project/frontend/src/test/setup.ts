import '@testing-library/jest-dom/vitest';

import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';

import { clearStreams } from '../api/stream';
import { server } from './server';

// jsdom 은 상대 주소 fetch 를 모른다 — 화면처럼 같은 서버 기준으로
const origin = 'http://localhost';
const realFetch = globalThis.fetch;
globalThis.fetch = (input, init) =>
  realFetch(typeof input === 'string' && input.startsWith('/') ? origin + input : input, init);

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  clearStreams();
});
afterAll(() => server.close());
