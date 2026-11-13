import { useState } from 'react';

import { del, post, type Schemas } from '../../../api/client';
import { useRefreshAdmin } from '../../../api/queries';
import { Card } from '../../../components/Card';
import { Modal } from '../../../components/Modal';
import { useToast } from '../../../lib/useToast';
import type { AdminData } from '../adminData';
import styles from '../admin.module.css';
import { Checks, type Check } from '../parts';
import { DOM_LABEL } from '../scope';
import {
  DOC_LABEL,
  DOC_OPTIONS,
  RULE_ITEMS,
  isAllowed,
  itemMeta,
  ruleRows,
  savedMessage,
  targetLabel,
  targetsFor,
  validateRule,
  type DocKey,
  type Place,
} from './ruleModel';

const DOC_CLS: Record<DocKey, string> = {
  sv: styles.dpSv!,
  pkb: styles.dpPkb!,
  cat: styles.dpCat!,
  meta: styles.dpMeta!,
};

/** 규칙 입력 — 저장 대상 · 대상 · 항목 · 내용 → 검증 → data/config/rules.ui.yaml + 다시 빌드. 전사(am) · 도메인(ov) */
export function RuleCard({ a, place, dom }: { a: AdminData; place: Place; dom: string | null }) {
  const refresh = useRefreshAdmin();
  const [toast, show] = useToast();
  const [doc, setDoc] = useState<DocKey>(DOC_OPTIONS[place][0]![0]);
  const [itemPick, setItem] = useState('');
  const [targetPick, setTarget] = useState('');
  const [body, setBody] = useState('');
  const [result, setResult] = useState<{ checks: Check[]; reject: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState(false);

  // 고른 값이 목록에 없으면 첫 항목 (지금 화면처럼)
  const items = RULE_ITEMS[doc];
  const item = items.some((x) => x[0] === itemPick) ? itemPick : items[0]![0];
  const targets = targetsFor(a, place, dom, doc, item);
  const target = targets.some((t) => t[0] === targetPick) ? targetPick : (targets[0]?.[0] ?? '');
  const meta = itemMeta(doc, item)!;
  const rows = ruleRows(a, place, dom);

  async function save() {
    const text = body.trim();
    const checks = validateRule(a, place, doc, item, target, text);
    if (!checks.every((c) => c[0])) {
      setResult({ checks, reject: '검증을 통과하지 못했습니다.' });
      show('검증 실패 — 적용하지 않았습니다.');
      return;
    }
    setResult({ checks, reject: null });
    setBusy(true);
    try {
      const j = await post<{ build: Schemas['BuildInfo'] }>('/api/admin/rules', {
        place,
        doc,
        item,
        dom: place === 'ov' ? dom : null,
        target,
        body: text,
      });
      setBody('');
      await refresh();
      show(savedMessage(doc, item, j.build.catalog_version));
    } catch (e) {
      setResult({
        checks: [...checks, [false, (e as Error).message]],
        reject: '서버가 거절했습니다 — 파일은 바뀌지 않았습니다.',
      });
      show('저장 실패: ' + (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    try {
      await del('/api/admin/rules/' + id);
      await refresh();
      show('규칙을 지우고 다시 빌드했습니다.');
    } catch (e) {
      show('삭제 실패: ' + (e as Error).message);
    }
  }

  const id = `rule-${place}`;
  return (
    <Card
      className={styles.wide}
      title="규칙 입력"
      actions={
        <button className="btn btn-ghost btn-sm" type="button" onClick={() => setHistory(true)}>
          등록된 내역 ({rows.length})
        </button>
      }
    >
      <div className={styles.cf3}>
        <div>
          <label htmlFor={`${id}-doc`}>저장 대상</label>
          <select id={`${id}-doc`} value={doc} onChange={(e) => setDoc(e.target.value as DocKey)}>
            {DOC_OPTIONS[place].map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={`${id}-tgt`}>{targetLabel(doc, item)}</label>
          <select id={`${id}-tgt`} value={target} onChange={(e) => setTarget(e.target.value)}>
            {targets.length ? (
              targets.map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))
            ) : (
              <option value="">대상 없음</option>
            )}
          </select>
        </div>
        <div>
          <label htmlFor={`${id}-item`}>항목</label>
          <select id={`${id}-item`} value={item} onChange={(e) => setItem(e.target.value)}>
            {items.map(([k, label]) => (
              <option key={k} value={k}>
                {label}
                {isAllowed(place, doc, k) ? '' : ' — 다른 메뉴'}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div style={{ marginBottom: 11 }}>
        <label className="lb" htmlFor={`${id}-body`}>
          {meta[1]}
        </label>
        <input
          type="text"
          id={`${id}-body`}
          spellCheck={false}
          placeholder={meta[2]}
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
        <p className="note" style={{ marginTop: 5 }}>
          {meta[3]}
        </p>
      </div>
      <div className="btn-row" style={{ marginTop: 0 }}>
        <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => void save()}>
          저장 · 적용
        </button>
      </div>
      {result && (
        <Checks
          checks={result.checks}
          reject={result.reject ? { title: '적용 거부', text: result.reject } : null}
        />
      )}
      <p className="toast" role="status" hidden={!toast}>
        {toast}
      </p>
      {history && (
        <Modal
          wide
          eyebrow={place === 'am' ? '규칙 입력 · 전사' : `규칙 입력 · ${dom ? DOM_LABEL[dom] : ''}`}
          title="등록된 내역"
          onClose={() => setHistory(false)}
        >
          {rows.length ? (
            rows.map((r, i) => (
              <div key={i} className={styles.rrow}>
                <span className={`${styles.docPill} ${DOC_CLS[r.doc] ?? ''}`}>
                  {DOC_LABEL[r.doc] ?? r.doc}
                </span>
                <span className={styles.ruleKind}>{itemMeta(r.doc, r.item)?.[1] ?? r.item}</span>
                <span className={styles.f} title={r.target}>
                  {r.label}
                </span>
                <span>{r.body}</span>
                <span className={styles.m}>
                  {r.by} · {r.at}
                  {r.id !== undefined && (
                    <>
                      {' '}
                      <button className="xlink" type="button" onClick={() => void remove(r.id!)}>
                        삭제
                      </button>
                    </>
                  )}
                </span>
              </div>
            ))
          ) : (
            <p className="note">등록된 규칙이 없습니다.</p>
          )}
        </Modal>
      )}
    </Card>
  );
}
