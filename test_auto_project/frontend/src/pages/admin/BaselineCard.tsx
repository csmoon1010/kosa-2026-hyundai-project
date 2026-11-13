import { useState } from 'react';

import { put } from '../../api/client';
import { usePreprocessing, useRefreshAdmin } from '../../api/queries';
import { Card } from '../../components/Card';
import { Modal } from '../../components/Modal';
import { Spinner } from '../../components/Spinner';
import { useToast } from '../../lib/useToast';
import type { AdminData } from './adminData';
import styles from './admin.module.css';
import { baselineDoc, preHelpers } from './docs/docsPre';
import { DOM_LABEL } from './scope';

/** 도메인 — Baseline Request (혜정 전처리 Baseline: parameter_path 별 기본 요청값을 사용자 등록) */
export function BaselineCard({ a, dom }: { a: AdminData; dom: string }) {
  const pre = usePreprocessing();
  const title = `Baseline Request · ${DOM_LABEL[dom]}`;
  if (!pre.data)
    return (
      <Card className={styles.wide} title={title}>
        {pre.isError ? (
          <p className="note">{pre.error.message}</p>
        ) : (
          <Spinner block label="전처리 산출물 불러오는 중" />
        )}
      </Card>
    );
  return <BaselineForm a={a} dom={dom} title={title} pre={pre.data.preprocessing} />;
}

type Pre = NonNullable<ReturnType<typeof usePreprocessing>['data']>['preprocessing'];
const valuesOf = (b: Pre['baselines'][string] | undefined) =>
  Object.fromEntries((b?.parameters ?? []).map((p) => [p.parameter_path, p.value]));

function BaselineForm({ a, dom, title, pre }: { a: AdminData; dom: string; title: string; pre: Pre }) {
  const refresh = useRefreshAdmin();
  const [toast, show] = useToast();
  const h = preHelpers(pre, a);
  const entries = h.apis(dom);
  const [pick, setPick] = useState('');
  const sid = entries.some(([s]) => s === pick) ? pick : (entries[0]?.[0] ?? '');
  const baseline = pre.baselines[sid];
  // 입력 중인 글 — 고른 API 마다. 없으면 저장된 값
  const [draft, setDraft] = useState<{ sid: string; text: string } | null>(null);
  const text = draft?.sid === sid ? draft.text : baseline ? JSON.stringify(valuesOf(baseline), null, 2) : '';
  const [history, setHistory] = useState(false);
  const registered = entries.filter(([s]) => pre.baselines[s]?.user_registered).length;

  async function save() {
    try {
      const values = JSON.parse(text);
      const saved = await put<{ file: string }>('/api/admin/preprocessing/baselines', {
        selected_api_id: sid,
        values,
      });
      setDraft(null);
      await refresh();
      show(`사용자 등록값 저장 · ${saved.file}`);
    } catch (e) {
      show('저장 실패: ' + (e as Error).message);
    }
  }

  return (
    <Card
      className={styles.wide}
      title={title}
      actions={
        <button className="btn btn-ghost btn-sm" type="button" onClick={() => setHistory(true)}>
          등록된 내역 ({registered} / {entries.length})
        </button>
      }
    >
      {!entries.length ? (
        <p className="note">해당 JSON 산출물이 없습니다. 전처리 실행 후 갱신해 주세요.</p>
      ) : (
        <>
          <div className={styles.cf3}>
            <div>
              <label htmlFor="blEp">대상 엔드포인트</label>
              <select id="blEp" value={sid} onChange={(e) => setPick(e.target.value)}>
                {entries.map(([s, c]) => (
                  <option key={s} value={s}>
                    {h.apiName(s, c)} · {c.apiId}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="blStat">등록 여부</label>
              <input
                type="text"
                id="blStat"
                readOnly
                value={
                  baseline?.user_registered ? '사용자 등록' : baseline ? '예시 초안 · 미등록' : '산출물 없음'
                }
              />
            </div>
          </div>
          <div style={{ marginBottom: 11 }}>
            <label className="lb" htmlFor="blBody">
              기본 요청값 · parameter_path별 JSON
            </label>
            <textarea
              id="blBody"
              className={styles.code}
              spellCheck={false}
              value={text}
              onChange={(e) => setDraft({ sid, text: e.target.value })}
            />
          </div>
          <div className="btn-row" style={{ marginTop: 0 }}>
            <button className="btn btn-primary btn-sm" type="button" onClick={() => void save()}>
              사용자 등록 · 검증
            </button>
            {baseline && (
              <button
                className="btn btn-ghost btn-sm"
                type="button"
                onClick={() => setDraft({ sid, text: JSON.stringify(baseline.example_values, null, 2) })}
              >
                example 초기값으로 채우기
              </button>
            )}
          </div>
        </>
      )}
      <p className="toast" role="status" hidden={!toast}>
        {toast}
      </p>
      {history && (
        <Modal wide eyebrow={title} title="등록된 내역" onClose={() => setHistory(false)}>
          {baselineDoc(pre, a, dom).body}
          <p className="note" style={{ marginTop: 10 }}>
            등록 상태는 실제 API 호출 성공 여부를 의미하지 않습니다.
          </p>
        </Modal>
      )}
    </Card>
  );
}
