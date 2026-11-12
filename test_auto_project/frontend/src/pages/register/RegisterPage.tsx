import { useOperations } from '../../api/queries';
import { NewScenarioCard } from './NewScenarioCard';
import { RegisteredList } from './RegisteredList';
import { ResultArea } from './ResultArea';
import sc from '../../components/scenario.module.css';

/** 시나리오 등록 — 자연어 요청 → 분석(①②③) → 시나리오 생성(IR) → 승인 · 등록.
 *  중간 산출물(후보 · 점수 · 트레이스 · 생성 로그)은 보여 주지 않는다 — 그건 '시나리오 등록(확인용)' 화면. */
export default function RegisterPage() {
  useOperations(); // 입력값 표의 필드 한글명 — 미리보기가 뜨기 전에 미리 받아 둔다
  return (
    <>
      <RegisteredList />
      <div className={sc.grid}>
        <div>
          <NewScenarioCard />
        </div>
        <div className={sc.right}>
          <ResultArea />
        </div>
      </div>
    </>
  );
}
