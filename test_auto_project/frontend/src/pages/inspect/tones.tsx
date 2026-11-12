// 확인용 화면의 상태 알약 색 · 시간 표시 — 분석 카드 · 승인 게이트 공통
import { Pill, type Tone } from '../../components/Pill';

// 상태 알약 색 — 지금 화면의 AG_SEL · AG_FINAL (st-ok → good, st-rb → signal, st-rj → muted)
export const SEL_TONE: Record<string, Tone> = {
  고정: 'good',
  선택: 'good',
  가선택: 'signal',
  보류: 'signal',
};
export const NEED_TONE: Record<string, Tone> = {
  자동: 'muted',
  '시나리오 승인': 'good',
  '단계 승인': 'signal',
  차단: 'signal',
};
export const FINAL_TONE: Record<string, Tone> = {
  완료: 'good',
  '검토 필요': 'signal',
  보류: 'signal',
  '업무 없음': 'muted',
  자동: 'good',
  '승인 필요': 'signal',
  차단: 'signal',
  '실행할 것 없음': 'muted',
};
export const pill = (text: string, tones: Record<string, Tone>) => (
  <Pill tone={tones[text] ?? 'muted'}>{text}</Pill>
);

export const msTxt = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)}초` : `${ms}ms`);
