import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Stepper } from './Stepper';

describe('Stepper', () => {
  it('단계 상태를 표시 · 읽어 준다 — 진행 중 숫자는 진행 중일 때만', () => {
    render(
      <Stepper
        steps={[
          { key: 'intent', label: '요청 이해', state: 'done' },
          { key: 'ir', label: '시나리오 생성', state: 'now', count: '2/5' },
          { key: 'x', label: '등록', state: 'wait', count: '9/9' },
        ]}
      />,
    );
    const items = screen.getAllByRole('listitem');
    expect(items.map((li) => li.getAttribute('data-s'))).toEqual(['done', 'now', 'wait']);
    expect(items[0]).toHaveTextContent('✓요청 이해 — 완료');
    expect(items[1]).toHaveTextContent('시나리오 생성2/5 — 진행 중');
    expect(items[2]).toHaveTextContent('3등록 — 대기');
  });
});
