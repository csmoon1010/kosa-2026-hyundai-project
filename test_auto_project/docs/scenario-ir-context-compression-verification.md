# Scenario IR 독립 옵션·컨텍스트 압축 검증 결과

작성일: 2026-11-01
상태: 기존 옵션·압축 동작은 자동 검증 완료. 아래 숫자 · 파일은 11-01 기준 기록이다.

> 2026-11-12 이후 바뀐 것
> - 실제 모델로 8개 조합을 비교했다 — `tap.eval_ir_options`, 정답셋 10문항, gpt-5.4, 11-07 조합당 1회 · 11-08 조합당 3회. 결과는 `data/out/eval/ir-options/` ([evaluation.md](evaluation.md)). 아래 '미실행' 절은 11-01 시점 기록이다.
> - 예산은 숫자 설정 4개 대신 STEP 수 기반으로 바뀌었다 (11-02, [scenario-ir-budget-plan.md](scenario-ir-budget-plan.md)).
> - 기록 파일(`data/out/evaluation/…`)은 처음 작업한 데모 폴더에 남아 있고 이 저장소에는 없다. 스크립트를 다시 돌리면 같은 위치에 생긴다.
> - API 선택 결과 불러오기 화면과 그 테스트는 지웠다 — 지금 화면 테스트는 `node --test tests/*.cjs`.

## 구현 결과

UI의 생성 모드 select를 독립 체크박스 3개로 교체했다. 중지조건·재시도, 압축 1, 압축 2를 자유롭게 조합한다. 초기값·기본값 복원은 모두 해제이며 생성 중 선택을 잠근다. 승인 직후 자동 생성과 승인본 재생성은 같은 옵션 전달 경로를 사용한다.

기존 generation_mode=basic/validated 요청을 지원하며, 새 generation_options와 충돌하면 오류를 반환한다. 실제 선택은 generation.options·시작 이벤트·결과 화면에 기록한다. 기존 숫자 예산 4개와 basic/validated의 검증 범위·수정 한도·저장 흐름은 유지한다.

압축 1은 데모 내부 data/out/parameters/parameter_vectors의 canonical_parameters_cf5a1c85ad4d 컬렉션을 읽는다. text-embedding-3-small/1536차원으로 질의를 임베딩하며, API 필터를 검색 전에 적용한다. 세 질의 범주는 현재 STEP 조건(선택된 관련 STEP 조건을 함께 포함), original_question, 승인된 현재 STEP selection_reason이다. 명확한 input_dependencies/output_consumers를 우선하고, 관계가 없거나 ambiguous이면 기존 KB tool call에 LLM이 후보 STEP ID·score·근거를 반환한다. 백엔드는 승인 후보 ID만 받고 0.7 이상 점수를 사용한다. 선택된 조건을 현재 조건 질의에 병합하므로 별도 질의나 별도 분류 LLM 호출을 늘리지 않는다. scope=expand는 최대 10, paths는 지정 경로 상세, full은 해당 API 전체 KB다. 원본 인덱스는 생성 중 sync하지 않는다. 인덱스 부재·해시 불일치·조회 오류·낮은 유사도는 이유를 기록하고 전체 KB로 전환한다. 임베딩 시도·토큰·시간을 계측하고 공유 예산에 포함한다.

압축 2는 선행 STEP 식별자·필요 출력과 후속 소비 관계·조건만 선별한다. STEP 수준의 의존성만 있으면 해당 STEP의 출력 전체를 남기며, 출처가 모호하면 후보를 보존한다. 필드까지 명시된 관계에서는 원본 출력 배열의 source_pointer를 제공해 인용 위치를 보존한다. 최종 수정 시에도 최신 전체 상태에서 같은 선별 함수를 실행한다. 백엔드 검증·조립용 원본은 유지한다.

`selection_reason`은 승인 자료에 저장된 기존 현재 STEP 문자열을 그대로 사용한다. LLM이 이를 도구 호출에서 새로 만들거나 연결 검색어로 재구성하지 않는다. 검색 뒤 `dependency_link_context`도 전달하지 않는다. STEP 연결은 기존 단계 문맥과 ParameterKB에 근거해 매핑하고, 백엔드는 source/output 존재·입력 경로·타입 호환성을 검사한다.

## 8가지 조합

아래 결과는 모의 모델·결정적인 검색 결과를 사용하되 실제 Runtime, 매핑 검사, 최종 저장 게이트를 통과시킨 자동 검사다. 실제 생성 모델의 품질 비교를 뜻하지 않는다.

| 중지조건·재시도 | 압축 1 | 압축 2 | Runtime·저장 | UI 선택·전달 | 일반 JSON·NDJSON API |
|---|---|---|---|---|---|
| 해제 | 해제 | 해제 | 통과 | 통과 | 통과 |
| 선택 | 해제 | 해제 | 통과 | 통과 | 통과 |
| 해제 | 선택 | 해제 | 통과 | 통과 | 통과 |
| 해제 | 해제 | 선택 | 통과 | 통과 | 통과 |
| 선택 | 선택 | 해제 | 통과 | 통과 | 통과 |
| 선택 | 해제 | 선택 | 통과 | 통과 | 통과 |
| 해제 | 선택 | 선택 | 통과 | 통과 | 통과 |
| 선택 | 선택 | 선택 | 통과 | 통과 | 통과 |

동일 조합에서 통신 재시도 선택 여부도 검사했다. 중지조건·재시도 선택 시에만 일시 통신 오류 추가 1회가 실행된다. 네 가지 validated 조합 모두 최종 수정에서도 옵션·선별 전략이 유지되는지 검사했다. 원본 pointer 인용, 모호한 출처, 미전달 KB 상세 확보, 오래된 인덱스 fallback, 조건별 k·확대 상한, 임베딩 예산 초과·실패 시도 집계도 확인했다.

최종 전체 Python 테스트 124개가 통과했다. 결과는 data/out/evaluation/context_automated.xml, 압축 집중 검사는 compression_targeted.xml, JavaScript 결과는 javascript_tests.json에 저장했다. Python 검사에는 Node 모의 DOM으로 실행한 스트리밍·옵션 UI 검사가 포함된다. 별도 JavaScript 검사에서는 API 선택 입력 11개와 전처리 UI 4개가 통과했다.

변경 전 Python 기준선은 88개 통과·1개 실패였다. 기존 Assertion 검사 기대값이 현재 inputs/outputs/bindings 전용 검증 범위와 달라 테스트를 기존 정책에 맞췄다. 제품 검증 범위를 확대하지 않았다. JavaScript 테스트 자료의 빈 API placeholder는 테스트 내부에서 유효 식별자로 대체하고, 빈 식별자 거부 검사도 유지했다. 사용자 예제 파일은 수정하지 않았다.

## 실제 Chroma 검색과 top-k 비교

실제 복사본 컬렉션을 열어 1816개 벡터를 확인했다. 저장 벡터 자체를 질의로 재사용하는 로컬 검사에서 API 필터와 검색 경로가 동작했다. 추가로 사전 정의한 12개 자연어 조건에 대해 실제 질의 임베딩을 생성해 검색했다. 기존 벡터를 전체 재생성하지 않았다.

| 조건별 k | 정답 후보 포함 |
|---|---|
| 1 | 9/12 |
| 2 | 11/12 |
| 3~10 | 12/12 |

기록: data/out/evaluation/kb_top_k.json
재현 스크립트: scripts/evaluate_kb_top_k.py

이 평가는 제한된 12문항의 후보 재현율이다. 최종 매핑 품질·총토큰을 비교한 최적값을 뜻하지 않는다. 따라서 서버 기본값은 요청한 초기 k=5로 유지하고, k=3은 후속 비교 후보로 둔다. 설정 위치는 src/tap/agent/config.py의 kb_top_k이며 정수 1~10만 허용한다.

## 압축 2 로컬 크기 비교

기존 IRRUN-20261101-205959 로그의 각 STEP 첫 입력 JSON을 로컬에서 재생해 선별했다. 4개 STEP의 합계는 47,585자에서 21,437자로 약 55% 감소했다. 기록은 data/out/evaluation/context_projection_offline.json이다. 이는 JSON 글자 수 비교로, 실제 모델 입력 토큰·출력 품질·캐시·비용 감소를 입증하지 않는다.

실시간 로그의 `context_projection` 응답에는 `selected_context.previous_steps`와 `selected_context.following_steps`를 포함한다. UI에서 `STEP 문맥 선별 · 백엔드` 행을 선택하면 선별 통계와 함께 LLM에 전달한 실제 문맥 JSON을 볼 수 있다.

## 미실행: 실제 생성 모델 반복 평가

동일 승인 예제로 8개 조합을 각 3회 실행하는 scripts/evaluate_context_compression.py를 준비했다. 그러나 24회 실행 요청은 자동 승인 검토에서 거절되어 실행하지 않았다. 거절 사유는 로컬 시나리오·KB 내용의 외부 API 전송과 유료 호출에 대한 구체적인 승인이 부족하다는 것이다. 생성 결과의 품질 유지·누적 입력 토큰·캐시·비용·지연의 비교는 아직 완료되지 않았다.

평가를 승인받으면 우선 k=5의 24회 비교를 수행하고, 필요하면 압축 1을 사용하는 네 조합에 대해 k=3을 각 3회 추가 비교한다. 합계 최대 36회다. 같은 예제의 반복은 편차 확인용이며, 다른 업무까지의 품질 보장은 별도 태스크 확장이 필요하다. 실제 모델 평가 통과 전에는 최적 k 선정이나 전체 성능 유지가 입증되었다고 표시하지 않는다.

## 사용·검증

서버를 재시작하고 브라우저를 강력 새로고침하면 체크박스 UI를 사용할 수 있다. pyproject.toml 에 명시한 chromadb==1.5.9가 필요하다. 기존 코드·기존 모드 요청의 기본값은 그대로 사용할 수 있다.

```bash
.venv/bin/python -m pytest -q
node --test tests/*.cjs
```

실제 API를 사용하는 두 평가 스크립트는 일반 회귀 검사에 포함하지 않았다. 로컬 자동 검증은 유료 모델 호출 없이 실행된다.
