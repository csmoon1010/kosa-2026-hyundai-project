import { useOperations } from '../../api/queries';
import sc from '../../components/scenario.module.css';
import { RunStage } from './RunStage';
import { ScenarioPicker } from './ScenarioPicker';

/** 시나리오 실행 — 등록 시나리오를 담아 드라이런 (실행기 연결 전) */
export default function RunPage() {
  useOperations(); // 입력값 표의 필드 한글명 — 결과가 뜨기 전에 미리 받아 둔다
  return (
    <div className={sc.grid}>
      <div>
        <ScenarioPicker />
      </div>
      <div className={sc.right}>
        <RunStage />
      </div>
    </div>
  );
}
