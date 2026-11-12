import { useStored } from '../../lib/storage';
import type { GenerationOptions } from './flow';

/** 시나리오 생성 옵션 — 중지조건 · 재시도는 늘 켬, 압축 1 · 2 는 사용자가 고른다. 고른 값은 브라우저에 기억 (지금 화면과 같은 이름) */
export function useGenerationOptions(): [
  GenerationOptions,
  (key: keyof GenerationOptions, on: boolean) => void,
] {
  const [kb, setKb] = useStored('tdg.opt.kb_rag');
  const [dep, setDep] = useStored('tdg.opt.dependency_projection');
  const options = { kb_rag: kb === '1', dependency_projection: dep === '1' };
  const set = (key: keyof GenerationOptions, on: boolean) =>
    (key === 'kb_rag' ? setKb : setDep)(on ? '1' : '');
  return [options, set];
}
