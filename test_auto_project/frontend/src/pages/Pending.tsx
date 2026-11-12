import { Card } from '../components/Card';

/** 아직 옮기지 않은 화면 — 옮길 단계(docs/react.md 7절)를 알린다. 단계를 마치면 이 파일을 쓰는 곳이 없어진다. */
export function Pending({ phase }: { phase: string }) {
  return (
    <Card eyebrow={phase}>
      <p>이 화면은 아직 옮기는 중입니다. 지금 화면은 FastAPI 서버 주소(/)에서 씁니다.</p>
    </Card>
  );
}
