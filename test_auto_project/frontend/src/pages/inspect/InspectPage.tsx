import sc from '../../components/scenario.module.css';
import { Spinner } from '../../components/Spinner';
import { useStore } from '../../lib/store';
import { AnalysisCards } from './AnalysisCards';
import { GateCard } from './GateCard';
import { InputCard } from './InputCard';
import { inspect } from './inspectState';
import { IrArea } from './ir/IrArea';

/** 시나리오 등록(확인용) — 중간 발표용. ①②③ · 승인 게이트 · 혜정 IR 생성 과정을 다 보여 준다.
 *  여기서 승인한 승인본은 IR 생성에만 쓰고, 실행 메뉴의 등록 시나리오로는 남기지 않는다 (등록은 '시나리오 등록'). */
export default function InspectPage() {
  const { busy, analysis } = useStore(inspect);
  return (
    <>
      <div className={sc.grid}>
        <div>
          <InputCard />
          <GateCard />
        </div>
        <div className={sc.right} aria-live="polite" aria-busy={busy || undefined}>
          {busy ? <Spinner block label="분석 중" /> : analysis && <AnalysisCards a={analysis} />}
        </div>
      </div>
      <IrArea />
    </>
  );
}
