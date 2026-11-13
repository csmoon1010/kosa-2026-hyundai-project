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

// React Flow 가 쓰는 브라우저 기능 — jsdom 에 없어 흉내 (React Flow 문서의 테스트 준비)
class ResizeObserverMock {
  constructor(private cb: ResizeObserverCallback) {}
  observe(target: Element) {
    this.cb(
      [{ target, contentRect: { width: 1000, height: 500 } } as unknown as ResizeObserverEntry],
      this as unknown as ResizeObserver,
    );
  }
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverMock as unknown as typeof ResizeObserver;
class DOMMatrixReadOnlyMock {
  m22: number;
  constructor(transform?: string) {
    const scale = transform?.match(/scale\(([1-9.])\)/)?.[1];
    this.m22 = scale !== undefined ? +scale : 1;
  }
}
globalThis.DOMMatrixReadOnly ??= DOMMatrixReadOnlyMock as unknown as typeof DOMMatrixReadOnly;
Object.defineProperties(HTMLElement.prototype, {
  offsetHeight: { get: () => 500, configurable: true },
  offsetWidth: { get: () => 1000, configurable: true },
});

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  clearStreams();
});
afterAll(() => server.close());
