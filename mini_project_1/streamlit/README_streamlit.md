# Hmall 협력사 Adaptive RAG 챗봇

`mini_project_final.ipynb`의 최종 Adaptive RAG를 사용하는 Streamlit 앱이다. 화면은 `day03/streamlit/6_chat.py`의 제목·안내 expander·채팅·입력·상태 사이드바 구성으로 유지한다.

## 실행

현재 실습 디렉터리(`csmoon1010`)에서 실행한다.

```bash
.venv/bin/python -m pip install -r day05/mini_project_1/streamlit/requirements_streamlit.txt
.venv/bin/python -m streamlit run day05/mini_project_1/streamlit/streamlit_chat.py
streamlit run day05/mini_project_1/streamlit/streamlit_chat.py --server.fileWatcherType none
```

기존 `.venv`에 필요한 패키지가 있으면 설치 명령은 생략한다. 앱의 파일 위치로 데이터·환경 파일 경로를 계산하므로 다른 디렉터리에서 절대 경로로 실행해도 된다.

`csmoon1010/.env` 또는 실행 환경에 다음 변수를 설정한다. 환경변수가 `.env`보다 우선한다. 키 값은 코드·캐시 설정·화면에 포함하지 않는다.

```dotenv
OPENAI_API_KEY=사용할_API_키
OPENAI_DEFAULT_MODEL=문서_파싱용_상위_모델
OPENAI_LOWER_MODEL=질문_보완_분류_리랭킹_답변용_모델
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

기존 노트북 인덱스를 사용할 때에는 노트북과 같은 임베딩 모델을 사용한다. `OPENAI_JUDGE_MODEL` 등 평가용 변수는 앱에서 사용하지 않는다.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `streamlit_chat.py` | 기존 예제 형태의 UI·세션 상태와 유일한 자원 캐시 함수 |
| `rag_config.py` | 환경 설정·데이터 경로 |
| `prepare_index.py` | 최초 인덱스 확인·필요한 최초 구축·PDF 파싱·청킹 |
| `adaptive_rag.py` | 모델·검색기·체인 준비와 Adaptive 그래프 |
| `chat_service.py` | 대화 이력 제한·질문 보완·답변 스트리밍·현재 출처 수집 |
| `tests/test_chatbot.py` | API를 호출하지 않는 그래프·UI·상태·최초 적재 동작 확인 |

노트북을 실행하거나 import하지 않는다. 데이터는 상위 `mini_project_1/`의 `files/`, `md_cache/`, `chroma_db/`, `parent_document_store/`를 사용한다.

## 인덱스 최초 준비

앱 시작 시 저장소를 확인하고 호환 인덱스가 있으면 재사용한다. 모든 저장소가 없으면 PDF 파싱·청킹·임베딩 적재를 자동 수행한다. BASE가 있고 부모·자식이 모두 없으면 BASE를 보존하고 부모·자식만 최초 구축한다. 최초 파싱·임베딩에는 시간과 API 비용이 발생할 수 있다.

설정 불일치, 빈 컬렉션, 부모·자식 일부만 존재하는 경우는 자동으로 덮어쓰거나 재구축하지 않는다. 최초 적재에는 프로세스 간 파일 잠금을 적용한다. 중간 실패 시 `mini_project_1/chroma_db.initializing` 표식을 남겨 다음 실행에서 불완전 적재를 알린다. 표식만 지워서 재시도하지 말고 앱을 중단한 상태에서 저장소를 확인·정리한다. 기존 노트북의 정상 인덱스는 이 표식이 없어도 재사용한다.

서비스 시작 이후에는 다시 구축하지 않는다. DB 또는 부모 저장소 변경을 감지하면 안내하고 질문 처리를 중단한다. 인덱스를 변경할 때는 모든 앱 프로세스를 종료하고 외부에서 준비한 뒤 앱을 재시작한다. 별도 준비 명령도 사용할 수 있다.

```bash
.venv/bin/python day05/mini_project_1/streamlit/prepare_index.py
```

## 대화와 스트리밍

- 질문 의미 해석에는 최근 최대 **6턴·4,000토큰** 이력을 사용한다. 1턴은 사용자 입력과 assistant 응답 한 쌍이다. 전체 화면 기록은 별도로 유지한다.
- 확인 질문과 사용자의 짧은 선택 답변도 연결한다. 모호하면 확인 질문을 표시하고 검색을 실행하지 않는다.
- 기본 벡터 검색 K=6, 조건 질문 Parent Document, 부정/예외 질문 후보 12개→LLM 리랭킹 6개의 정책을 사용한다. 분류 확신도 0.8 미만·분류 실패·특수 검색 실패는 기본 검색으로 복귀한다.
- 최종 답변 모델을 한 번 호출하고 그 토큰을 `st.write_stream`으로 표시한다. 분류·리랭킹·질문 보완 출력은 화면에 노출하지 않는다.
- 완료 답변의 출처와 검색 정보는 해당 세션의 메시지에 저장한다. 출처 패널 등 추가 UI는 없다. 이전 대화는 질문 해석용이며 업무 답변 근거는 현재 검색 문서로 제한한다.
- 중단된 응답은 정상 답변으로 저장하지 않으며 다음 질문의 이력에서 제외한다.

`get_resources(settings)`만 `st.cache_resource`를 사용한다. 공유 자원에 대화·요청 결과·누적 사용량을 저장하지 않는다. 대화 초기화는 해당 세션만 비우며 인덱스와 공유 자원은 유지한다.

벤치마크·골든셋 생성·RAGAS 평가·기존 실패 사례 분석은 포함하지 않는다.

## 동작 확인

```bash
.venv/bin/python -m unittest discover -s day05/mini_project_1/streamlit/tests -v
```

테스트는 모의 모델·임베딩과 임시 저장소를 사용한다. 실제 API 키로 외부 모델을 호출하지 않고 분기·복귀·토큰 전달·이력 제한·확인 질문·중단 처리·최초 적재·UI 재실행·세션 분리를 확인한다. 실제 문서 답변의 품질 평가를 대체하는 테스트는 아니다.
